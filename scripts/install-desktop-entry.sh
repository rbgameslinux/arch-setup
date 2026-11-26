#!/bin/bash
# Instala o atalho gráfico do Arch Setup (sem terminal) em ~/.local/share/applications.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$DIR/run.sh"
DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/io.github.rbgameslinux.ArchSetup.desktop"

if [ ! -f "$RUNNER" ]; then
    echo "[ERRO] Não encontrei $RUNNER" >&2
    exit 1
fi

chmod +x "$RUNNER"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Arch Setup
GenericName=Configuração pós-formatação do Arch Linux
Comment=Interface gráfica para pacotes, sistema, serviços e correções
Exec="$RUNNER"
Path="$DIR"
Icon=system-software-install-symbolic
Terminal=false
Categories=System;Utility;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "[INFO] Atalho instalado: $DESKTOP_FILE"
echo "[INFO] O app será iniciado sem terminal; a autenticação usa pkexec/askpass gráfico."
