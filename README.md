# Scripts de Pós-Formatação para Arch Linux

Coleção de scripts para configuração inicial do Arch Linux.

## Scripts

### `pos-formatacao.sh`
Script principal de pós-formatação. Instala drivers para GPU AMD, Wine, AUR helper (paru/yay), e permite selecionar pacotes adicionais (Steam, VSCode, OBS, Chrome, etc.) de forma interativa.

### `install-virt-manager.sh`
Instala e configura **Virt-Manager/QEMU**, **Samba** (compartilhamento de rede) e **CUPS** (impressão).

### `fix-microfone-zapzap.sh`
Corrige o problema do ZapZap reduzir o volume do microfone no PipeWire, criando uma regra que bloqueia o controle de volume pelo QtWebEngineProcess.

## Como usar

```bash
git clone https://github.com/rbgameslinux/Scripts-de-configur-o-para-Archlinux.git
cd Scripts-de-configur-o-para-Archlinux
chmod +x *.sh
./pos-formatacao.sh
```

## Logs

Cada script gera um log automaticamente em `/tmp/pos-formatacao-<data>.log`.
