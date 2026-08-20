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

install_heroic_appimage() {
    local BIN_DIR="$HOME/.local/bin"
    local APP_DIR="$HOME/.local/share/applications"
    local YML="/tmp/heroic-latest-linux.yml"
    local APPIMAGE=""
    local ICON_PATH=""
    local URL_BASE="https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/latest/download"

    mkdir -p "$BIN_DIR" "$APP_DIR"

    info "Obtendo a versão mais recente do Heroic..."
    if ! curl -L --fail --no-progress-meter "$URL_BASE/latest-linux.yml" -o "$YML"; then
        warn "Falha ao obter informações da versão do Heroic."
        return 1
    fi

    APPIMAGE=$(grep -m1 '^path:' "$YML" | awk '{print $2}')
    if [ -z "$APPIMAGE" ]; then
        warn "Não foi possível identificar o arquivo AppImage do Heroic."
        rm -f "$YML"
        return 1
    fi
    rm -f "$YML"

    info "Baixando $APPIMAGE (~180M)... Isso pode demorar."
    if ! curl -L --fail --retry 3 --no-progress-meter "$URL_BASE/$APPIMAGE" -o "$BIN_DIR/Heroic.AppImage"; then
        warn "Falha no download do Heroic."
        return 1
    fi

    chmod +x "$BIN_DIR/Heroic.AppImage"

    ICON_PATH=$(install_appimage_icon "$BIN_DIR/Heroic.AppImage" "heroic" || true)
    [ -z "$ICON_PATH" ] && ICON_PATH="heroic"

    cat > "$APP_DIR/heroic.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Heroic Games Launcher
GenericName=Game launcher
Comment=Launcher para Epic Games, GOG e Amazon Games
Exec=$BIN_DIR/Heroic.AppImage
Icon=$ICON_PATH
Terminal=false
Categories=Game;Utility;
StartupWMClass=heroic
EOF
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    info "Heroic instalado em $BIN_DIR/Heroic.AppImage"
}

github_latest_appimage() {
    local REPO="$1"
    local PATTERN="$2"
    curl -sL --fail --no-progress-meter \
        "https://api.github.com/repos/$REPO/releases/latest" |
        grep 'browser_download_url' |
        grep -oE 'https://[^"]+\.AppImage' |
        grep -E "$PATTERN" |
        head -n 1
}

install_appimage_icon() {
    local APPIMAGE="$1"
    local ICON_NAME="$2"
    local TMP="/tmp/appimage-icon-$$"
    local SRC=""
    local EXT=""
    local TYPE=""
    local DEST_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

    rm -rf "$TMP"
    mkdir -p "$TMP"

    if ! (cd "$TMP" && "$APPIMAGE" --appimage-extract > /dev/null 2>&1); then
        rm -rf "$TMP"
        return 1
    fi

    if [ -e "$TMP/squashfs-root/.DirIcon" ]; then
        SRC=$(readlink -f "$TMP/squashfs-root/.DirIcon")
    else
        SRC=$(find "$TMP/squashfs-root" -type f \( -iname '*.png' -o -iname '*.svg' \) 2>/dev/null \
            | grep -viE 'tray|splash|banner|header' | head -n 1)
    fi

    [ -z "$SRC" ] || [ ! -f "$SRC" ] && { rm -rf "$TMP"; return 1; }

    if command -v file &> /dev/null; then
        TYPE=$(file -b --mime-type "$SRC")
        case "$TYPE" in
            *svg*) EXT="svg" ;;
            *png*) EXT="png" ;;
            *)     EXT="png" ;;
        esac
    else
        EXT="${SRC##*.}"
        [ "$EXT" == "$SRC" ] && EXT="png"
    fi

    if [ "$EXT" == "svg" ]; then
        DEST_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
    fi

    mkdir -p "$DEST_DIR"
    cp "$SRC" "$DEST_DIR/$ICON_NAME.$EXT"
    rm -rf "$TMP"
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    echo "$DEST_DIR/$ICON_NAME.$EXT"
}

install_zapzap_appimage() {
    local BIN_DIR="$HOME/.local/bin"
    local APP_DIR="$HOME/.local/share/applications"
    local URL=""
    local APPIMAGE="ZapZap.AppImage"
    local ICON_PATH=""

    mkdir -p "$BIN_DIR" "$APP_DIR"

    info "Obtendo a versão mais recente do ZapZap..."
    URL=$(github_latest_appimage "rafatosta/zapzap" "linux-x86_64.AppImage")
    if [ -z "$URL" ]; then
        warn "Falha ao obter a URL do ZapZap."
        return 1
    fi

    info "Baixando ZapZap (~190M)... Isso pode demorar."
    if ! curl -L --fail --retry 3 --no-progress-meter "$URL" -o "$BIN_DIR/$APPIMAGE"; then
        warn "Falha no download do ZapZap."
        return 1
    fi

    chmod +x "$BIN_DIR/$APPIMAGE"

    ICON_PATH=$(install_appimage_icon "$BIN_DIR/$APPIMAGE" "zapzap" || true)
    [ -z "$ICON_PATH" ] && ICON_PATH="zapzap"

    cat > "$APP_DIR/zapzap.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ZapZap
GenericName=WhatsApp client
Comment=WhatsApp desktop nativo
Exec=$BIN_DIR/$APPIMAGE
Icon=$ICON_PATH
Terminal=false
Categories=Network;InstantMessaging;
StartupWMClass=zapzap
EOF
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    info "ZapZap instalado em $BIN_DIR/$APPIMAGE"
}

install_protonup_qt_appimage() {
    local BIN_DIR="$HOME/.local/bin"
    local APP_DIR="$HOME/.local/share/applications"
    local URL=""
    local APPIMAGE="ProtonUp-Qt.AppImage"
    local ICON_PATH=""

    mkdir -p "$BIN_DIR" "$APP_DIR"

    info "Obtendo a versão mais recente do ProtonUp-Qt..."
    URL=$(github_latest_appimage "DavidoTek/ProtonUp-Qt" "x86_64.AppImage")
    if [ -z "$URL" ]; then
        warn "Falha ao obter a URL do ProtonUp-Qt."
        return 1
    fi

    info "Baixando ProtonUp-Qt (~63M)... Isso pode demorar."
    if ! curl -L --fail --retry 3 --no-progress-meter "$URL" -o "$BIN_DIR/$APPIMAGE"; then
        warn "Falha no download do ProtonUp-Qt."
        return 1
    fi

    chmod +x "$BIN_DIR/$APPIMAGE"

    ICON_PATH=$(install_appimage_icon "$BIN_DIR/$APPIMAGE" "protonup-qt" || true)
    [ -z "$ICON_PATH" ] && ICON_PATH="protonup-qt"

    cat > "$APP_DIR/protonup-qt.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ProtonUp-Qt
GenericName=Proton manager
Comment=Gerenciador de Proton GE
Exec=$BIN_DIR/$APPIMAGE
Icon=$ICON_PATH
Terminal=false
Categories=Utility;
StartupWMClass=protonup-qt
EOF
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    info "ProtonUp-Qt instalado em $BIN_DIR/$APPIMAGE"
}

info "============================================"
info " Script de pós-formatação - Arch Linux"
info " Destinado para quem usa GPU AMD"
info "============================================"
echo

echo
warn "O suporte ao AUR (Arch User Repository) permite instalar pacotes"
warn "mantidos pela comunidade. Eles NÃO são auditados oficialmente pelo"
warn "Arch Linux e podem estar desatualizados ou comprometidos."
warn "Habilite apenas se souber o que está fazendo."
echo -n "Deseja instalar suporte ao AUR? (s/N): "
read -r AUR_ENABLED
if [ "$AUR_ENABLED" == "s" ] || [ "$AUR_ENABLED" == "S" ]; then
    AUR_ENABLED="s"
else
    AUR_ENABLED="n"
fi

# Detecta número de núcleos da CPU
CORES=$(nproc)
info "CPU detectada com $CORES núcleos."

if [ "$AUR_ENABLED" == "s" ]; then
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

        if [ "$AUR_CHOICE" == "1" ]; then
            info "Instalando paru..."
            rm -rf /tmp/paru
            safe git clone https://aur.archlinux.org/paru.git /tmp/paru
            (cd /tmp/paru && safe makepkg -si --noconfirm)
            AUR_HELPER="paru"
        else
            info "Instalando yay..."
            rm -rf /tmp/yay
            safe git clone https://aur.archlinux.org/yay.git /tmp/yay
            (cd /tmp/yay && safe makepkg -si --noconfirm)
            AUR_HELPER="yay"
        fi
    else
        info "Usando $AUR_HELPER já instalado."
    fi
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
if [ "$AUR_ENABLED" == "s" ]; then
    info "Instalando electron29-bin como dependência..."
    safe $AUR_HELPER -S --needed --noconfirm electron29-bin
fi

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
    "heroic-games-launcher" "Launcher para Epic/GOG/Amazon" "appimage"
    "protonup-qt"        "Gerenciador de Proton GE" "appimage"
    "visual-studio-code-bin" "Editor de código Microsoft" "aur"
    "ventoy"             "Criar USB bootável múltipla" "repo"
    "obs-studio"         "OBS Studio (versão oficial) + plugin de browser" "repo"
    "obs-vkcapture"      "Captura de tela Vulkan para OBS" "aur"
    "winff"              "Conversor de vídeo com GUI" "aur"
    "gimp"               "Editor de imagens avançado" "repo"
    "droidcam"           "Usar celular como webcam" "aur"
    "v4l2loopback-dc-dkms" "Módulo kernel para Droidcam" "aur"
    "antimicrox"         "Mapear teclado para controle" "aur"
    "google-chrome"      "Navegador Google Chrome" "aur"
    "github-cli"         "CLI oficial do GitHub (gh)" "repo"
    "steam"              "Plataforma de jogos digitais" "repo"
    "ark"                "Gerenciador de arquivos (KDE)" "repo"
    "gedit"              "Editor de texto GNOME" "repo"
    "gparted"            "Gerenciador de partições" "repo"
    "mangohud"           "Overlay de desempenho" "repo"
    "radeontop"          "Monitor de GPU AMD" "repo"
    "bash-completion"    "Auto-completar avançado" "repo"
    "telegram-desktop"   "Mensageiro Telegram" "repo"
    "discord"            "Mensageiro para gamers" "repo"
    "zapzap"             "WhatsApp desktop nativo" "appimage"
    "firefox"            "Navegador Mozilla Firefox" "repo"
    "qbittorrent"        "Cliente torrent" "repo"
    "filelight"          "Analisador de espaço em disco" "repo"
    "protontricks"       "Winetricks simplificado para Proton" "repo"
)

echo
info "============================================"
info " Seleção de Pacotes Adicionais"
info "============================================"
if [ "$AUR_ENABLED" == "s" ]; then
    echo "Digite os números separados por espaço/vírgula (ex: 1 3 5)"
else
    warn "Suporte ao AUR desabilitado: pacotes AUR ficam ocultos da lista."
    echo "Digite os números separados por espaço/vírgula (ex: 1 3 5)"
fi
echo "'t' para selecionar todos | 'n' para pular"
echo

VISIVEIS=()
for i in "${!PACOTES[@]}"; do
    if (( i % 3 == 0 )); then
        if [ "$AUR_ENABLED" != "s" ] && [ "${PACOTES[i+2]}" == "aur" ]; then
            continue
        fi
        VISIVEIS+=("$i")
    fi
done

PACKAGE_LIST=$(
    n=1
    for i in "${VISIVEIS[@]}"; do
        printf "[%2d] %-22s (%s)\n" "$n" "${PACOTES[i]}" "${PACOTES[i+2]}"
        n=$(( n + 1 ))
    done
)
echo "$PACKAGE_LIST" | pr -2 -t -w ${COLUMNS:-80}

echo
read -p "Escolha: " ESCOLHA

SELEGIONADOS=()
if [ "$ESCOLHA" == "t" ]; then
    for i in "${VISIVEIS[@]}"; do
        SELEGIONADOS+=("${PACOTES[i]}")
    done
elif [ "$ESCOLHA" != "n" ]; then
    ESCOLHA=$(echo "$ESCOLHA" | tr ',' ' ' | tr -s ' ')
    for num in $ESCOLHA; do
        idx=$(( num - 1 ))
        if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#VISIVEIS[@]}" ]; then
            SELEGIONADOS+=("${PACOTES[${VISIVEIS[idx]}]}")
        fi
    done
fi

if [ ${#SELEGIONADOS[@]} -gt 0 ]; then
    REPO=()
    AUR=()
    APPIMAGE=()
    for pkg in "${SELEGIONADOS[@]}"; do
        for i in "${!PACOTES[@]}"; do
            if (( i % 3 == 0 )) && [ "${PACOTES[i]}" == "$pkg" ]; then
                case "${PACOTES[i+2]}" in
                    repo)     REPO+=("$pkg") ;;
                    aur)      AUR+=("$pkg") ;;
                    appimage) APPIMAGE+=("$pkg") ;;
                esac
                break
            fi
        done
    done

    # obs-studio instala o plugin de browser junto (dependência)
    if [ ${#REPO[@]} -gt 0 ] && [[ " ${REPO[*]} " == *" obs-studio "* ]]; then
        REPO+=("obs-studio-plugin-browser")
    fi

    [ ${#REPO[@]} -gt 0 ] && safe sudo pacman -S --needed --noconfirm "${REPO[@]}"

    if [ ${#AUR[@]} -gt 0 ]; then
        if [ -z "$AUR_HELPER" ]; then
            warn "Nenhum AUR helper encontrado. Pacotes AUR não instalados: ${AUR[*]}"
        else
            safe $AUR_HELPER -S --needed --noconfirm "${AUR[@]}"
        fi
    fi

    # Instala os AppImages (download direto do site oficial, fora do AUR)
    for pkg in "${APPIMAGE[@]}"; do
        case "$pkg" in
            heroic-games-launcher) install_heroic_appimage ;;
            zapzap)                install_zapzap_appimage ;;
            protonup-qt)           install_protonup_qt_appimage ;;
        esac
    done
else
    info "Nenhum pacote adicional selecionado."
fi

# =============================================
# Icon Themes & Fonts
# =============================================
ICONS_FONTS=(
    "papirus-icon-theme"       "Tema de ícones Papirus" "repo"
    "breeze-icons"             "Ícones Breeze (KDE)" "repo"
    "ttf-nerd-fonts-symbols"   "Símbolos Nerd Fonts" "repo"
    "ttf-nerd-fonts-symbols-common" "Arquivos comuns Nerd Fonts Symbols" "repo"
    "ttf-nerd-fonts-symbols-mono"   "Fonte mono Nerd Fonts Symbols" "repo"
)

echo
info "============================================"
info " Icon Themes & Fonts"
info "============================================"
echo "Digite os números separados por espaço/vírgula (ex: 1 3 5)"
echo "'t' para selecionar todos | 'n' para pular"
echo

ICONS_VISIVEIS=()
for i in "${!ICONS_FONTS[@]}"; do
    if (( i % 3 == 0 )); then
        ICONS_VISIVEIS+=("$i")
    fi
done

ICONS_LIST=$(
    n=1
    for i in "${ICONS_VISIVEIS[@]}"; do
        printf "[%2d] %-35s (%s)\n" "$n" "${ICONS_FONTS[i]}" "${ICONS_FONTS[i+2]}"
        n=$(( n + 1 ))
    done
)
echo "$ICONS_LIST" | pr -2 -t -w ${COLUMNS:-80}

echo
read -p "Escolha: " ICONS_ESCOLHA

ICONS_SELECIONADOS=()
if [ "$ICONS_ESCOLHA" == "t" ]; then
    for i in "${ICONS_VISIVEIS[@]}"; do
        ICONS_SELECIONADOS+=("${ICONS_FONTS[i]}")
    done
elif [ "$ICONS_ESCOLHA" != "n" ]; then
    ICONS_ESCOLHA=$(echo "$ICONS_ESCOLHA" | tr ',' ' ' | tr -s ' ')
    for num in $ICONS_ESCOLHA; do
        idx=$(( num - 1 ))
        if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#ICONS_VISIVEIS[@]}" ]; then
            ICONS_SELECIONADOS+=("${ICONS_FONTS[${ICONS_VISIVEIS[idx]}]}")
        fi
    done
fi

if [ ${#ICONS_SELECIONADOS[@]} -gt 0 ]; then
    info "Instalando icon themes e fonts..."
    safe sudo pacman -S --needed --noconfirm "${ICONS_SELECIONADOS[@]}"
else
    info "Nenhum icon theme/font selecionado."
fi

echo
info "============================================"
info " Instalação concluída!"
info "============================================"
