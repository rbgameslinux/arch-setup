"""AppImage download, icon extraction, and .desktop creation in user space."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from arch_setup.backend.runner import TaskLogger

BIN_DIR = Path.home() / ".local" / "bin"
APP_DIR = Path.home() / ".local" / "share" / "applications"
ICONS_DIR = Path.home() / ".local" / "share" / "icons" / "hicolor"

GH_API_BASE = "https://api.github.com/repos"
GH_RELEASES_URL = GH_API_BASE + "/{repo}/releases/latest"

_UA = "arch-setup-gui/2.0 (https://github.com/rbgameslinux/arch-setup)"


def _http_get(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _github_latest_appimage(repo: str, pattern: str, logger: TaskLogger) -> str | None:
    """Return the browser download URL for the latest AppImage matching *pattern*."""
    api_url = GH_RELEASES_URL.format(repo=repo)
    logger.info(f"Consultando releases do GitHub: {repo}")
    try:
        data = json.loads(_http_get(api_url))
    except Exception as exc:
        logger.warn(f"Falha ao consultar API do GitHub ({repo}): {exc}")
        return None
    for asset in data.get("assets", []):
        url = asset.get("browser_download_url", "")
        if url.endswith(".AppImage") and re.search(pattern, url):
            return url
    logger.warn(f"Nenhum AppImage encontrado para o padrão '{pattern}' em {repo}")
    return None


def _download_file(url: str, dest: Path, label: str, logger: TaskLogger) -> bool:
    """Stream-download *url* to *dest*, reporting progress via logger."""
    logger.info(f"Baixando {label}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total_raw = resp.headers.get("Content-Length")
            total = int(total_raw) if total_raw else 0
            downloaded = 0
            chunk_size = 65536
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        frac = min(downloaded / total, 1.0)
                        logger.set_progress(frac, f"{label}: {int(frac * 100)}%")
        return True
    except Exception as exc:
        logger.warn(f"Falha no download de {label}: {exc}")
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def _extract_appimage_icon(
    appimage: Path,
    icon_name: str,
    logger: TaskLogger,
) -> str | None:
    """Extract icon from AppImage and install into hicolor; returns icon path or name."""
    tmp = Path(tempfile.mkdtemp(prefix="arch-setup-icon-"))
    try:
        rc = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=tmp,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
        if rc.returncode != 0:
            return None

        squash = tmp / "squashfs-root"
        # Prefer .DirIcon (may be a symlink)
        dir_icon = squash / ".DirIcon"
        src: Path | None = None
        if dir_icon.exists():
            resolved = dir_icon.resolve()
            if resolved.is_file():
                src = resolved

        if src is None:
            # Walk squashfs-root looking for a suitable icon
            candidates = sorted(
                squash.rglob("*.png"),
                key=lambda p: len(p.parts),
            )
            ignored = re.compile(r"tray|splash|banner|header", re.IGNORECASE)
            for c in candidates:
                if not ignored.search(c.name):
                    src = c
                    break
            if src is None:
                candidates_svg = sorted(squash.rglob("*.svg"), key=lambda p: len(p.parts))
                for c in candidates_svg:
                    if not ignored.search(c.name):
                        src = c
                        break

        if src is None or not src.is_file():
            return None

        ext = "svg" if src.suffix.lower() == ".svg" else "png"
        if ext == "svg":
            dest_dir = ICONS_DIR / "scalable" / "apps"
        else:
            dest_dir = ICONS_DIR / "256x256" / "apps"

        dest_dir.mkdir(parents=True, exist_ok=True)
        icon_path = dest_dir / f"{icon_name}.{ext}"
        shutil.copy2(src, icon_path)

        # Refresh icon cache (best-effort)
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", str(ICONS_DIR)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        return str(icon_path)
    except Exception as exc:
        logger.warn(f"Falha ao extrair ícone de {appimage.name}: {exc}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_desktop(
    app_id: str,
    name: str,
    generic_name: str,
    comment: str,
    exec_path: Path,
    icon: str,
    categories: str,
    wm_class: str,
) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    desktop = APP_DIR / f"{app_id}.desktop"
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name={name}
GenericName={generic_name}
Comment={comment}
Exec={exec_path}
Icon={icon}
Terminal=false
Categories={categories}
StartupWMClass={wm_class}
""",
        encoding="utf-8",
    )
    # Update desktop DB (best-effort)
    try:
        subprocess.run(
            ["update-desktop-database", str(APP_DIR)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


# ─────────────────────────── Public install functions ───────────────────────────


def install_heroic(logger: TaskLogger) -> bool:
    """Download and install Heroic Games Launcher AppImage."""
    logger.set_progress(0.0, "Heroic: consultando release...")
    YML_URL = "https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/latest/download/latest-linux.yml"
    try:
        yml = _http_get(YML_URL).decode("utf-8", errors="replace")
        match = re.search(r"^path:\s*(.+\.AppImage)", yml, re.MULTILINE)
        if not match:
            logger.warn("Não foi possível identificar o AppImage do Heroic no latest-linux.yml")
            return False
        appimage_name = match.group(1).strip()
        url = f"https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/latest/download/{appimage_name}"
    except Exception as exc:
        logger.warn(f"Falha ao obter metadados do Heroic: {exc}")
        return False

    dest = BIN_DIR / "Heroic.AppImage"
    logger.set_progress(0.1, "Heroic: baixando...")
    if not _download_file(url, dest, "Heroic (~180 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    logger.set_progress(0.85, "Heroic: extraindo ícone...")
    icon = _extract_appimage_icon(dest, "heroic", logger) or "heroic"
    _write_desktop(
        "heroic",
        "Heroic Games Launcher",
        "Game launcher",
        "Launcher para Epic Games, GOG e Amazon Games",
        dest,
        icon,
        "Game;Utility;",
        "heroic",
    )
    logger.info(f"Heroic instalado em {dest}")
    return True


def install_zapzap(logger: TaskLogger) -> bool:
    """Download and install ZapZap (WhatsApp) AppImage."""
    logger.set_progress(0.0, "ZapZap: consultando release...")
    url = _github_latest_appimage("rafatosta/zapzap", r"linux-x86_64\.AppImage", logger)
    if not url:
        return False

    dest = BIN_DIR / "ZapZap.AppImage"
    logger.set_progress(0.1, "ZapZap: baixando...")
    if not _download_file(url, dest, "ZapZap (~190 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    logger.set_progress(0.85, "ZapZap: extraindo ícone...")
    icon = _extract_appimage_icon(dest, "zapzap", logger) or "zapzap"
    _write_desktop(
        "zapzap",
        "ZapZap",
        "WhatsApp client",
        "WhatsApp desktop nativo",
        dest,
        icon,
        "Network;InstantMessaging;",
        "zapzap",
    )
    logger.info(f"ZapZap instalado em {dest}")
    return True


def install_protonup_qt(logger: TaskLogger) -> bool:
    """Download and install ProtonUp-Qt AppImage."""
    logger.set_progress(0.0, "ProtonUp-Qt: consultando release...")
    url = _github_latest_appimage("DavidoTek/ProtonUp-Qt", r"x86_64\.AppImage", logger)
    if not url:
        return False

    dest = BIN_DIR / "ProtonUp-Qt.AppImage"
    logger.set_progress(0.1, "ProtonUp-Qt: baixando...")
    if not _download_file(url, dest, "ProtonUp-Qt (~63 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    logger.set_progress(0.85, "ProtonUp-Qt: extraindo ícone...")
    icon = _extract_appimage_icon(dest, "protonup-qt", logger) or "protonup-qt"
    _write_desktop(
        "protonup-qt",
        "ProtonUp-Qt",
        "Proton manager",
        "Gerenciador de Proton GE",
        dest,
        icon,
        "Utility;",
        "protonup-qt",
    )
    logger.info(f"ProtonUp-Qt instalado em {dest}")
    return True


APPIMAGE_INSTALLERS = {
    "heroic-games-launcher": install_heroic,
    "zapzap": install_zapzap,
    "protonup-qt": install_protonup_qt,
}
