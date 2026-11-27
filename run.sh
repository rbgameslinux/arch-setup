#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$EUID" -eq 0 ]; then
    echo "[ERRO] Não execute como root. O app solicitará permissão via pkexec quando necessário." >&2
    exit 1
fi

PACKAGES=(python python-gobject gtk4 libadwaita polkit)
MANUAL_CMD="sudo pacman -S --needed python python-gobject gtk4 libadwaita polkit"

check_deps() {
    command -v python3 >/dev/null 2>&1 || return 1
    command -v pkexec >/dev/null 2>&1 || return 1
    python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw" >/dev/null 2>&1 || return 1
}

install_deps() {
    echo "[INFO] Instalando dependências da interface gráfica: ${PACKAGES[*]}"

    if command -v pkexec >/dev/null 2>&1; then
        echo "[INFO] Solicitando senha na janela do polkit..."
        if pkexec pacman -S --needed --noconfirm "${PACKAGES[@]}"; then
            return 0
        fi
        echo "[ERRO] Instalação via polkit falhou ou foi cancelada." >&2
        echo "[DICA] Para instalar manualmente, rode: $MANUAL_CMD" >&2
        return 1
    fi

    if [ -t 0 ] && command -v sudo >/dev/null 2>&1; then
        echo "[INFO] pkexec indisponível; usando sudo no terminal..."
        sudo pacman -S --needed --noconfirm "${PACKAGES[@]}"
        return 0
    fi

    echo "[ERRO] Sem pkexec e sem terminal com sudo para instalar dependências." >&2
    echo "[DICA] Abra um terminal e rode: $MANUAL_CMD" >&2
    return 1
}

if ! check_deps; then
    install_deps
    if ! check_deps; then
        echo "[ERRO] Ainda faltam dependências após a instalação." >&2
        echo "[DICA] Rode manualmente: $MANUAL_CMD" >&2
        exit 1
    fi
fi

export PYTHONPATH="${DIR}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m arch_setup "$@"
