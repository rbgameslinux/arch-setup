#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

LOG_FILE="/tmp/launcher-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

if [ "$EUID" -eq 0 ]; then
    error "Não execute como root. Use sudo."
fi

DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v dialog &> /dev/null; then
    info "dialog não encontrado. Instalando..."
    sudo pacman -S --noconfirm dialog
fi

run_script() {
    local script="$1"
    local name="$2"
    dialog --title "Confirmar" --yesno "Executar ${name}?" 6 50
    if [ $? -eq 0 ]; then
        clear
        bash "$script"
        echo
        read -p "Pressione Enter para voltar ao menu..."
    fi
}

while true; do
    choice=$(dialog --clear --title "Scripts Arch Linux" \
        --menu "Escolha um script para executar:" 16 65 6 \
        "1" "Pós-formatação (drivers, pacotes, AUR)" \
        "2" "Configurar Sistema (env, sysctl, GRUB)" \
        "3" "Virt-Manager + Samba + CUPS" \
        "4" "Fix Microfone ZapZap" \
        "5" "Sair" \
        3>&1 1>&2 2>&3)

    clear
    case $choice in
        1) run_script "$DIR/scripts/pos-formatacao.sh" "Pós-Formatação" ;;
        2) run_script "$DIR/scripts/config-system.sh" "Configurar Sistema" ;;
        3) run_script "$DIR/scripts/install-virt-manager.sh" "Virt-Manager" ;;
        4) run_script "$DIR/scripts/fix-microfone-zapzap.sh" "Fix Microfone ZapZap" ;;
        5) info "Saindo..." ; exit 0 ;;
        *) break ;;
    esac
done
