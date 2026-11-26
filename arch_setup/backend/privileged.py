"""Privileged worker executed via `pkexec` for root-only Arch setup tasks.

Uses only the Python standard library so it works reliably under pkexec's
sanitized environment (which strips PYTHONPATH and user site variables).
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9@._+][a-zA-Z0-9@._+-]*$")

SYSCTL_CONTENT = """# Reduz uso de swap (prioriza RAM)
vm.swappiness=10

# Aumenta limite de arquivos monitorados (inotify)
fs.inotify.max_user_watches=524288

# Melhora performance de rede
net.core.rmem_max=134217728
net.core.wmem_max=134217728

# Kernel panic reboot
kernel.panic=10
"""

AUDIO_LIMITS_CONTENT = """# Limites para áudio em tempo real (PipeWire/JACK)
@audio - rtprio 95
@audio - memlock unlimited
"""

DEFAULT_ENV_VARS: dict[str, str] = {
    "MANGOHUD": "1",
    "RADV_PERFTEST": "aco,gpl",
    "MESA_SHADER_CACHE_MAX_SIZE": "10G",
}

DEFAULT_SMB_CONF = """[global]
  workgroup = WORKGROUP
  server string = Samba Server
  security = user
  map to guest = Bad User
  usershare path = /var/lib/samba/usershares
  usershare max shares = 100
  usershare allow guests = yes
  usershare owner only = yes
"""

SAMBA_USERSHARE_BLOCK = """  usershare path = /var/lib/samba/usershares
  usershare max shares = 100
  usershare allow guests = yes
  usershare owner only = yes"""


class PrivilegedError(RuntimeError):
    """Raised when a privileged task fails validation or execution."""


def emit(line: str) -> None:
    """Print and flush immediately so the GUI runner receives live output."""
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def log_info(msg: str) -> None:
    emit(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    emit(f"[AVISO] {msg}")


def log_error(msg: str) -> None:
    emit(f"[ERRO] {msg}")


def emit_step(current: int, total: int, label: str) -> None:
    emit(f"@@STEP {current} {total} {label}")


def validate_packages(packages: Any) -> list[str]:
    """Validate a non-empty list of pacman package names."""
    if not isinstance(packages, list) or not packages:
        raise PrivilegedError("Lista de pacotes inválida ou vazia.")
    cleaned: list[str] = []
    for pkg in packages:
        if not isinstance(pkg, str) or not PKG_NAME_RE.match(pkg):
            raise PrivilegedError(f"Nome de pacote inválido: {pkg!r}")
        cleaned.append(pkg)
    return cleaned


def resolve_target_user(raw_user: Any) -> str:
    """Validate target non-root user and match PKEXEC_UID when present."""
    if not isinstance(raw_user, str) or not raw_user or raw_user == "root":
        raise PrivilegedError(f"Usuário alvo inválido: {raw_user!r}")
    try:
        pw_target = pwd.getpwnam(raw_user)
    except KeyError as exc:
        raise PrivilegedError(f"Usuário não encontrado: {raw_user!r}") from exc

    pkexec_uid = os.environ.get("PKEXEC_UID")
    if pkexec_uid is not None:
        try:
            caller_pw = pwd.getpwuid(int(pkexec_uid))
        except (ValueError, KeyError) as exc:
            raise PrivilegedError("PKEXEC_UID inválido.") from exc
        if caller_pw.pw_name != pw_target.pw_name:
            raise PrivilegedError(
                f"Usuário alvo ({raw_user}) diverge do chamador pkexec ({caller_pw.pw_name})."
            )
    return pw_target.pw_name


def run_cmd(
    cmd: list[str],
    *,
    dry_run: bool = False,
    check: bool = True,
    stream: bool = True,
) -> int:
    """Run a command, streaming stdout/stderr line-by-line when requested."""
    if dry_run:
        log_info(f"[dry-run] Executaria: {' '.join(cmd)}")
        return 0

    if not stream:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                emit(line)
        if proc.stderr:
            for line in proc.stderr.splitlines():
                emit(line)
        if check and proc.returncode != 0:
            raise PrivilegedError(
                f"Comando falhou (código {proc.returncode}): {' '.join(cmd)}"
            )
        return proc.returncode

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        emit(line.rstrip("\r\n"))
    returncode = proc.wait()
    if check and returncode != 0:
        raise PrivilegedError(f"Comando falhou (código {returncode}): {' '.join(cmd)}")
    return returncode


def user_in_group(username: str, group_name: str) -> bool:
    """Check whether username belongs to group_name."""
    try:
        group_entry = grp.getgrnam(group_name)
        if username in group_entry.gr_mem:
            return True
    except KeyError:
        return False
    try:
        pw_entry = pwd.getpwnam(username)
        return pw_entry.pw_gid == group_entry.gr_gid
    except KeyError:
        return False


def ensure_user_in_group(username: str, group_name: str, *, dry_run: bool) -> None:
    """Add user to group if not already a member."""
    if user_in_group(username, group_name):
        log_warn(f"Usuário {username} já está no grupo {group_name}")
        return
    run_cmd(["gpasswd", "-a", username, group_name], dry_run=dry_run, stream=False)
    log_info(f"Usuário {username} adicionado ao grupo {group_name}")


def handle_pacman_install(params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    packages = validate_packages(params.get("packages"))
    log_info(f"Instalando {len(packages)} pacote(s) via pacman: {' '.join(packages)}")
    run_cmd(["pacman", "-S", "--needed", "--noconfirm", *packages], dry_run=dry_run)


def handle_configure_makepkg_jobs(
    params: dict[str, Any], *, dry_run: bool, **_: Any
) -> None:
    process_count = getattr(os, "process_cpu_count", None)
    fallback = int(process_count() or 0) if callable(process_count) else 0
    cores = params.get("cores") or fallback or (os.cpu_count() or 1)
    if not isinstance(cores, int) or cores < 1 or cores > 1024:
        raise PrivilegedError(f"Número de núcleos inválido: {cores!r}")

    makepkg_conf = Path("/etc/makepkg.conf")
    log_info(f"Configurando MAKEFLAGS=\"-j{cores}\" em {makepkg_conf}...")
    if dry_run:
        log_info(f"[dry-run] Atualizaria MAKEFLAGS para -j{cores} em {makepkg_conf}")
        return

    try:
        text = makepkg_conf.read_text(encoding="utf-8")
    except OSError:
        text = ""
        log_warn(f"{makepkg_conf} não encontrado; o arquivo será criado")

    bak = makepkg_conf.with_suffix(".conf.bak")
    try:
        shutil.copy2(makepkg_conf, bak)
        log_info(f"Backup criado: {bak}")
    except OSError:
        log_warn(f"Não foi possível criar backup de {makepkg_conf}")

    pattern = re.compile(r'^#?MAKEFLAGS="-j[0-9]*"', re.MULTILINE)
    replacement = f'MAKEFLAGS="-j{cores}"'
    if pattern.search(text):
        new_text = pattern.sub(replacement, text)
    else:
        suffix = "" if text.endswith("\n") else "\n"
        new_text = f"{text}{suffix}{replacement}\n"
    makepkg_conf.write_text(new_text, encoding="utf-8")
    log_info(f"MAKEFLAGS definido para -j{cores}.")


def handle_configure_env(_params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    env_file = Path("/etc/environment")
    bak_file = Path("/etc/environment.bak")
    log_info("Configurando /etc/environment...")
    if dry_run:
        log_info("[dry-run] Garantiria variáveis AMD/Mesa em /etc/environment")
        return

    if env_file.exists() and not bak_file.exists():
        shutil.copy2(env_file, bak_file)
        log_info(f"Backup criado: {bak_file}")

    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = existing.splitlines()
    added: list[str] = []
    for key, value in DEFAULT_ENV_VARS.items():
        if any(line.startswith(f"{key}=") for line in lines):
            log_warn(f"{key} já definido em /etc/environment")
        else:
            lines.append(f"{key}={value}")
            added.append(key)
            log_info(f"{key}={value} adicionado ao /etc/environment")

    if added or not env_file.exists():
        content = "\n".join(lines) + ("\n" if lines else "")
        env_file.write_text(content, encoding="utf-8")


def handle_configure_sysctl(_params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    sysctl_file = Path("/etc/sysctl.d/99-performance.conf")
    log_info(f"Aplicando sysctl tweaks em {sysctl_file}...")
    if dry_run:
        log_info(f"[dry-run] Escreveria {sysctl_file} e executaria sysctl --load")
        return

    sysctl_file.parent.mkdir(parents=True, exist_ok=True)
    sysctl_file.write_text(SYSCTL_CONTENT, encoding="utf-8")
    run_cmd(["sysctl", f"--load={sysctl_file}"], dry_run=dry_run, stream=False)
    log_info(f"Sysctl tweaks aplicados em {sysctl_file}")


def handle_configure_audio_limits(
    _params: dict[str, Any], *, target_user: str | None, dry_run: bool, **_: Any
) -> None:
    limits_file = Path("/etc/security/limits.d/99-audio.conf")
    log_info("Configurando limites de áudio em tempo real...")
    if not dry_run:
        limits_file.parent.mkdir(parents=True, exist_ok=True)
        limits_file.write_text(AUDIO_LIMITS_CONTENT, encoding="utf-8")
    else:
        log_info(f"[dry-run] Escreveria {limits_file}")

    if target_user:
        ensure_user_in_group(target_user, "audio", dry_run=dry_run)


def handle_enable_fstrim(_params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    log_info("Habilitando TRIM automático para SSD (fstrim.timer)...")
    run_cmd(["systemctl", "enable", "fstrim.timer"], dry_run=dry_run, stream=False)
    run_cmd(["systemctl", "start", "fstrim.timer"], dry_run=dry_run, stream=False)
    log_info("fstrim.timer habilitado e iniciado")


def handle_configure_systemd_timeout(
    _params: dict[str, Any], *, dry_run: bool, **_: Any
) -> None:
    conf = Path("/etc/systemd/system.conf")
    log_info("Configurando DefaultTimeoutStopSec=10s em /etc/systemd/system.conf...")
    if dry_run:
        log_info("[dry-run] Atualizaria DefaultTimeoutStopSec=10s")
        return
    if not conf.exists():
        log_warn(f"{conf} não encontrado; pulando")
        return
    text = conf.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r"^#?DefaultTimeoutStopSec=.*$",
        "DefaultTimeoutStopSec=10s",
        text,
        flags=re.MULTILINE,
    )
    if count == 0:
        log_warn("Linha DefaultTimeoutStopSec não encontrada em system.conf")
    else:
        conf.write_text(new_text, encoding="utf-8")
        log_info("DefaultTimeoutStopSec=10s aplicado")


def handle_setup_virt_manager(
    _params: dict[str, Any], *, target_user: str | None, dry_run: bool, **_: Any
) -> None:
    log_info("Configurando libvirtd e rede padrão...")
    run_cmd(["systemctl", "enable", "libvirtd.service"], dry_run=dry_run, stream=False)
    run_cmd(["systemctl", "start", "libvirtd.service"], dry_run=dry_run, stream=False)

    rc = run_cmd(["virsh", "net-start", "default"], dry_run=dry_run, check=False, stream=False)
    if rc != 0:
        log_warn("Rede 'default' já está ativa ou não pôde ser iniciada")
    rc = run_cmd(["virsh", "net-autostart", "default"], dry_run=dry_run, check=False, stream=False)
    if rc != 0:
        log_warn("Rede 'default' já em autostart")

    libvirtd_conf = Path("/etc/libvirt/libvirtd.conf")
    if dry_run:
        log_info(f"[dry-run] Configuraria permissões em {libvirtd_conf}")
    elif libvirtd_conf.exists():
        text = libvirtd_conf.read_text(encoding="utf-8")
        text = re.sub(
            r"^#unix_sock_group =.*$",
            'unix_sock_group = "libvirt"',
            text,
            flags=re.MULTILINE,
        )
        text = re.sub(
            r"^#unix_sock_rw_perms =.*$",
            'unix_sock_rw_perms = "0770"',
            text,
            flags=re.MULTILINE,
        )
        libvirtd_conf.write_text(text, encoding="utf-8")

    if target_user:
        ensure_user_in_group(target_user, "libvirt", dry_run=dry_run)

    run_cmd(["systemctl", "restart", "libvirtd.service"], dry_run=dry_run, stream=False)
    log_info("Virt-Manager configurado com sucesso")


def handle_setup_samba(
    _params: dict[str, Any], *, target_user: str | None, dry_run: bool, **_: Any
) -> None:
    log_info("Configurando Samba e usershares...")
    usershares = Path("/var/lib/samba/usershares")
    if dry_run:
        log_info("[dry-run] Configuraria /var/lib/samba/usershares e /etc/samba/smb.conf")
    else:
        usershares.mkdir(parents=True, exist_ok=True)
        run_cmd(["groupadd", "-r", "sambashares"], dry_run=False, check=False, stream=False)
        try:
            sambashares_gid = grp.getgrnam("sambashares").gr_gid
            os.chown(usershares, 0, sambashares_gid)
            os.chmod(usershares, 0o1770)
        except KeyError:
            log_warn("Grupo sambashares não encontrado; ajuste permissões manualmente")

        smb_conf = Path("/etc/samba/smb.conf")
        smb_bak = Path("/etc/samba/smb.conf.bak")
        if smb_conf.exists() and not smb_bak.exists():
            shutil.copy2(smb_conf, smb_bak)

        if not smb_conf.exists():
            smb_conf.parent.mkdir(parents=True, exist_ok=True)
            smb_conf.write_text(DEFAULT_SMB_CONF, encoding="utf-8")
        else:
            content = smb_conf.read_text(encoding="utf-8")
            if "usershare path" in content:
                log_warn("Usershare já configurado no smb.conf")
            elif re.search(r"^\[global\]", content, re.MULTILINE):
                content = re.sub(
                    r"^(\[global\][ \t]*)$",
                    f"\\1\n{SAMBA_USERSHARE_BLOCK}",
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                smb_conf.write_text(content, encoding="utf-8")
            else:
                suffix = "" if content.endswith("\n") else "\n"
                smb_conf.write_text(
                    f"{content}{suffix}\n[global]\n{SAMBA_USERSHARE_BLOCK}\n",
                    encoding="utf-8",
                )

    rc = run_cmd(
        ["testparm", "-s", "/etc/samba/smb.conf"],
        dry_run=dry_run,
        check=False,
        stream=False,
    )
    if rc != 0:
        log_warn("Avisos na validação do smb.conf via testparm")

    if target_user:
        ensure_user_in_group(target_user, "sambashares", dry_run=dry_run)

    for svc in ("smb.service", "nmb.service"):
        run_cmd(["systemctl", "restart", svc], dry_run=dry_run, stream=False)
        run_cmd(["systemctl", "enable", svc], dry_run=dry_run, stream=False)
    log_info("Samba configurado com sucesso")


def handle_setup_cups(_params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    log_info("Habilitando CUPS e Avahi (mDNS)...")
    for svc in ("cups.service", "avahi-daemon.service"):
        run_cmd(["systemctl", "enable", svc], dry_run=dry_run, stream=False)
        run_cmd(["systemctl", "start", svc], dry_run=dry_run, stream=False)

    nsswitch = Path("/etc/nsswitch.conf")
    if dry_run:
        log_info("[dry-run] Verificaria mdns_minimal em /etc/nsswitch.conf")
    elif nsswitch.exists():
        content = nsswitch.read_text(encoding="utf-8")
        if "mdns" in content:
            log_warn("mDNS já configurado em /etc/nsswitch.conf")
        elif re.search(r"^hosts:.*$", content, re.MULTILINE):
            new_content = re.sub(
                r"^hosts:.*$",
                "hosts: files mdns_minimal [NOTFOUND=return] dns",
                content,
                flags=re.MULTILINE,
            )
            nsswitch.write_text(new_content, encoding="utf-8")
            log_info("mDNS configurado em /etc/nsswitch.conf")
        else:
            log_warn("Linha 'hosts:' não encontrada em /etc/nsswitch.conf")


def handle_noop_check(params: dict[str, Any], *, dry_run: bool, **_: Any) -> None:
    message = str(params.get("message", "Verificação concluída"))
    log_info(f"{message} (dry_run={dry_run})")


TASK_HANDLERS = {
    "pacman_install": handle_pacman_install,
    "configure_makepkg_jobs": handle_configure_makepkg_jobs,
    "configure_env": handle_configure_env,
    "configure_sysctl": handle_configure_sysctl,
    "configure_audio_limits": handle_configure_audio_limits,
    "enable_fstrim": handle_enable_fstrim,
    "configure_systemd_timeout": handle_configure_systemd_timeout,
    "setup_virt_manager": handle_setup_virt_manager,
    "setup_samba": handle_setup_samba,
    "setup_cups": handle_setup_cups,
    "noop_check": handle_noop_check,
}


def execute_manifest(manifest: dict[str, Any], *, dry_run: bool = False) -> None:
    """Validate and execute all tasks in a manifest sequentially."""
    if not isinstance(manifest, dict):
        raise PrivilegedError("Manifesto deve ser um objeto JSON.")

    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise PrivilegedError("Manifesto sem tarefas para executar.")

    raw_user = manifest.get("target_user")
    target_user = resolve_target_user(raw_user) if raw_user is not None else None

    total = len(tasks)
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise PrivilegedError(f"Tarefa #{index} inválida.")
        action = task.get("action")
        if not isinstance(action, str) or action not in TASK_HANDLERS:
            raise PrivilegedError(f"Ação não permitida: {action!r}")

        label = str(task.get("label") or action)
        params = task.get("params") or {}
        if not isinstance(params, dict):
            raise PrivilegedError(f"Parâmetros inválidos na tarefa {action!r}")

        emit_step(index, total, label)
        TASK_HANDLERS[action](params, target_user=target_user, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arch Setup privileged worker")
    parser.add_argument("manifest", help="Caminho para o arquivo JSON de tarefas")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas valida e imprime ações sem alterar o sistema",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and os.geteuid() != 0:
        log_error("privileged.py deve ser executado como root via pkexec.")
        return 1

    try:
        manifest_path = Path(args.manifest)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        execute_manifest(manifest, dry_run=args.dry_run)
    except Exception as exc:
        log_error(str(exc))
        return 1

    log_info("Lote privilegiado concluído com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
