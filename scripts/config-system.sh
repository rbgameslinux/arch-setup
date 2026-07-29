#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVISO]${NC} $1"; }
error() { echo -e "${RED}[ERRO]${NC} $1"; exit 1; }

LOG_FILE="/tmp/config-system-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

if [ "$EUID" -eq 0 ]; then
    error "Não execute como root. Use sudo."
fi

info "============================================"
info " Configurações do Sistema - Arch Linux"
info "============================================"
echo

# --- 1. /etc/environment ---
info "Configurando /etc/environment..."
if [ -f /etc/environment ] && [ ! -f /etc/environment.bak ]; then
    sudo cp /etc/environment /etc/environment.bak
    info "Backup criado: /etc/environment.bak"
fi

ENV_FILE="/etc/environment"
sudo touch "$ENV_FILE"

declare -A ENV_VARS=(
    ["MANGOHUD"]="1"
    ["RADV_PERFTEST"]="aco,gpl"
    ["MESA_SHADER_CACHE_MAX_SIZE"]="10G"
)

for key in "${!ENV_VARS[@]}"; do
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        warn "${key} já definido em /etc/environment"
    else
        echo "${key}=${ENV_VARS[$key]}" | sudo tee -a "$ENV_FILE" > /dev/null
        info "${key} adicionado ao /etc/environment"
    fi
done

# --- 2. Sysctl tweaks ---
info "Aplicando sysctl tweaks..."
SYSCTL_FILE="/etc/sysctl.d/99-performance.conf"
sudo tee "$SYSCTL_FILE" > /dev/null << 'EOF'
# Reduz uso de swap (prioriza RAM)
vm.swappiness=10

# Aumenta limite de arquivos monitorados (inotify)
fs.inotify.max_user_watches=524288

# Melhora performance de rede
net.core.rmem_max=134217728
net.core.wmem_max=134217728

# Kernel panic reboot
kernel.panic=10
EOF
sudo sysctl --load="$SYSCTL_FILE" > /dev/null
info "Sysctl tweaks aplicados em ${SYSCTL_FILE}"

# --- 3. Limites do sistema ---
info "Configurando limites do sistema..."
LIMITS_FILE="/etc/security/limits.d/99-audio.conf"
sudo tee "$LIMITS_FILE" > /dev/null << 'EOF'
# Limites para áudio em tempo real (PipeWire/JACK)
@audio - rtprio 95
@audio - memlock unlimited
EOF

if ! groups "$(whoami)" | grep -q audio; then
    sudo gpasswd -a "$(whoami)" audio
    info "Usuário adicionado ao grupo audio"
else
    warn "Usuário já está no grupo audio"
fi

# --- 4. fstrim (SSD TRIM) ---
info "Configurando TRIM automático para SSD..."
sudo systemctl enable fstrim.timer 2>/dev/null
sudo systemctl start fstrim.timer 2>/dev/null
if systemctl is-enabled fstrim.timer &>/dev/null; then
    info "fstrim.timer habilitado e iniciado"
fi

# # --- 5. Core dump limitado ---
# info "Limitando core dumps..."
# COREDUMP_CONF="/etc/systemd/coredump.conf"
# if [ -f "$COREDUMP_CONF" ]; then
#     sudo sed -i 's/^#Compress=yes/Compress=yes/' "$COREDUMP_CONF" 2>/dev/null || true
#     sudo sed -i 's/^#ProcessSizeMax=.*/ProcessSizeMax=100M/' "$COREDUMP_CONF" 2>/dev/null || true
#     info "Core dump limitado a 100MB"
# fi

# --- 6. Acelerar boot (reduzir tempo de espera) ---
info "Reduzindo tempo de espera do systemd..."
sudo sed -i 's/^#DefaultTimeoutStopSec.*/DefaultTimeoutStopSec=10s/' /etc/systemd/system.conf 2>/dev/null || true

# --- 7. GRUB kernel parameters ---
info "Configurando parâmetros do kernel no GRUB..."
GRUB_FILE="/etc/default/grub"
if [ -f "$GRUB_FILE" ]; then
    sudo cp "$GRUB_FILE" "${GRUB_FILE}.bak" 2>/dev/null || true
    info "Backup criado: ${GRUB_FILE}.bak"

    CURRENT=$(grep "^GRUB_CMDLINE_LINUX_DEFAULT" "$GRUB_FILE" | sed 's/GRUB_CMDLINE_LINUX_DEFAULT="//;s/"$//')

    NEW_PARAMS="quiet amdgpu.ppfeaturemask=0xffffffff transparent_hugepage=madvise"

    for param in $NEW_PARAMS; do
        if ! echo "$CURRENT" | grep -q "$param"; then
            CURRENT="$CURRENT $param"
            info "Adicionado: $param"
        else
            warn "Parâmetro já presente: $param"
        fi
    done

    sudo sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"${CURRENT}\"|" "$GRUB_FILE"

    info "Regenerando GRUB config..."
    if command -v grub-mkconfig &> /dev/null; then
        sudo grub-mkconfig -o /boot/grub/grub.cfg
    elif command -v grub2-mkconfig &> /dev/null; then
        sudo grub2-mkconfig -o /boot/grub2/grub.cfg
    else
        warn "grub-mkconfig não encontrado. Gere manualmente."
    fi
else
    warn "/etc/default/grub não encontrado. Bootloader pode não ser GRUB."
fi

echo
info "============================================"
info " Configurações aplicadas com sucesso!"
info "============================================"
echo
echo "Alterações feitas:"
echo "  - /etc/environment (MANGOHUD, RADV_PERFTEST, MESA_SHADER_CACHE)"
echo "  - /etc/sysctl.d/99-performance.conf (swap, inotify, rede)"
echo "  - /etc/security/limits.d/99-audio.conf (rtprio, memlock)"
echo "  - fstrim.timer ativado (TRIM SSD)"
echo "  - Timeout do systemd reduzido"
echo "  - GRUB: quiet + amdgpu.ppfeaturemask + transparent_hugepage"
echo
echo "Recomendado: reinicie o sistema ou faça logout/login"
