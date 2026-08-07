#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

LOG_FILE="/tmp/fix-davinci-resolve-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

if [ "$EUID" -eq 0 ]; then
    error "Não execute como root. Use sudo."
fi

# Monitor onde o Resolve vai abrir (pode mudar após formatar; use niri msg outputs)
OUTPUT="DP-1"

info "============================================"
info " Fix DaVinci Resolve - Arch Linux"
info "============================================"
echo

# --- 1. Checar instalação ---
if [ ! -x /opt/resolve/bin/resolve ]; then
    error "Resolve não encontrado em /opt/resolve. Instale antes de rodar este script."
fi
info "Resolve detectado em /opt/resolve"

# --- 2. Wrapper ~/.local/bin/resolve ---
WRAPPER="${HOME}/.local/bin/resolve"
info "Criando wrapper ${WRAPPER}..."
mkdir -p "${HOME}/.local/bin"

WRAPPER_CONTENT='#!/bin/sh
ulimit -c 0
unset QT_QPA_PLATFORM
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORMTHEME=default
export QT_QPA_PLATFORM_PLUGIN_PATH=/opt/resolve/libs/plugins/platforms
exec /opt/resolve/bin/resolve "$@"
'

if [ -f "$WRAPPER" ] && cmp -s <(printf '%s' "$WRAPPER_CONTENT") "$WRAPPER"; then
    warn "Wrapper já existente e correto, pulando"
else
    printf '%s' "$WRAPPER_CONTENT" > "$WRAPPER"
    chmod +x "$WRAPPER"
    info "Wrapper criado: ${WRAPPER}"
fi

# --- 3. .desktop ---
DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${DESKTOP_DIR}/com.blackmagicdesign.resolve.desktop"

info "Configurando o lançador (.desktop)..."
mkdir -p "$DESKTOP_DIR"

if [ -f "$DESKTOP_FILE" ]; then
    if grep -q "Exec=.*resolve %u" "$DESKTOP_FILE" && ! grep -q "${HOME}/.local/bin/resolve" "$DESKTOP_FILE"; then
        sed -i "s|^Exec=.*|Exec=${WRAPPER} %u|" "$DESKTOP_FILE"
        info "Exec do .desktop atualizado para o wrapper"
    elif grep -q "${HOME}/.local/bin/resolve" "$DESKTOP_FILE"; then
        warn ".desktop já aponta para o wrapper, pulando"
    else
        sed -i "s|^Exec=.*|Exec=${WRAPPER} %u|" "$DESKTOP_FILE"
        info "Exec do .desktop atualizado para o wrapper"
    fi
else
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DaVinci Resolve
GenericName=DaVinci Resolve
Comment=Revolutionary new tools for editing, visual effects, color correction and professional audio post production, all in a single application!
Path=/opt/resolve/
Exec=${WRAPPER} %u
Terminal=false
MimeType=application/x-resolveproj;
Icon=/opt/resolve/graphics/DV_Resolve.png
StartupNotify=true
Name[en_US]=DaVinci Resolve
EOF
    info ".desktop criado: ${DESKTOP_FILE}"
fi

# --- 4. Regras do niri ---
NIRI_CONFIG="${HOME}/.config/niri/config.kdl"

if [ -f "$NIRI_CONFIG" ]; then
    if grep -q 'app-id="resolve"' "$NIRI_CONFIG"; then
        warn "Regras do Resolve já existem no niri, pulando"
    else
        cat >> "$NIRI_CONFIG" << EOF

// DaVinci Resolve — a janela principal (título "DaVinci Resolve ...") e a
// segunda janela (Workspace > segunda janela, título "resolve") precisam abrir
// flutuando em (0,0) do ${OUTPUT}, senão o Resolve não renderiza a janela.
window-rule {
    match app-id="resolve"
    open-floating true
    open-on-output "${OUTPUT}"
    default-floating-position x=0 y=0 relative-to="top-left"
}
window-rule {
    match app-id="resolve" title="^resolve$"
    open-focused false
}
EOF
        info "Regras do Resolve adicionadas ao niri (output: ${OUTPUT})"
    fi
else
    warn "Config do niri não encontrado em ${NIRI_CONFIG}. Pule se não usar niri."
fi

echo
info "============================================"
info " Fix aplicado com sucesso!"
info "============================================"
echo
echo "O que foi feito:"
echo "  - Wrapper: ${WRAPPER} (força QT_QPA_PLATFORM=xcb + sem core dump)"
echo "  - Launcher: ${DESKTOP_FILE}"
if [ -f "$NIRI_CONFIG" ]; then
    echo "  - Regras do niri em: ${NIRI_CONFIG}"
fi
echo
echo "Observações:"
echo "  - Se o monitor mudou de nome, edite OUTPUT=\"${OUTPUT}\" no script"
echo "    e remova/atualize o bloco no config do niri antes de rodar de novo."
echo "  - Abra o Resolve pelo menu/launcher (usa o .desktop) ou pelo terminal: resolve"
echo "  - Se houver QT_QPA_PLATFORM=wayland global (niri/environment.d), o"
echo "    wrapper o sobrescreve — não precisa mexer."
echo
echo "Limpeza opcional (core dumps antigos que o Resolve gerava ao fechar):"
echo "  sudo rm -f /var/lib/systemd/coredump/core.*"
echo
echo "Para reverter:"
echo "  rm ${WRAPPER}"
echo "  (remova os blocos 'match app-id=\"resolve\"' do config do niri)"
