# Arch Setup — migração para app gráfico (Python/GTK4)

Coleção de scripts de pós-formatação do Arch Linux migrada para uma interface
gráfica em **Python + GTK4 + Libadwaita (PyGObject)**. Tarefas privilegiadas
usam **pkexec** (uma senha por lote); AUR, AppImages e fixes rodam na sessão do
usuário, com **askpass gráfico** quando o sudo é necessário.

**Versão atual:** `v2.0.0-rc2` (release candidate da migração GTK4).

## Como usar

```bash
git clone https://github.com/rbgameslinux/arch-setup.git
cd arch-setup
chmod +x run.sh   # se baixou por ZIP em vez de git clone
./run.sh
```

`run.sh` recusa root, verifica `python3`, `python-gobject`, `gtk4`, `libadwaita`
e `polkit`. Se faltar algum, ele primeiro abre a janela de senha do **polkit**
via `pkexec`; sem `pkexec`, usa `sudo` **apenas se houver terminal**; sem os
dois, mostra o comando e sai:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita polkit
```

O app **não fica instalado no sistema**: ele roda direto da pasta do projeto.

### Atalho no menu (opcional, mas recomendado)

```bash
./scripts/install-desktop-entry.sh
```

Cria `~/.local/share/applications/io.github.rbgameslinux.ArchSetup.desktop`
apontando para o `run.sh` desta pasta, com `Terminal=false`. Como é um `.desktop`
padrão XDG, o atalho aparece no menu do KDE, do XFCE/Thunar, do GNOME etc. Use
o atalho em vez de depender do duplo clique no `run.sh`: cada gerenciador de
arquivos trata `.sh` do seu jeito (o Thunar, por exemplo, pode abrir o arquivo
num editor). Se a pasta for movida ou apagada, o atalho deixa de funcionar.

## O que ele faz

- **Pacotes**: base/opcionais em categorias, toggle AUR (paru/yay) e busca
  repo-first (AUR só quando habilitado).
- **AppImages**: Heroic, ZapZap, ProtonUp-Qt, Nexus, RecompLauncher e Epic com
  estrutura completa estilo Gear Lever — pasta `~/AppImages` (ou a configurada
  no GSettings), ícone em `.icons/`, `.desktop` com `DESKTOPINTEGRATION=1`,
  chaves `X-AppImage-*` e `gearlever.conf`. Dá para **arrastar um AppImage
  avulso** para a linha “Instalar AppImage avulso”. Sem o Gear Lever instalado
  também funciona; desligando o switch, volta a `~/.local/bin`.
- **Sistema e serviços**: tweaks individuais e blocos para Virt-Manager, Samba
  e CUPS/Avahi.
- **Correções e wallpapers**: regra PipeWire para o microfone do ZapZap,
  wrapper do DaVinci Resolve com seleção de monitor via `niri` e download de
  wallpapers com barra de progresso.
- **Qualidade**: 87 testes automatizados; cada execução gera um log em
  `/tmp/arch-setup-<data>-<hora>.log`.

## Licença

Copyright (C) 2026 rbgameslinux.

Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os
termos da **GNU General Public License versão 3**, publicada pela Free Software
Foundation. O texto completo está em [`LICENSE`](LICENSE).

A integração com o Gear Lever é uma **reimplementação independente do
comportamento/formato** (GSettings, `.desktop`, `.icons/`, `gearlever.conf`),
sem cópia de código-fonte do projeto Gear Lever, que também é GPL-3.0. Os
AppImages instalados e os wallpapers baixados mantêm as licenças dos seus
respectivos autores.
