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

# --- 1.1 Isca de foco: exige zenity ou xterm ---
if ! command -v zenity >/dev/null 2>&1 && ! command -v xterm >/dev/null 2>&1; then
    warn "A isca de foco precisa de zenity ou xterm e nenhum está instalado."
    read -r -p "Instalar zenity e xterm agora? [s/N] " RESPOSTA
    case "$RESPOSTA" in
        s|S|sim|SIM)
            info "Instalando zenity e xterm..."
            if ! sudo pacman -S --needed --noconfirm zenity xterm; then
                warn "Falha na instalação. Instale manualmente: sudo pacman -S zenity xterm"
            fi
            ;;
        *)
            warn "Sem a isca, o Resolve pode fechar sozinho ao abrir em workspace vazia."
            ;;
    esac
fi

# --- 2. Wrapper ~/.local/bin/resolve ---
WRAPPER="${HOME}/.local/bin/resolve"
info "Criando wrapper ${WRAPPER}..."
mkdir -p "${HOME}/.local/bin"

cat > "${WRAPPER}.tmp" << 'WRAPPER_EOF'
#!/bin/sh
ulimit -c 0
unset QT_QPA_PLATFORM
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=xim
export QT_QPA_PLATFORMTHEME=default
export QT_QPA_PLATFORM_PLUGIN_PATH=/opt/resolve/libs/plugins/platforms

LOG="$HOME/.local/state/resolve-watchdog.log"
mkdir -p "$HOME/.local/state"

if ! niri msg version >/dev/null 2>&1; then
    exec /opt/resolve/bin/resolve "$@"
fi

log() { echo "[$(date "+%F %T")] $*" >> "$LOG"; }

# Retorna o ID (niri) da janela PRINCIPAL do Resolve. Ignora a janela
# secundária (título "resolve", marcada open-focused false no niri) e os
# relatórios de crash — detectar a secundária fazia o watchdog fechar a isca
# antes da principal ter foco, quebrando o teclado no popup de projeto novo.
resolve_main_window_id() {
    niri msg windows 2>/dev/null | awk '
        /^Window ID/ { id = $3; sub(/:/, "", id); title = "" }
        /^  Title:/ { title = $0 }
        /^  App ID: "resolve"/ && title != "" && !found &&
            title !~ /: "resolve"$/ &&
            title !~ /Relatório de Problemas/ &&
            title !~ /Problem Report/ { print id; found = 1 }
        END { exit found ? 0 : 1 }
    '
}

# Limpa lock stale do Qt (qtsingleapp-DaVinc-*) deixado quando o Resolve
# morre com o abort do libsystemd ao fechar. Só remove se o PID estiver morto.
clean_stale_lock() {
    for lock in /tmp/qtsingleapp-DaVinc-*lockfile*; do
        [ -e "$lock" ] || continue
        pid=$(tr -cd '0-9' < "$lock")
        if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$lock"
            log "lock stale do Qt removido: $lock (pid=${pid:-desconhecido})"
        fi
    done
}

focused_workspace() {
    niri msg workspaces 2>/dev/null | awk '/^[ \t]*\*/ { print $2; exit }'
}

workspace_has_window() {
    niri msg windows 2>/dev/null | awk -v ws="$1" '
        $1 == "Workspace" && $2 == "ID:" && $3 == ws { found = 1 }
        END { exit found ? 0 : 1 }'
}

# Isca de foco: workspace vazio impede o Resolve (X11) de receber a ativação
# inicial do xwayland-satellite/niri, e ele sai com código 0. Abrir qualquer
# janela antes resolve — aqui usamos um terminal kitty NATIVO do Wayland como
# isca, pois uma janela X11 (zenity/xterm) quebra o foco de teclado do Resolve
# quando é fechada. A isca é fechada graciosamente via niri assim que a janela
# principal do Resolve aparece.
DECOY_PID=""
DECOY_ID=""
DECOY_MARK="resolve-isca-$$"
decoy_open() {
    if [ -n "$DECOY_PID" ] && kill -0 "$DECOY_PID" 2>/dev/null; then
        return 0
    fi
    if command -v kitty >/dev/null 2>&1; then
        kitty --title="$DECOY_MARK" --class=Resolve-isca \
            /bin/bash -c 'sleep 300' >/dev/null 2>&1 &
    elif command -v xterm >/dev/null 2>&1; then
        xterm -geometry 60x3+0+0 -T "$DECOY_MARK" -e sh -c 'sleep 300' >/dev/null 2>&1 &
    else
        log "isca nao aberta: nem kitty nem xterm disponiveis"
        return 1
    fi
    sleep 1
    # Resolve o ID niri da isca (para fechamento gracioso) e o PID real.
    DECOY_ID=$(niri msg windows 2>/dev/null | awk -v m="$DECOY_MARK" '
        /^Window ID/ { id = $3; sub(/:/, "", id); title = "" }
        /^  Title:/ { title = $0 }
        title != "" && title ~ m && !found { print id; found = 1 }
        END { exit found ? 0 : 1 }
    ')
    REAL=$(pgrep -f "$DECOY_MARK" 2>/dev/null | head -1)
    [ -n "$REAL" ] && DECOY_PID="$REAL" || DECOY_PID=$!
    log "janela isca de foco aberta (pid $DECOY_PID, id ${DECOY_ID:-desconhecido})"
}

decoy_close() {
    if [ -n "$DECOY_ID" ]; then
        niri msg action close-window "$DECOY_ID" 2>/dev/null
    fi
    if [ -n "$DECOY_PID" ] && kill -0 "$DECOY_PID" 2>/dev/null; then
        kill "$DECOY_PID" 2>/dev/null
    fi
    pkill -f "$DECOY_MARK" 2>/dev/null
    pkill -f 'xterm .*-e sh -c sleep 300' 2>/dev/null
    DECOY_PID=""
    DECOY_ID=""
    log "janela isca de foco fechada"
}

WS=$(focused_workspace)
if [ -n "$WS" ]; then
    if ! workspace_has_window "$WS"; then
        decoy_open
    fi
else
    decoy_open
fi

attempt=0
while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
    clean_stale_lock
    /opt/resolve/bin/resolve "$@" &
    RPID=$!
    xws=$(pgrep -cf '^xwayland-satellite' 2>/dev/null || echo 0)
    log "tentativa $attempt iniciada (PID $RPID, xwayland-satellite=${xws:-0})"

    elapsed=0
    found=0
    while [ "$elapsed" -lt 45 ]; do
        if MAINWID=$(resolve_main_window_id); then
            found=1
            break
        fi
        if ! kill -0 "$RPID" 2>/dev/null; then
            wait "$RPID"
            code=$?
            log "resolve saiu antes de abrir janela (codigo $code)"
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ "$found" -eq 1 ]; then
        log "janela principal detectada no niri (PID $RPID, ID ${MAINWID:-desconhecido})"
        if [ -n "$MAINWID" ]; then
            niri msg action focus-window "$MAINWID" 2>/dev/null
            log "foco forcado na janela principal (ID $MAINWID)"
            sleep 1
        fi
        decoy_close
        start=$(date +%s)
        wait "$RPID"
        code=$?
        elapsed_run=$(($(date +%s) - start))
        log "resolve encerrou (codigo $code, ficou aberto ${elapsed_run}s)"
        if [ "$elapsed_run" -lt 30 ]; then
            log "AVISO: resolve fechou em menos de 30s; possivel crash/fechamento precoce"
        fi
        exit $code
    fi

    if kill -0 "$RPID" 2>/dev/null; then
        log "sem janela em ~20s; matando PID $RPID"
        kill "$RPID" 2>/dev/null
        sleep 3
        kill -9 "$RPID" 2>/dev/null
        wait "$RPID" 2>/dev/null
        pkill -f 'resolve -report[C]rash' 2>/dev/null
    fi

    if [ -n "$WS" ]; then
        if ! workspace_has_window "$WS"; then
            decoy_open
        fi
    else
        decoy_open
    fi
done

decoy_close
log "resolve falhou apos 3 tentativas; desistindo"
exit 1
WRAPPER_EOF

if [ -f "$WRAPPER" ] && cmp -s "${WRAPPER}.tmp" "$WRAPPER"; then
    warn "Wrapper já existente e correto, pulando"
    rm -f "${WRAPPER}.tmp"
else
    mv "${WRAPPER}.tmp" "$WRAPPER"
    chmod +x "$WRAPPER"
    info "Wrapper criado/atualizado: ${WRAPPER}"
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
