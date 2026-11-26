"""User-space backend for system fixes: ZapZap mic and DaVinci Resolve."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from arch_setup.backend.runner import TaskLogger

# ─────────────────── ZapZap PipeWire mic fix ────────────────────────────────

PIPEWIRE_CONF_DIR = Path.home() / ".config" / "pipewire" / "pipewire-pulse.conf.d"
PIPEWIRE_CONF_FILE = PIPEWIRE_CONF_DIR / "99-block-source-volume.conf"

PIPEWIRE_RULE = """\
pulse.rules = [
    {
        matches = [
            { application.process.binary = "QtWebEngineProcess" }
        ]
        actions = {
            quirks = [ block-source-volume ]
        }
    }
]
"""


def zapzap_fix_is_applied() -> bool:
    return PIPEWIRE_CONF_FILE.is_file()


def apply_zapzap_fix(logger: TaskLogger) -> bool:
    """Create PipeWire rule that prevents ZapZap from lowering mic volume."""
    logger.info("Aplicando fix do microfone do ZapZap (PipeWire)...")
    try:
        PIPEWIRE_CONF_DIR.mkdir(parents=True, exist_ok=True)
        PIPEWIRE_CONF_FILE.write_text(PIPEWIRE_RULE, encoding="utf-8")
        logger.info(f"Regra criada: {PIPEWIRE_CONF_FILE}")

        # Backup
        backup = Path.home() / "backup-config" / "99-block-source-volume.conf"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PIPEWIRE_CONF_FILE, backup)
        logger.info(f"Backup salvo em: {backup}")

        # Restart user PipeWire (fallback para PulseAudio, como no script original)
        rc = subprocess.run(
            ["systemctl", "--user", "restart", "pipewire-pulse"],
            capture_output=True, check=False, timeout=10,
        ).returncode
        if rc != 0:
            rc = subprocess.run(
                ["pulseaudio", "-k"],
                capture_output=True, check=False, timeout=10,
            ).returncode
        if rc != 0:
            logger.warn(
                "Não foi possível reiniciar pipewire-pulse nem matar o PulseAudio; "
                "reinicie a sessão para aplicar a regra."
            )
        else:
            logger.info("pipewire-pulse reiniciado com sucesso.")

        return True
    except Exception as exc:
        logger.error(f"Falha ao aplicar fix ZapZap: {exc}")
        return False


def revert_zapzap_fix(logger: TaskLogger) -> bool:
    """Remove PipeWire rule."""
    if not PIPEWIRE_CONF_FILE.exists():
        logger.warn("Regra PipeWire não encontrada — nada a remover.")
        return True
    try:
        PIPEWIRE_CONF_FILE.unlink()
        rc = subprocess.run(
            ["systemctl", "--user", "restart", "pipewire-pulse"],
            capture_output=True, check=False, timeout=10,
        ).returncode
        if rc != 0:
            subprocess.run(
                ["pulseaudio", "-k"],
                capture_output=True, check=False, timeout=10,
            )
        logger.info("Fix ZapZap removido e pipewire-pulse reiniciado.")
        return True
    except Exception as exc:
        logger.error(f"Falha ao reverter fix ZapZap: {exc}")
        return False


# ─────────────────── DaVinci Resolve fix ────────────────────────────────────

RESOLVE_BIN = Path("/opt/resolve/bin/resolve")
WRAPPER_PATH = Path.home() / ".local" / "bin" / "resolve"
DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"
DESKTOP_FILE = DESKTOP_DIR / "com.blackmagicdesign.resolve.desktop"
NIRI_CONFIG = Path.home() / ".config" / "niri" / "config.kdl"
ASKPASS_SCRIPT = Path(__file__).resolve().parent.parent / "ui" / "askpass.py"

# A isca de foco do wrapper precisa de kitty (nativo Wayland) ou, em fallback,
# xterm (X11). Detectados no PATH para a página de correções avisar o usuário.
KITTY_PATH = shutil.which("kitty")
XTERM_PATH = shutil.which("xterm")


WRAPPER_TEMPLATE = """\
#!/bin/sh
ulimit -c 0
unset QT_QPA_PLATFORM
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=xim
export QT_QPA_PLATFORMTHEME=default
export QT_QPA_PLATFORM_PLUGIN_PATH=/opt/resolve/libs/plugins/platforms

LOG="$HOME/.local/state/resolve-watchdog.log"
mkdir -p "$HOME/.local/state"

if ! niri msg version >/dev/null 2>&1; then
    exec /opt/resolve/bin/resolve "$@"
fi

log() { echo "[$(date "+%F %T")] $*" >> "$LOG"; }

resolve_main_window_id() {
    niri msg windows 2>/dev/null | awk '
        /^Window ID/ { id = $3; sub(/:/, "", id); title = "" }
        /^  Title:/ { title = $0 }
        /^  App ID: "resolve"/ && title != "" && !found &&
            title !~ /: "resolve"$/ &&
            title !~ /Relatório de Problemas/ &&
            title !~ /Problem Report/ { print id; found = 1 }
        END { exit found ? 0 : 1 }
    '
}

clean_stale_lock() {
    for lock in /tmp/qtsingleapp-DaVinc-*lockfile*; do
        [ -e "$lock" ] || continue
        pid=$(tr -cd '0-9' < "$lock")
        if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$lock"
            log "lock stale do Qt removido: $lock (pid=${pid:-desconhecido})"
        fi
    done
}

focused_workspace() {
    niri msg workspaces 2>/dev/null | awk '/^[ \\t]*\\*/ { print $2; exit }'
}

workspace_has_window() {
    niri msg windows 2>/dev/null | awk -v ws="$1" '
        $1 == "Workspace" && $2 == "ID:" && $3 == ws { found = 1 }
        END { exit found ? 0 : 1 }'
}

DECOY_PID=""
DECOY_ID=""
DECOY_MARK="resolve-isca-$$"

decoy_open() {
    if [ -n "$DECOY_PID" ] && kill -0 "$DECOY_PID" 2>/dev/null; then
        return 0
    fi
    if command -v kitty >/dev/null 2>&1; then
        kitty --title="$DECOY_MARK" --class=Resolve-isca \\
            /bin/bash -c 'sleep 300' >/dev/null 2>&1 &
    elif command -v xterm >/dev/null 2>&1; then
        xterm -geometry 60x3+0+0 -T "$DECOY_MARK" -e sh -c 'sleep 300' >/dev/null 2>&1 &
    else
        log "isca nao aberta: nem kitty nem xterm disponiveis"
        return 1
    fi
    sleep 1
    DECOY_ID=$(niri msg windows 2>/dev/null | awk -v m="$DECOY_MARK" '
        /^Window ID/ { id = $3; sub(/:/, "", id); title = "" }
        /^  Title:/ { title = $0 }
        title != "" && title ~ m && !found { print id; found = 1 }
        END { exit found ? 0 : 1 }
    ')
    REAL=$(pgrep -f "$DECOY_MARK" 2>/dev/null | head -1)
    [ -n "$REAL" ] && DECOY_PID="$REAL" || DECOY_PID=$!
    log "janela isca de foco aberta (pid $DECOY_PID, id ${DECOY_ID:-desconhecido})"
}

decoy_close() {
    if [ -n "$DECOY_ID" ]; then
        niri msg action close-window "$DECOY_ID" 2>/dev/null
    fi
    if [ -n "$DECOY_PID" ] && kill -0 "$DECOY_PID" 2>/dev/null; then
        kill "$DECOY_PID" 2>/dev/null
    fi
    pkill -f "$DECOY_MARK" 2>/dev/null
    pkill -f 'xterm .*-e sh -c sleep 300' 2>/dev/null
    DECOY_PID=""
    DECOY_ID=""
    log "janela isca de foco fechada"
}

WS=$(focused_workspace)
if [ -n "$WS" ]; then
    if ! workspace_has_window "$WS"; then decoy_open; fi
else
    decoy_open
fi

attempt=0
while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
    clean_stale_lock
    /opt/resolve/bin/resolve "$@" &
    RPID=$!
    XWS=$(pgrep -cf '^xwayland-satellite' 2>/dev/null || echo 0)
    log "tentativa $attempt iniciada (PID $RPID, xwayland-satellite=${XWS:-0})"

    elapsed=0
    found=0
    while [ "$elapsed" -lt 45 ]; do
        if MAINWID=$(resolve_main_window_id); then
            found=1; break
        fi
        if ! kill -0 "$RPID" 2>/dev/null; then
            wait "$RPID"; code=$?
            log "resolve saiu antes de abrir janela (codigo $code)"
            break
        fi
        sleep 1; elapsed=$((elapsed + 1))
    done

    if [ "$found" -eq 1 ]; then
        log "janela principal detectada no niri (PID $RPID, ID ${MAINWID:-desconhecido})"
        if [ -n "$MAINWID" ]; then
            niri msg action focus-window "$MAINWID" 2>/dev/null
            log "foco forcado na janela principal (ID $MAINWID)"
            sleep 1
        fi
        decoy_close
        start=$(date +%s)
        wait "$RPID"; code=$?
        elapsed_run=$(($(date +%s) - start))
        log "resolve encerrou (codigo $code, ficou aberto ${elapsed_run}s)"
        if [ "$elapsed_run" -lt 30 ]; then
            log "AVISO: resolve fechou em menos de 30s; possivel crash/fechamento precoce"
        fi
        exit $code
    fi

    if kill -0 "$RPID" 2>/dev/null; then
        log "sem janela em ~45s; matando PID $RPID"
        kill "$RPID" 2>/dev/null; sleep 3
        kill -9 "$RPID" 2>/dev/null
        wait "$RPID" 2>/dev/null
        pkill -f 'resolve -report[C]rash' 2>/dev/null
    fi

    if [ -n "$WS" ]; then
        if ! workspace_has_window "$WS"; then decoy_open; fi
    else
        decoy_open
    fi
done

decoy_close
log "resolve falhou apos 3 tentativas; desistindo"
exit 1
"""

NIRI_WINDOW_RULES_TEMPLATE = """\

// DaVinci Resolve — a janela principal e a janela secundária precisam abrir
// flutuando em (0,0) do {output}, senão o Resolve não renderiza corretamente.
window-rule {{
    match app-id="resolve"
    open-floating true
    open-on-output "{output}"
    default-floating-position x=0 y=0 relative-to="top-left"
}}
window-rule {{
    match app-id="resolve" title="^resolve$"
    open-focused false
}}
"""

DESKTOP_ENTRY_TEMPLATE = """\
[Desktop Entry]
Version=1.0
Type=Application
Name=DaVinci Resolve
GenericName=DaVinci Resolve
Comment=Revolutionary new tools for editing, visual effects, color correction and professional audio post production, all in a single application!
Path=/opt/resolve/
Exec={wrapper} %u
Terminal=false
MimeType=application/x-resolveproj;
Icon=/opt/resolve/graphics/DV_Resolve.png
StartupNotify=true
Name[en_US]=DaVinci Resolve
"""


def resolve_fix_is_applied() -> bool:
    return WRAPPER_PATH.is_file()


def get_niri_outputs() -> list[str]:
    """Return list of output names from `niri msg outputs`."""
    try:
        proc = subprocess.run(
            ["niri", "msg", "outputs"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        outputs: list[str] = []
        for line in proc.stdout.splitlines():
            # Lines like: "Output "DP-1" (connected, ...)"
            m = re.match(r'Output\s+"([^"]+)"', line.strip())
            if m:
                outputs.append(m.group(1))
        return outputs if outputs else ["DP-1"]
    except Exception:
        return ["DP-1"]


def apply_resolve_fix(output: str, logger: TaskLogger) -> bool:
    """Create wrapper, .desktop and niri window rules for DaVinci Resolve."""
    if not RESOLVE_BIN.is_file() or not os.access(RESOLVE_BIN, os.X_OK):
        logger.error("DaVinci Resolve não encontrado/executável em /opt/resolve. Instale antes de rodar este fix.")
        return False

    logger.info(f"Aplicando fix DaVinci Resolve (output: {output})...")

    # 1. Wrapper
    try:
        WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = WRAPPER_PATH.with_suffix(".tmp")
        tmp.write_text(WRAPPER_TEMPLATE, encoding="utf-8")

        if WRAPPER_PATH.exists() and WRAPPER_PATH.read_text() == WRAPPER_TEMPLATE:
            logger.warn("Wrapper já existente e correto — pulando.")
            tmp.unlink(missing_ok=True)
        else:
            tmp.rename(WRAPPER_PATH)
            WRAPPER_PATH.chmod(0o755)
            logger.info(f"Wrapper criado/atualizado: {WRAPPER_PATH}")
    except Exception as exc:
        logger.error(f"Falha ao criar wrapper: {exc}")
        return False

    # 2. .desktop
    try:
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        entry = DESKTOP_ENTRY_TEMPLATE.format(wrapper=WRAPPER_PATH)
        if DESKTOP_FILE.exists():
            existing = DESKTOP_FILE.read_text(encoding="utf-8")
            if str(WRAPPER_PATH) in existing:
                logger.warn(".desktop já aponta para o wrapper — pulando.")
            else:
                updated = re.sub(
                    r"^Exec=.*$", f"Exec={WRAPPER_PATH} %u", existing, flags=re.MULTILINE
                )
                DESKTOP_FILE.write_text(updated, encoding="utf-8")
                logger.info(".desktop atualizado para usar o wrapper")
        else:
            DESKTOP_FILE.write_text(entry, encoding="utf-8")
            logger.info(f".desktop criado: {DESKTOP_FILE}")

        subprocess.run(
            ["update-desktop-database", str(DESKTOP_DIR)],
            capture_output=True, check=False, timeout=10,
        )
    except Exception as exc:
        logger.error(f"Falha ao configurar .desktop: {exc}")
        return False

    # 3. niri window rules
    try:
        if NIRI_CONFIG.exists():
            niri_text = NIRI_CONFIG.read_text(encoding="utf-8")
            if 'app-id="resolve"' in niri_text:
                # Permite trocar o monitor pela GUI mesmo após o fix aplicado.
                offset = niri_text.index('app-id="resolve"')
                match = re.search(
                    r'open-on-output\s+"([^"]+)"', niri_text[offset:]
                )
                if match and match.group(1) == output:
                    logger.warn("Regras do Resolve já apontam para este monitor — pulando.")
                elif match:
                    start = offset + match.start()
                    end = offset + match.end()
                    updated = (
                        niri_text[:start]
                        + f'open-on-output "{output}"'
                        + niri_text[end:]
                    )
                    NIRI_CONFIG.write_text(updated, encoding="utf-8")
                    logger.info(f"Regras do niri atualizadas para o monitor {output}")
                else:
                    logger.warn(
                        "Regras do Resolve existem, mas sem 'open-on-output'. "
                        "Ajuste manualmente o config do niri."
                    )
            else:
                rules = NIRI_WINDOW_RULES_TEMPLATE.format(output=output)
                NIRI_CONFIG.write_text(niri_text + rules, encoding="utf-8")
                logger.info(f"Regras do niri adicionadas (output: {output})")
        else:
            logger.warn(
                f"Config do niri não encontrado em {NIRI_CONFIG}. "
                "Adicione as regras manualmente se usar niri."
            )
    except Exception as exc:
        logger.warn(f"Não foi possível atualizar config do niri: {exc}")

    logger.info("Fix DaVinci Resolve aplicado com sucesso.")
    return True


def revert_resolve_fix(logger: TaskLogger) -> bool:
    """Remove wrapper (user removes niri rules manually)."""
    try:
        if WRAPPER_PATH.exists():
            WRAPPER_PATH.unlink()
            logger.info(f"Wrapper removido: {WRAPPER_PATH}")
        else:
            logger.warn("Wrapper não encontrado — nada a remover.")
        logger.info("Remova manualmente os blocos 'match app-id=\"resolve\"' do config do niri.")
        return True
    except Exception as exc:
        logger.error(f"Falha ao reverter fix Resolve: {exc}")
        return False
