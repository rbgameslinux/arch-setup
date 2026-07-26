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

# --- 1. Instalar pacotes virt-manager/qemu ---
info "Instalando pacotes virt-manager/qemu..."
sudo pacman -S --needed --noconfirm \
    virt-manager qemu-desktop ebtables iptables-nft \
    dnsmasq edk2-ovmf spice-vdagent virt-viewer

# --- 2. Habilitar e iniciar libvirtd ---
info "Habilitando e iniciando libvirtd..."
sudo systemctl enable libvirtd.service
sudo systemctl start libvirtd.service

# --- 3. Configurar rede padrão ---
info "Configurando rede padrão do libvirt..."
sudo virsh net-start default 2>/dev/null || warn "Rede 'default' já está ativa"
sudo virsh net-autostart default 2>/dev/null || warn "Rede 'default' já em autostart"

# --- 4. Configurar permissões do libvirt ---
info "Configurando permissões do libvirt..."

if grep -q '^#unix_sock_group' /etc/libvirt/libvirtd.conf; then
    sudo sed -i 's/^#unix_sock_group =.*/unix_sock_group = "libvirt"/' /etc/libvirt/libvirtd.conf
fi
if grep -q '^#unix_sock_rw_perms' /etc/libvirt/libvirtd.conf; then
    sudo sed -i 's/^#unix_sock_rw_perms =.*/unix_sock_rw_perms = "0770"/' /etc/libvirt/libvirtd.conf
fi

if ! groups | grep -q libvirt; then
    sudo gpasswd -a "$(whoami)" libvirt
else
    warn "Usuário já está no grupo libvirt"
fi

sudo systemctl restart libvirtd.service

# --- 5. Instalar spice-vdagent ---
info "Instalando spice-vdagent..."
sudo pacman -S --needed --noconfirm spice-vdagent

# --- 6. Instalar Samba ---
info "Instalando Samba e dependências..."
sudo pacman -S --needed --noconfirm \
    kdenetwork-filesharing samba smbclient gvfs-smb

AUR_HELPER=$(command -v paru || command -v yay || true)
if [ -n "$AUR_HELPER" ]; then
    info "Instalando fusesmb via $AUR_HELPER..."
    $AUR_HELPER -S --needed --noconfirm fusesmb
else
    warn "Nenhum helper AUR encontrado. Instale 'fusesmb' manualmente."
fi

# --- 7. Configurar usershares ---
info "Configurando usershares do Samba..."
sudo mkdir -p /var/lib/samba/usershares
sudo groupadd -r sambashares 2>/dev/null || true
sudo chown root:sambashares /var/lib/samba/usershares
sudo chmod 1770 /var/lib/samba/usershares

# --- 8. Configurar smb.conf ---
info "Configurando smb.conf..."
if [ -f /etc/samba/smb.conf ] && [ ! -f /etc/samba/smb.conf.bak ]; then
    sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.bak
fi
if [ ! -f /etc/samba/smb.conf ]; then
    sudo touch /etc/samba/smb.conf
fi
if ! grep -q "usershare path" /etc/samba/smb.conf; then
    sudo sed -i '/^\[global\]/a \
  usershare path = /var/lib/samba/usershares\n\
  usershare max shares = 100\n\
  usershare allow guests = yes\n\
  usershare owner only = yes' /etc/samba/smb.conf
else
    warn "Usershare já configurado no smb.conf"
fi

# --- 9. Testar e reiniciar Samba ---
info "Testando configuração do Samba..."
sudo testparm -s /etc/samba/smb.conf 2>/dev/null || warn "Avisos na configuração do Samba"

sudo gpasswd sambashares -a "$(whoami)" 2>/dev/null || true
sudo systemctl restart smb.service
sudo systemctl restart nmb.service
sudo systemctl enable nmb.service
sudo systemctl enable smb.service

# --- 10. Instalar CUPS (impressão) ---
info "Instalando CUPS e dependências..."
sudo pacman -S --needed --noconfirm \
    cups cups-pdf system-config-printer

# --- 11. Instalar Avahi (descoberta de impressoras de rede) ---
info "Instalando Avahi para descoberta de impressoras de rede (mDNS)..."
sudo pacman -S --needed --noconfirm avahi nss-mdns

# --- 12. Habilitar serviços de impressão ---
info "Habilitando serviços de impressão..."
sudo systemctl enable cups.service
sudo systemctl start cups.service
sudo systemctl enable avahi-daemon.service
sudo systemctl start avahi-daemon.service

if ! grep -q "mdns" /etc/nsswitch.conf; then
    sudo sed -i 's/^hosts:.*/hosts: files mdns_minimal [NOTFOUND=return] dns/' /etc/nsswitch.conf
fi

# --- Concluído ---
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Instalação concluída com sucesso!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Serviços habilitados:"
echo "  - libvirtd, smb, nmb (virt-manager + Samba)"
echo "  - cups (impressão)"
echo "  - avahi-daemon (descoberta de impressoras na rede)"
echo ""
echo "Grupos: libvirt, sambashares"
echo ""
echo "Próximos passos:"
echo "  1. Faça logout/login para permissões de grupo"
echo "  2. Na VM, instale: sudo pacman -S spice-vdagent"
echo "  3. Para adicionar impressora, abra system-config-printer"
echo "     ou acesse http://localhost:631 no navegador"
