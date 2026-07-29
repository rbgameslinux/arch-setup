#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

LOG_FILE="/tmp/pos-formatacao-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

if [ "$EUID" -eq 0 ]; then
    error "Não execute como root. Use sudo."
fi

ask_continue() {
    echo
    warn "$1"
    echo -n "Deseja continuar mesmo assim? (s/N): "
    read -r resp
    [ "$resp" != "s" ] && exit 1
}

safe() {
    "$@" || ask_continue "Falhou: $*"
}

info "============================================"
info " Script de pós-formatação - Arch Linux"
info " Destinado para quem usa GPU AMD"
info "============================================"
echo

# Detecta número de núcleos da CPU
CORES=$(nproc)
info "CPU detectada com $CORES núcleos."

# Detecta se já existe um AUR helper instalado
AUR_HELPER=""
for helper in paru yay paru-bin yay-bin; do
    if command -v "$helper" &> /dev/null; then
        AUR_HELPER="$helper"
        info "AUR helper detectado: $AUR_HELPER"
        break
    fi
done

if [ -z "$AUR_HELPER" ]; then
    info "Qual AUR helper você deseja instalar?"
    echo "1) paru"
    echo "2) yay"
    read -p "Escolha (1 ou 2): " AUR_CHOICE

    info "Instalando dependências base..."
    safe sudo pacman -S --needed --noconfirm base-devel git

    if [ "$AUR_CHOICE" == "1" ] || [ "$AUR_CHOICE" != "2" ]; then
        info "Instalando paru..."
        safe git clone https://aur.archlinux.org/paru.git /tmp/paru
        (cd /tmp/paru && safe makepkg -si --noconfirm)
        AUR_HELPER="paru"
    else
        info "Instalando yay..."
        safe git clone https://aur.archlinux.org/yay.git /tmp/yay
        (cd /tmp/yay && safe makepkg -si --noconfirm)
        AUR_HELPER="yay"
    fi
else
    info "Usando $AUR_HELPER já instalado."
fi

# Instala dependências base (se não instalou na etapa anterior)
info "Instalando dependências base..."
safe sudo pacman -S --needed --noconfirm base-devel git

# Configura MAKEFLAGS no /etc/makepkg.conf
info "Configurando MAKEFLAGS para $CORES threads..."
safe sudo sed -i "s/^#MAKEFLAGS=\"-j[0-9]*\"/MAKEFLAGS=\"-j$CORES\"/" /etc/makepkg.conf
safe sudo sed -i "s/^MAKEFLAGS=\"-j[0-9]*\"/MAKEFLAGS=\"-j$CORES\"/" /etc/makepkg.conf
if ! grep -q "^MAKEFLAGS" /etc/makepkg.conf; then
    echo "MAKEFLAGS=\"-j$CORES\"" | safe sudo tee -a /etc/makepkg.conf > /dev/null
fi
info "MAKEFLAGS definido para -j$CORES."

# Instala pacotes base
info "Instalando pacotes base..."
safe sudo pacman -S --needed --noconfirm \
    wine \
    wine-gecko \
    wine-mono \
    winetricks \
    ntfs-3g \
    git \
    wget \
    curl \
    vulkan-radeon \
    libva-mesa-driver \
    vulkan-icd-loader \
    lib32-mesa \
    lib32-vulkan-radeon \
    lib32-vulkan-icd-loader \
    lib32-libva-mesa-driver \
    mesa-demos \
    xorg-xdpyinfo \
    amd-ucode \
    mesa-utils \
    glfw-wayland \
    eog \
    unrar \
    zip \
    unzip

# Instala electron29-bin automaticamente como dependência
info "Instalando electron29-bin como dependência..."
safe $AUR_HELPER -S --needed --noconfirm electron29-bin

# Lista de pacotes para seleção
PACOTES=(
    "celluloid"          "Reprodutor de vídeo GTK4 (frontend MPV)" "repo"
    "mpv"                "Reprodutor de vídeo via terminal" "repo"
    "vlc"                "Reprodutor de vídeo versátil" "repo"
    "opencl-amd"         "Suporte OpenCL para GPU AMD" "aur"
    "android-tools"      "Ferramentas ADB e Fastboot" "repo"
    "deckboard-bin"      "Controle remoto para PC via celular" "aur"
    "r-linux"            "Linguagem R para análise estatística" "aur"
    "lutris"             "Gerenciador de jogos (Wine/Nativo)" "repo"
    "heroic-games-launcher-bin" "Launcher para Epic/GOG/Amazon" "aur"
    "visual-studio-code-bin" "Editor de código Microsoft" "aur"
    "protonup-qt"        "Gerenciador de Proton GE" "aur"
    "ventoy"             "Criar USB bootável múltipla" "repo"
    "obs-studio-tytan652" "OBS Studio com plugins extras" "aur"
    "obs-vkcapture"      "Captura de tela Vulkan para OBS" "aur"
    "winff"              "Conversor de vídeo com GUI" "repo"
    "gimp"               "Editor de imagens avançado" "repo"
    "droidcam"           "Usar celular como webcam" "aur"
    "v4l2loopback-dc-dkms" "Módulo kernel para Droidcam" "aur"
    "antimicrox"         "Mapear teclado para controle" "aur"
    "google-chrome"      "Navegador Google Chrome" "aur"
    "steam"              "Plataforma de jogos digitais" "repo"
    "ark"                "Gerenciador de arquivos (KDE)" "repo"
    "gedit"              "Editor de texto GNOME" "repo"
    "gparted"            "Gerenciador de partições" "repo"
    "mangohud"           "Overlay de desempenho" "repo"
    "radeontop"          "Monitor de GPU AMD" "repo"
    "bash-completion"    "Auto-completar avançado" "repo"
    "telegram-desktop"   "Mensageiro Telegram" "repo"
    "discord"            "Mensageiro para gamers" "repo"
    "firefox"            "Navegador Mozilla Firefox" "repo"
    "lact"               "Controle de GPU AMD" "aur"
    "qbittorrent"        "Cliente torrent" "repo"
    "zapzap"             "WhatsApp desktop nativo" "aur"
    "filelight"          "Analisador de espaço em disco" "repo"
    "protontricks"       "Winetricks simplificado para Proton" "aur"
)

echo
info "============================================"
info " Seleção de Pacotes Adicionais"
info "============================================"
echo "Digite os números separados por espaço/vírgula (ex: 1 3 5)"
echo "'t' para selecionar todos | 'n' para pular"
echo

PACKAGE_LIST=$(
    for i in "${!PACOTES[@]}"; do
        if (( i % 3 == 0 )); then
            idx=$(( i / 3 + 1 ))
            printf "[%2d] %-28s (%s)\n" "$idx" "${PACOTES[i]}" "${PACOTES[i+2]}"
        fi
    done
)
echo "$PACKAGE_LIST" | pr -2 -t -w ${COLUMNS:-80}

echo
read -p "Escolha: " ESCOLHA

SELEGIONADOS=()
if [ "$ESCOLHA" == "t" ]; then
    for i in "${!PACOTES[@]}"; do
        (( i % 3 == 0 )) && SELEGIONADOS+=("${PACOTES[i]}")
    done
elif [ "$ESCOLHA" != "n" ]; then
    ESCOLHA=$(echo "$ESCOLHA" | tr ',' ' ' | tr -s ' ')
    for num in $ESCOLHA; do
        idx=$(( (num - 1) * 3 ))
        if [ $idx -ge 0 ] && [ $idx -lt ${#PACOTES[@]} ]; then
            SELEGIONADOS+=("${PACOTES[idx]}")
        fi
    done
fi

if [ ${#SELEGIONADOS[@]} -gt 0 ]; then
    REPO=()
    AUR=()
    for pkg in "${SELEGIONADOS[@]}"; do
        for i in "${!PACOTES[@]}"; do
            if (( i % 3 == 0 )) && [ "${PACOTES[i]}" == "$pkg" ]; then
                [ "${PACOTES[i+2]}" == "repo" ] && REPO+=("$pkg") || AUR+=("$pkg")
                break
            fi
        done
    done

    [ ${#REPO[@]} -gt 0 ] && safe sudo pacman -S --needed --noconfirm "${REPO[@]}"
    [ ${#AUR[@]} -gt 0 ] && safe $AUR_HELPER -S --needed --noconfirm "${AUR[@]}"
else
    info "Nenhum pacote adicional selecionado."
fi

echo
info "============================================"
info " Instalação concluída!"
info "============================================"
