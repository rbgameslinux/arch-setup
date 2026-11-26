"""Serviços page — Fase 3: blocos expansíveis de Virt-Manager, Samba e CUPS."""

from __future__ import annotations

import getpass
import subprocess
from functools import lru_cache
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend import aur as aur_mod
from arch_setup.backend.privileged import user_in_group
from arch_setup.backend.runner import (
    ExecutionPlan,
    PrivilegedBatch,
    PrivilegedTask,
    TaskLogger,
    UserStep,
)
from arch_setup.models.catalog import (
    SERVICE_BLOCKS,
    ServiceBlock,
    get_installed_pacman_packages,
)
from arch_setup.ui.execution_dialog import ExecutionDialog
from arch_setup.ui.pages import escape_label

BLOCK_ACTIONS: dict[str, str] = {
    "virt_manager": "setup_virt_manager",
    "samba": "setup_samba",
    "cups": "setup_cups",
}


def _systemctl_state(service: str, verb: str, expected: str) -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", verb, service],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return proc.returncode == 0 and proc.stdout.strip() == expected
    except (OSError, subprocess.TimeoutExpired):
        return False


def service_is_enabled(service: str) -> bool:
    """`is-enabled` also returns 0 for static/alias units; require 'enabled'."""
    return _systemctl_state(service, "is-enabled", "enabled")


def service_is_active(service: str) -> bool:
    return _systemctl_state(service, "is-active", "active")


@lru_cache(maxsize=1)
def _installed_packages() -> frozenset[str]:
    return frozenset(get_installed_pacman_packages())


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def detect_block_state(block: ServiceBlock) -> bool:
    """Return True only when packages, services, groups and configs are in place."""
    if not block.services:
        return False
    if not set(block.repo_packages).issubset(_installed_packages()):
        return False
    if not all(
        service_is_enabled(svc) and service_is_active(svc) for svc in block.services
    ):
        return False
    username = getpass.getuser()
    if any(not user_in_group(username, group) for group in block.groups):
        return False

    if block.key == "virt_manager":
        conf = _read_text(Path("/etc/libvirt/libvirtd.conf"))
        return (
            'unix_sock_group = "libvirt"' in conf
            and 'unix_sock_rw_perms = "0770"' in conf
        )
    if block.key == "samba":
        return (
            Path("/var/lib/samba/usershares").is_dir()
            and "usershare path" in _read_text(Path("/etc/samba/smb.conf"))
        )
    if block.key == "cups":
        return "mdns" in _read_text(Path("/etc/nsswitch.conf"))
    return True


class ServicesPage(Adw.PreferencesPage):
    """Services installation page with per-block toggles."""

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Serviços")
        self.set_name("services")
        self.set_icon_name("network-server-symbolic")

        self._blocks: dict[str, ServiceBlock] = {block.key: block for block in SERVICE_BLOCKS}
        self._switch_rows: dict[str, Adw.SwitchRow] = {}
        self._expanders: dict[str, Adw.ExpanderRow] = {}
        self._build_ui()
        GLib.idle_add(self._refresh_state)

    # ─────────────────────────── UI construction ────────────────────────────

    def _build_ui(self) -> None:
        blocks_group = Adw.PreferencesGroup(
            title="Blocos de serviços",
            description=(
                "Clique num bloco para expandir, ver pacotes/serviços e "
                "marcar o que deseja instalar."
            ),
        )
        for block in SERVICE_BLOCKS:
            expander = Adw.ExpanderRow(
                title=escape_label(block.title),
                subtitle=escape_label(block.description),
            )
            count_lbl = Gtk.Label(
                label=f"{len(block.repo_packages) + len(block.aur_packages)} pacotes"
            )
            count_lbl.add_css_class("dim-label")
            count_lbl.add_css_class("caption")
            expander.add_suffix(count_lbl)
            self._expanders[block.key] = expander

            switch = Adw.SwitchRow(
                title="Incluir na instalação",
                subtitle="Marque para configurar este bloco",
            )
            switch.set_active(False)
            self._switch_rows[block.key] = switch
            expander.add_row(switch)

            for pkg in block.repo_packages:
                expander.add_row(Adw.ActionRow(title=pkg, subtitle="repo"))
            for pkg in block.aur_packages:
                expander.add_row(Adw.ActionRow(title=pkg, subtitle="AUR"))
            for svc in block.services:
                expander.add_row(Adw.ActionRow(title=svc, subtitle="serviço systemd"))

            blocks_group.add(expander)
        self.add(blocks_group)

        action_group = Adw.PreferencesGroup()
        install_row = Adw.ActionRow(
            title="Instalar e configurar serviços selecionados",
            subtitle="Uma autenticação pkexec para todo o lote",
        )
        self._install_btn = Gtk.Button(label="Instalar")
        self._install_btn.add_css_class("suggested-action")
        self._install_btn.set_valign(Gtk.Align.CENTER)
        self._install_btn.connect("clicked", self._on_install)
        install_row.add_suffix(self._install_btn)
        action_group.add(install_row)
        self.add(action_group)

        notes = Adw.PreferencesGroup(
            title="Após a instalação",
            description=(
                "Faça logout/login para aplicar os grupos libvirt e sambashares. "
                "Na VM, instale spice-vdagent. Para adicionar impressoras, use "
                "system-config-printer ou http://localhost:631."
            ),
        )
        self.add(notes)

    # ─────────────────────────── State helpers ──────────────────────────────

    def _refresh_state(self) -> bool:
        _installed_packages.cache_clear()
        for key, row in self._switch_rows.items():
            block = self._blocks[key]
            configured = detect_block_state(block)
            row.set_active(False)
            status = "✓ Já configurado" if configured else "Pronto para instalar"
            self._expanders[key].set_subtitle(
                escape_label(f"{status}  •  {block.description}")
            )
            row.set_subtitle(
                escape_label(
                    "Já configurado — marque para reconfigurar"
                    if configured
                    else "Marque para incluir na instalação"
                )
            )
        return GLib.SOURCE_REMOVE

    def build_plan(self) -> ExecutionPlan | None:
        """Build the execution plan for the selected service blocks."""
        selected = [
            self._blocks[key]
            for key, row in self._switch_rows.items()
            if row.get_active()
        ]
        if not selected:
            return None

        tasks: list[PrivilegedTask] = []
        for block in selected:
            repo_pkgs = list(block.repo_packages)
            if repo_pkgs:
                tasks.append(
                    PrivilegedTask(
                        "pacman_install",
                        f"Instalar pacotes: {block.title}",
                        {"packages": repo_pkgs},
                    )
                )
            tasks.append(
                PrivilegedTask(
                    BLOCK_ACTIONS[block.key],
                    f"Configurar {block.title}",
                )
            )

        stages: list[object] = [
            PrivilegedBatch(title="Serviços via pkexec", tasks=tasks)
        ]

        aur_pkgs: list[str] = []
        for block in selected:
            for pkg in block.aur_packages:
                if pkg not in aur_pkgs:
                    aur_pkgs.append(pkg)
        if aur_pkgs:
            def _aur_stage(logger: TaskLogger, _pkgs: list[str] = aur_pkgs) -> None:
                helper = aur_mod.detect_aur_helper()
                if not helper:
                    logger.warn(
                        "Helper AUR não detectado. Instale paru/yay na página "
                        "Pós-formatação para instalar: " + ", ".join(_pkgs)
                    )
                    return
                helper_result = aur_mod.aur_install(_pkgs, helper=helper, logger=logger)
                if helper_result != 0:
                    raise RuntimeError(f"Falha ao instalar pacotes AUR: {', '.join(_pkgs)}")

            stages.append(
                UserStep(title=f"Pacotes AUR ({', '.join(aur_pkgs)})", fn=_aur_stage)
            )

        return ExecutionPlan(title="Instalar e configurar serviços", stages=stages)

    # ────────────────────────────── Actions ─────────────────────────────────

    def _on_install(self, _button: Gtk.Button) -> None:
        plan = self.build_plan()
        if plan is None:
            alert = Adw.AlertDialog.new(
                "Nada selecionado", "Habilite ao menos um bloco de serviços."
            )
            alert.add_response("ok", "OK")
            alert.present(self.get_root())
            return

        dialog = ExecutionDialog(plan)
        dialog.start(self.get_root(), on_complete=lambda _ok: self._refresh_state())
