"""Catalog of packages, system tweaks, services, and fixes."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PackageSource = Literal["repo", "aur", "appimage"]


@dataclass(frozen=True)
class PackageItem:
    """Represents a selectable software package or AppImage."""

    name: str
    description: str
    source: PackageSource
    category: str = "Geral"
    extra_packages: tuple[str, ...] = ()
    appimage_bin: str | None = None


@dataclass(frozen=True)
class TweakItem:
    """Represents a configurable system tweak."""

    key: str
    title: str
    description: str
    default_enabled: bool = True


@dataclass(frozen=True)
class ServiceBlock:
    """Represents a service stack (Virt-Manager, Samba, CUPS)."""

    key: str
    title: str
    description: str
    repo_packages: tuple[str, ...]
    aur_packages: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavSection:
    """Sidebar navigation section metadata."""

    key: str
    title: str
    subtitle: str
    icon_name: str


NAV_SECTIONS: tuple[NavSection, ...] = (
    NavSection(
        key="overview",
        title="Visão Geral",
        subtitle="Estado do sistema e arquitetura",
        icon_name="computer-symbolic",
    ),
    NavSection(
        key="packages",
        title="Pós-formatação",
        subtitle="Drivers AMD, pacotes, AUR e AppImages",
        icon_name="system-software-install-symbolic",
    ),
    NavSection(
        key="system",
        title="Sistema",
        subtitle="Env, sysctl, áudio e TRIM",
        icon_name="preferences-system-symbolic",
    ),
    NavSection(
        key="services",
        title="Serviços",
        subtitle="Virt-Manager, Samba e CUPS",
        icon_name="network-server-symbolic",
    ),
    NavSection(
        key="fixes",
        title="Correções",
        subtitle="ZapZap (PipeWire) e DaVinci Resolve",
        icon_name="applications-engineering-symbolic",
    ),
    NavSection(
        key="wallpapers",
        title="Wallpapers",
        subtitle="Coleção Rbgames (~1.2 GB)",
        icon_name="preferences-desktop-wallpaper-symbolic",
    ),
)


BASE_PACKAGES: tuple[str, ...] = (
    "base-devel",
    "git",
    "wine",
    "wine-gecko",
    "wine-mono",
    "winetricks",
    "ntfs-3g",
    "wget",
    "curl",
    "vulkan-radeon",
    "libva-mesa-driver",
    "vulkan-icd-loader",
    "lib32-mesa",
    "lib32-vulkan-radeon",
    "lib32-vulkan-icd-loader",
    "lib32-libva-mesa-driver",
    "mesa-demos",
    "xorg-xdpyinfo",
    "amd-ucode",
    "mesa-utils",
    "glfw-wayland",
    "eog",
    "unrar",
    "zip",
    "unzip",
    "udiskie",
)

AUR_BASE_DEPENDENCIES: tuple[str, ...] = ("electron29-bin",)

AUR_HELPERS: tuple[str, ...] = ("paru", "yay", "paru-bin", "yay-bin")


OPTIONAL_PACKAGES: tuple[PackageItem, ...] = (
    PackageItem("celluloid", "Reprodutor de vídeo GTK4 (frontend MPV)", "repo", "Mídia"),
    PackageItem("mpv", "Reprodutor de vídeo via terminal", "repo", "Mídia"),
    PackageItem("vlc", "Reprodutor de vídeo versátil", "repo", "Mídia"),
    PackageItem(
        "rocm-opencl-runtime",
        "Runtime OpenCL da ROCm (necessário p/ DaVinci Resolve)",
        "repo",
        "Sistema & GPU",
    ),
    PackageItem("android-tools", "Ferramentas ADB e Fastboot", "repo", "Desenvolvimento"),
    PackageItem("deckboard-bin", "Controle remoto para PC via celular", "aur", "Utilitários"),
    PackageItem("r-linux", "Linguagem R para análise estatística", "aur", "Desenvolvimento"),
    PackageItem("lutris", "Gerenciador de jogos (Wine/Nativo)", "repo", "Jogos"),
    PackageItem(
        "heroic-games-launcher",
        "Launcher para Epic/GOG/Amazon",
        "appimage",
        "Jogos",
        appimage_bin="Heroic.AppImage",
    ),
    PackageItem(
        "protonup-qt",
        "Gerenciador de Proton GE",
        "appimage",
        "Jogos",
        appimage_bin="ProtonUp-Qt.AppImage",
    ),
    PackageItem(
        "nexus-launcher",
        "Launcher de jogos Xodus (Nexus)",
        "appimage",
        "Jogos",
        appimage_bin="Nexus-Launcher.AppImage",
    ),
    PackageItem(
        "recomp-launcher",
        "Launcher de PC recomps",
        "appimage",
        "Jogos",
        appimage_bin="RecompLauncher.AppImage",
    ),
    PackageItem(
        "epic-games-launcher",
        "Launcher oficial da Epic Games",
        "appimage",
        "Jogos",
        appimage_bin="EpicGamesLauncher.AppImage",
    ),
    PackageItem("visual-studio-code-bin", "Editor de código Microsoft", "aur", "Desenvolvimento"),
    PackageItem("ventoy", "Criar USB bootável múltipla", "repo", "Utilitários"),
    PackageItem(
        "obs-studio",
        "OBS Studio (versão oficial) + plugin de browser",
        "repo",
        "Mídia",
        extra_packages=("obs-studio-plugin-browser",),
    ),
    PackageItem("obs-vkcapture", "Captura de tela Vulkan para OBS", "aur", "Mídia"),
    PackageItem("winff", "Conversor de vídeo com GUI", "aur", "Mídia"),
    PackageItem("gimp", "Editor de imagens avançado", "repo", "Mídia"),
    PackageItem("droidcam", "Usar celular como webcam", "aur", "Utilitários"),
    PackageItem("v4l2loopback-dc-dkms", "Módulo kernel para Droidcam", "aur", "Utilitários"),
    PackageItem("antimicrox", "Mapear teclado para controle", "aur", "Jogos"),
    PackageItem("google-chrome", "Navegador Google Chrome", "aur", "Internet"),
    PackageItem("github-cli", "CLI oficial do GitHub (gh)", "repo", "Desenvolvimento"),
    PackageItem("steam", "Plataforma de jogos digitais", "repo", "Jogos"),
    PackageItem("ark", "Gerenciador de arquivos (KDE)", "repo", "Utilitários"),
    PackageItem("gedit", "Editor de texto GNOME", "repo", "Utilitários"),
    PackageItem("gparted", "Gerenciador de partições", "repo", "Sistema & GPU"),
    PackageItem("mangohud", "Overlay de desempenho", "repo", "Jogos"),
    PackageItem("radeontop", "Monitor de GPU AMD", "repo", "Sistema & GPU"),
    PackageItem("bash-completion", "Auto-completar avançado", "repo", "Sistema & GPU"),
    PackageItem("telegram-desktop", "Mensageiro Telegram", "repo", "Internet"),
    PackageItem("discord", "Mensageiro para gamers", "repo", "Internet"),
    PackageItem(
        "zapzap",
        "WhatsApp desktop nativo",
        "appimage",
        "Internet",
        appimage_bin="ZapZap.AppImage",
    ),
    PackageItem("firefox", "Navegador Mozilla Firefox", "repo", "Internet"),
    PackageItem("qbittorrent", "Cliente torrent", "repo", "Internet"),
    PackageItem("filelight", "Analisador de espaço em disco", "repo", "Utilitários"),
    PackageItem("protontricks", "Winetricks simplificado para Proton", "repo", "Jogos"),
)


ICON_FONT_PACKAGES: tuple[PackageItem, ...] = (
    PackageItem("papirus-icon-theme", "Tema de ícones Papirus", "repo", "Aparência"),
    PackageItem("breeze-icons", "Ícones Breeze (KDE)", "repo", "Aparência"),
    PackageItem("ttf-nerd-fonts-symbols", "Símbolos Nerd Fonts", "repo", "Aparência"),
    PackageItem(
        "ttf-nerd-fonts-symbols-common",
        "Arquivos comuns Nerd Fonts Symbols",
        "repo",
        "Aparência",
    ),
    PackageItem(
        "ttf-nerd-fonts-symbols-mono",
        "Fonte mono Nerd Fonts Symbols",
        "repo",
        "Aparência",
    ),
)


SYSTEM_TWEAKS: tuple[TweakItem, ...] = (
    TweakItem(
        key="env_vars",
        title="Variáveis de ambiente AMD/Mesa",
        description="Define MANGOHUD=1, RADV_PERFTEST=aco,gpl e MESA_SHADER_CACHE_MAX_SIZE=10G em /etc/environment",
    ),
    TweakItem(
        key="sysctl",
        title="Ajustes de desempenho sysctl",
        description="Configura swappiness=10, inotify (524288), buffers de rede e kernel.panic=10",
    ),
    TweakItem(
        key="audio_limits",
        title="Limites de áudio em tempo real",
        description="Cria /etc/security/limits.d/99-audio.conf (rtprio 95, memlock unlimited) e adiciona usuário ao grupo audio",
    ),
    TweakItem(
        key="fstrim",
        title="TRIM automático para SSD",
        description="Habilita e inicia fstrim.timer no systemd",
    ),
    TweakItem(
        key="systemd_timeout",
        title="Reduzir timeout ao desligar",
        description="Define DefaultTimeoutStopSec=10s em /etc/systemd/system.conf",
    ),
)


SERVICE_BLOCKS: tuple[ServiceBlock, ...] = (
    ServiceBlock(
        key="virt_manager",
        title="Virt-Manager & QEMU",
        description="Virtualização com KVM/QEMU, rede padrão libvirt e acesso ao grupo libvirt",
        repo_packages=(
            "virt-manager",
            "qemu-full",
            "ebtables",
            "iptables-nft",
            "dnsmasq",
            "edk2-ovmf",
            "spice-vdagent",
            "virt-viewer",
        ),
        services=("libvirtd.service",),
        groups=("libvirt",),
    ),
    ServiceBlock(
        key="samba",
        title="Samba (compartilhamento de rede)",
        description="Configura usershares em /var/lib/samba/usershares, smb.conf e grupo sambashares",
        repo_packages=("kdenetwork-filesharing", "samba", "smbclient", "gvfs-smb"),
        aur_packages=("fusesmb",),
        services=("smb.service", "nmb.service"),
        groups=("sambashares",),
    ),
    ServiceBlock(
        key="cups",
        title="CUPS & Avahi (impressão)",
        description="Suporte a impressão local/PDF e descoberta mDNS na rede",
        repo_packages=("cups", "cups-pdf", "system-config-printer", "avahi", "nss-mdns"),
        services=("cups.service", "avahi-daemon.service"),
    ),
)


def detect_cpu_cores() -> int:
    """Return the CPUs available to this process (equivalente a `nproc`)."""
    process_count = getattr(os, "process_cpu_count", None)
    if callable(process_count):
        detected = process_count()
        if detected:
            return int(detected)
    return int(os.cpu_count() or 1)


def get_installed_pacman_packages() -> set[str]:
    """Return the set of locally installed package names via `pacman -Qq`."""
    if not shutil.which("pacman"):
        return set()
    try:
        proc = subprocess.run(
            ["pacman", "-Qq"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode != 0:
            return set()
        return {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return set()


def detect_aur_helper() -> str | None:
    """Return the first installed AUR helper binary name, or None."""
    for helper in AUR_HELPERS:
        if shutil.which(helper):
            return helper
    return None


def detect_environment_summary() -> dict[str, object]:
    """Collect lightweight system state for the overview and pages."""
    installed = get_installed_pacman_packages()
    base_installed = sum(1 for pkg in BASE_PACKAGES if pkg in installed)
    local_bin = Path.home() / ".local" / "bin"
    return {
        "cpu_cores": detect_cpu_cores(),
        "aur_helper": detect_aur_helper(),
        "total_installed_packages": len(installed),
        "base_installed_count": base_installed,
        "base_total_count": len(BASE_PACKAGES),
        "has_niri": shutil.which("niri") is not None,
        "has_resolve": os.access("/opt/resolve/bin/resolve", os.X_OK),
        "has_resolve_wrapper": (local_bin / "resolve").is_file(),
        "has_zapzap_fix": (
            Path.home()
            / ".config"
            / "pipewire"
            / "pipewire-pulse.conf.d"
            / "99-block-source-volume.conf"
        ).is_file(),
        "has_wallpapers": (Path.home() / "Wallpapers").is_dir(),
    }
