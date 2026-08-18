#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

if [ "$EUID" -eq 0 ]; then
    error "Não execute como root. Use sudo."
fi

if ! command -v dialog &> /dev/null; then
    echo "[INFO] dialog não encontrado. Instalando..."
    sudo pacman -S --noconfirm dialog
fi

install_wallpapers() {
    local DEST="$HOME/Wallpapers"
    local TMP_FILE="/tmp/rbgames-wallpapers.tar.gz"
    local TMP_DIR="/tmp/rbgames-wallpapers-extract"
    local URL="https://drive.usercontent.google.com/download?id=1siQhnSD-MO8gEXxusMocu_feXn60SzXw&export=download&confirm=t"

    info "Baixando wallpapers (~1.2G)... Isso pode demorar."
    if ! curl -L --fail --retry 3 --no-progress-meter "$URL" -o "$TMP_FILE"; then
        warn "Falha no download. Pode ser limite de cota do Google Drive."
        return 1
    fi

    if ! gzip -t "$TMP_FILE"; then
        warn "Arquivo baixado está corrompido (ou o Drive retornou um aviso em vez do arquivo)."
        rm -f "$TMP_FILE"
        return 1
    fi

    rm -rf "$TMP_DIR"
    mkdir -p "$TMP_DIR"
    info "Extraindo wallpapers..."
    tar -xzf "$TMP_FILE" -C "$TMP_DIR"

    if [ -d "$TMP_DIR/Rbgames-Wallpapers" ]; then
        if [ -d "$DEST" ]; then
            cp -r "$TMP_DIR/Rbgames-Wallpapers/." "$DEST/"
        else
            mv "$TMP_DIR/Rbgames-Wallpapers" "$DEST"
        fi
        info "Wallpapers instalados em $DEST"
    else
        warn "Estrutura do arquivo inesperada; nada foi instalado."
    fi

    rm -f "$TMP_FILE"
    rm -rf "$TMP_DIR"
}

clear
if install_wallpapers; then
    dialog --title "Sucesso" --msgbox "Wallpapers instalados com sucesso em ~/Wallpapers!" 6 50
else
    dialog --title "Erro" --msgbox "Falha ao instalar wallpapers.\nVerifique o terminal para detalhes." 7 50
fi
