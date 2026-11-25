#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$EUID" -eq 0 ]; then
    echo "[ERRO] Não execute como root. O app solicitará permissão via pkexec quando necessário." >&2
    exit 1
fi

check_deps() {
    command -v python3 >/dev/null 2>&1 || return 1
    command -v pkexec >/dev/null 2>&1 || return 1
    python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw" >/dev/null 2>&1 || return 1
}

if ! check_deps; then
    echo "[INFO] Instalando dependências da interface gráfica (python-gobject, gtk4, libadwaita, polkit)..."
    sudo pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita polkit
fi

export PYTHONPATH="${DIR}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m arch_setup "$@"
