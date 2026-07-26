# RbgamesLinux

## install-virt-manager.sh

Script de instalação automatizada para **Virt-Manager/QEMU**, **Samba** e **CUPS** no Arch Linux.

### O que o script instala e configura:

- **Virt-Manager + QEMU** — Gerenciador de máquinas virtuais
- **Spice-vdagent** — Agent para melhor integre entre VM e máquina física
- **Samba** — Compartilhamento de pastas na rede local
- **CUPS** — Sistema de impressão
- **Avahi** — Descoberta automática de impressoras na rede (mDNS)

### Como usar:

```bash
git clone https://github.com/rbgameslinux/Scripts-de-configur-o-para-Archlinux.git
cd Scripts-de-configur-o-para-Archlinux
chmod +x install-virt-manager.sh
./install-virt-manager.sh
```

### O que o script faz:

1. Instala pacotes do Virt-Manager, QEMU e dependências
2. Habilita e inicia o serviço libvirtd
3. Configura a rede padrão do libvirt
4. Configura permissões do libvirt para o usuário atual
5. Instala e configura o Samba com usershares
6. Instala e configura o CUPS para impressão
7. Instala o Avahi para descoberta de impressoras na rede

### Pré-requisitos:

- Arch Linux (ou derivações como Manjaro, EndeavourOS)
- Helper AUR (paru ou yay) para instalar o fusesmb

### Notas:

- Após executar o script, faça **logout/login** para que as permissões de grupo tenham efeito
- Na VM, instale também: `sudo pacman -S spice-vdagent`
- Para configurar uma impressora, acesse `http://localhost:631` ou use o `system-config-printer`
