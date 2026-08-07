# Scripts de Pós-Formatação para Arch Linux

Coleção de scripts para configuração inicial do Arch Linux.

## Scripts

### `pos-formatacao.sh`
Script principal de pós-formatação. Instala drivers para GPU AMD, Wine, AUR helper (paru/yay), e permite selecionar pacotes adicionais (Steam, VSCode, OBS, Chrome, etc.) de forma interativa.

### `config-system.sh`
Aplica configurações do sistema: variáveis de ambiente para GPU AMD (MANGOHUD, RADV_PERFTEST, cache shader), sysctl tweaks (swap, inotify, rede), limites de áudio em tempo real, TRIM SSD, e parâmetros do GRUB (quiet, amdgpu.ppfeaturemask, transparent_hugepage).

### `install-virt-manager.sh`
Instala e configura **Virt-Manager/QEMU**, **Samba** (compartilhamento de rede) e **CUPS** (impressão).

### `fix-microfone-zapzap.sh`
Corrige o problema do ZapZap reduzir o volume do microfone no PipeWire, criando uma regra que bloqueia o controle de volume pelo QtWebEngineProcess.

## Como usar

### Via menu interativo (recomendado)

```bash
git clone https://github.com/rbgameslinux/arch-setup.git
cd Scripts-de-configur-o-para-Archlinux
chmod +x *.sh scripts/*.sh
./launcher.sh
```

### Direto

```bash
./scripts/pos-formatacao.sh
./scripts/config-system.sh
./scripts/install-virt-manager.sh
./scripts/fix-microfone-zapzap.sh
```

## Logs

Cada script gera um log automaticamente em `/tmp/pos-formatacao-<data>.log`.
