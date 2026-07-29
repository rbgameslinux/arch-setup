#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$EUID" -eq 0 ]; then
    echo "[ERRO] Não execute como root. Use sudo." >&2
    exit 1
fi

if ! command -v dialog &> /dev/null; then
    echo "[INFO] dialog não encontrado. Instalando..."
    sudo pacman -S --noconfirm dialog
fi

run_script() {
    local script="$1"
    local name="$2"
    if [ ! -f "$script" ]; then
        dialog --title "Erro" --msgbox "Script não encontrado:\n$script" 6 50
        return
    fi
    dialog --title "Confirmar" --yesno "Executar ${name}?" 6 50
    [ $? -ne 0 ] && return
    clear
    if bash "$script"; then
        dialog --title "Sucesso" --msgbox "${name} concluído com sucesso!" 6 40
    else
        dialog --title "Erro" --msgbox "${name} falhou.\nVerifique o log para detalhes." 7 50
    fi
}

while true; do
    choice=$(dialog --title "Scripts Arch Linux" \
        --ok-label "Selecionar" \
        --cancel-label "Sair" \
        --menu "Escolha um script para executar:" 16 65 5 \
        "1" "Pós-formatação (drivers, pacotes, AUR)" \
        "2" "Configurar Sistema (env, sysctl, GRUB)" \
        "3" "Virt-Manager + Samba + CUPS" \
        "4" "Fix Microfone ZapZap" \
        3>&1 1>&2 2>&3)

    clear
    case $choice in
        1) run_script "$DIR/scripts/pos-formatacao.sh" "Pós-Formatação" ;;
        2) run_script "$DIR/scripts/config-system.sh" "Configurar Sistema" ;;
        3) run_script "$DIR/scripts/install-virt-manager.sh" "Virt-Manager" ;;
        4) run_script "$DIR/scripts/fix-microfone-zapzap.sh" "Fix Microfone ZapZap" ;;
        *) exit 0 ;;
    esac
done
