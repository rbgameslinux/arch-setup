#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

LOG_FILE="/tmp/pos-formatacao-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

info "Fix: Impedir ZapZap de abaixar o volume do microfone"

CONFIG_DIR="${HOME}/.config/pipewire/pipewire-pulse.conf.d"
CONFIG_FILE="${CONFIG_DIR}/99-block-source-volume.conf"
BACKUP_DIR="${HOME}/backup-config"

info "Criando diretório de configuração..."
mkdir -p "${CONFIG_DIR}"

info "Criando regra block-source-volume para QtWebEngineProcess..."
cat > "${CONFIG_FILE}" << 'EOF'
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
EOF

info "Salvando backup..."
mkdir -p "${BACKUP_DIR}"
cp "${CONFIG_FILE}" "${BACKUP_DIR}/99-block-source-volume.conf"

info "Reiniciando PipeWire PulseAudio..."
systemctl --user restart pipewire-pulse 2>/dev/null || pulseaudio -k 2>/dev/null || true

echo
info "Pronto! O volume do microfone não será mais alterado pelo ZapZap."
echo
echo "Para reverter:"
echo "  rm ${CONFIG_FILE} && systemctl --user restart pipewire-pulse"
echo
echo "Para testar a regra em tempo real (se o problema persistir):"
echo "  pactl subscribe | grep --line-buffered -i volume"
