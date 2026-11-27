"""AppImage download, icon extraction, and .desktop creation in user space."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from arch_setup.backend import gearlever as gearlever_mod
from arch_setup.backend.runner import TaskLogger

BIN_DIR = Path.home() / ".local" / "bin"
APP_DIR = Path.home() / ".local" / "share" / "applications"
ICONS_DIR = Path.home() / ".local" / "share" / "icons" / "hicolor"

GH_API_BASE = "https://api.github.com/repos"
GH_RELEASES_URL = GH_API_BASE + "/{repo}/releases/latest"
GH_ALL_RELEASES_URL = GH_API_BASE + "/{repo}/releases"

_UA = "arch-setup-gui/2.0 (https://github.com/rbgameslinux/arch-setup)"

# Official Epic installer endpoint; redirect (~303) to the versioned CDN file.
EPIC_APPIMAGE_URL = (
    "https://launcher-public-service-prod06.ol.epicgames.com"
    "/launcher/api/installer/download/EpicGamesLauncher-x86_64.AppImage"
)


_MAX_ATTEMPTS = 3


def _http_get(url: str, *, timeout: int = 20) -> bytes:
    """HTTP GET with retries (equivalente a curl --retry 3)."""
    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_error = exc
    raise last_error if last_error is not None else RuntimeError("Falha de rede")


def _github_latest_appimage(
    repo: str,
    pattern: str,
    logger: TaskLogger,
    *,
    include_prereleases: bool = False,
) -> str | None:
    """Return the browser download URL for the latest AppImage matching *pattern*.

    Some projects (e.g. RecompLauncher) publish only beta releases; for those,
    ``include_prereleases=True`` scans the releases list in order instead of
    hitting ``/releases/latest`` (which ignores prereleases).
    """
    api_url = (
        GH_ALL_RELEASES_URL.format(repo=repo)
        if include_prereleases
        else GH_RELEASES_URL.format(repo=repo)
    )
    logger.info(f"Consultando releases do GitHub: {repo}")
    try:
        data = json.loads(_http_get(api_url))
    except Exception as exc:
        logger.warn(f"Falha ao consultar API do GitHub ({repo}): {exc}")
        return None

    releases = data if include_prereleases and isinstance(data, list) else [data]
    for release in releases:
        for asset in release.get("assets", []):
            url = asset.get("browser_download_url", "")
            if url.endswith(".AppImage") and re.search(pattern, url):
                return url
    logger.warn(f"Nenhum AppImage encontrado para o padrão '{pattern}' em {repo}")
    return None


def _download_file(url: str, dest: Path, label: str, logger: TaskLogger) -> bool:
    """Stream-download *url* to *dest*, reporting progress via logger."""
    logger.info(f"Baixando {label}...")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
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
            dest.unlink(missing_ok=True)
            if attempt == _MAX_ATTEMPTS:
                logger.warn(f"Falha no download de {label} após {attempt} tentativas: {exc}")
                return False
            logger.warn(f"Tentativa {attempt}/{_MAX_ATTEMPTS} falhou para {label}: {exc}")
    return False


@dataclass(frozen=True)
class AppImageMetadata:
    """Dados lidos de dentro do AppImage (`.desktop` embutido)."""

    name: str = ""
    comment: str = ""
    args: str = ""
    categories: str = ""
    wm_class: str = ""
    mime: str = ""
    version: str = ""


@contextmanager
def _extracted(appimage: Path, logger: TaskLogger) -> Iterator[Path | None]:
    """Extrai o AppImage numa pasta temporária e devolve `squashfs-root`."""
    tmp = Path(tempfile.mkdtemp(prefix="arch-setup-appimage-"))
    try:
        proc = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=tmp,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
        squash = tmp / "squashfs-root"
        yield squash if proc.returncode == 0 and squash.is_dir() else None
    except Exception as exc:
        logger.warn(f"Falha ao extrair metadados de {appimage.name}: {exc}")
        yield None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_icon(squash: Path) -> tuple[Path, str] | None:
    """Localiza `.DirIcon` (ou o primeiro png/svg) dentro do AppImage."""
    dir_icon = squash / ".DirIcon"
    if dir_icon.exists():
        try:
            resolved = dir_icon.resolve()
            if resolved.is_file():
                ext = "svg" if resolved.suffix.lower() == ".svg" else "png"
                return resolved, ext
        except OSError:
            pass

    ignored = re.compile(r"tray|splash|banner|header", re.IGNORECASE)
    for pattern in ("*.png", "*.svg"):
        for candidate in sorted(squash.rglob(pattern), key=lambda p: len(p.parts)):
            if not ignored.search(candidate.name):
                ext = "svg" if pattern == "*.svg" else "png"
                return candidate, ext
    return None


def _copy_icon_file(
    src: Path,
    ext: str,
    dest_dir: Path,
    icon_name: str,
    logger: TaskLogger,
    *,
    label: str,
) -> str | None:
    """Copia um ícone já localizado para `dest_dir` dentro da extração atual."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    icon_path = dest_dir / f"{icon_name}.{ext}"
    try:
        shutil.copy2(src, icon_path)
    except OSError as exc:
        logger.warn(f"Falha ao copiar ícone de {label}: {exc}")
        return None
    _refresh_icon_cache()
    return str(icon_path)


def _parse_desktop_entry(path: Path) -> dict[str, str]:
    """Parser minimalista do grupo `[Desktop Entry]` de um arquivo .desktop."""
    result: dict[str, str] = {}
    in_entry = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_entry = stripped == "[Desktop Entry]"
            continue
        if not in_entry or not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if "[" in key:  # traduções, ex.: Name[pt_BR]
            continue
        result.setdefault(key, value)
    return result


def _desktop_exec_args(exec_value: str) -> str:
    """Remove `env VAR=...` e o executável, devolvendo só os argumentos."""
    try:
        tokens = shlex.split(exec_value)
    except ValueError:
        return ""
    while tokens and "=" in tokens[0]:
        tokens.pop(0)
    if tokens and tokens[0] == "env":
        tokens.pop(0)
        while tokens and "=" in tokens[0]:
            tokens.pop(0)
    if tokens:
        tokens.pop(0)  # o próprio executável
    return " ".join(t for t in tokens if not t.startswith("%"))


def _read_metadata(appimage: Path, logger: TaskLogger) -> AppImageMetadata | None:
    """Lê nome, comentário, argumentos, versão e ícone de dentro do AppImage."""
    with _extracted(appimage, logger) as squash:
        if squash is None:
            return None
        desktop: Path | None = None
        for candidate in (
            *squash.glob("*.desktop"),
            *squash.glob("usr/share/applications/*.desktop"),
        ):
            fields = _parse_desktop_entry(candidate)
            if fields.get("Name"):
                desktop, parsed = candidate, fields
                break
        else:
            parsed = {}
        return AppImageMetadata(
            name=parsed.get("Name", ""),
            comment=parsed.get("Comment", ""),
            args=_desktop_exec_args(parsed.get("Exec", "")),
            categories=parsed.get("Categories", ""),
            wm_class=parsed.get("StartupWMClass", ""),
            mime=parsed.get("MimeType", ""),
            version=parsed.get("X-AppImage-Version", ""),
        )


def _extract_appimage_icon(
    appimage: Path,
    icon_name: str,
    logger: TaskLogger,
) -> str | None:
    """Extrai e instala o ícone no hicolor; devolve o caminho ou None."""
    with _extracted(appimage, logger) as squash:
        if squash is None:
            return None
        found = _find_icon(squash)
        if found is None:
            return None
        src, ext = found
        dest_dir = (
            ICONS_DIR / "scalable" / "apps"
            if ext == "svg"
            else ICONS_DIR / "256x256" / "apps"
        )
        return _copy_icon_file(
            src, ext, dest_dir, icon_name, logger, label=appimage.name
        )


def _gearlever_icon(
    appimage: Path,
    prefix: str,
    logger: TaskLogger,
) -> str | None:
    """Copia o ícone para a pasta do Gear Lever na mesma extração temporária."""
    with _extracted(appimage, logger) as squash:
        if squash is None:
            return None
        found = _find_icon(squash)
        if found is None:
            return None
        src, ext = found
        return _copy_icon_file(
            src,
            ext,
            gearlever_mod.icons_dir(logger),
            prefix,
            logger,
            label=appimage.name,
        )


def _refresh_icon_cache() -> None:
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


def _update_desktop_db() -> None:
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


def _write_desktop(
    app_id: str,
    name: str,
    generic_name: str,
    comment: str,
    exec_path: Path,
    icon: str,
    categories: str,
    wm_class: str,
    *,
    exec_line: str | None = None,
) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    desktop = APP_DIR / f"{app_id}.desktop"
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name={name}
GenericName={generic_name}
Comment={comment}
TryExec={exec_path}
Exec={exec_line or exec_path}
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


STAGING_DIR = Path(tempfile.gettempdir()) / "arch-setup-appimages"


def _dest_for(filename: str, *, use_gearlever: bool, logger: TaskLogger) -> Path:
    """Stage temporário para o estilo Gear Lever; ~/.local/bin no modo simples."""
    if use_gearlever:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        return STAGING_DIR / filename
    return BIN_DIR / filename


def _gearlever_filename(name: str) -> str:
    """Nome de arquivo usado pelo Gear Lever (minúsculas, sem especiais)."""
    base = Path(name).stem.lower().replace(" ", "_")
    base = re.sub(r"[^\w.]+", "", base).strip(".")
    return f"{base}.appimage" if base else "appimage.appimage"


def _unique_target(folder: Path, desired: str, version: str) -> Path:
    """Resolve conflitos como o Gear Lever: nome_versão.appimage, depois _N."""
    candidate = folder / desired
    if not candidate.exists():
        return candidate
    stem = desired  # o Gear Lever preserva ".appimage" na base do nome
    if version:
        suffix = re.sub(r"[^\w]", "_", version.replace(".", "_"))
        numbered = folder / f"{stem}_{suffix}.appimage"
        if not numbered.exists():
            return numbered
    index = 1
    while True:
        numbered = folder / f"{stem}_{index}.appimage"
        if not numbered.exists():
            return numbered
        index += 1


def _version_from_url(url: str) -> str:
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[-_][A-Za-z0-9.]+)?)", url)
    return match.group(1) if match else ""


def _gearlever_prefix(display: str) -> str:
    """Nome base usado nos arquivos .desktop/.appimage do Gear Lever."""
    return _gearlever_filename(display).removesuffix(".appimage")


def _installed_appimage_files(folder: Path, prefix: str) -> list[Path]:
    return sorted(p for p in folder.glob(f"{prefix}*.appimage") if p.is_file())


def _installed_version(prefix: str) -> str:
    desktop = APP_DIR / f"{prefix}.desktop"
    if not desktop.is_file():
        return ""
    return _parse_desktop_entry(desktop).get("X-AppImage-Version", "").strip()


def _skip_installed_version(
    prefix: str, version: str, logger: TaskLogger, *, use_gearlever: bool
) -> bool:
    """Evita baixar novamente quando a mesma versão já está instalada."""
    if not use_gearlever or not version:
        return False
    folder = gearlever_mod.appimages_dir(logger)
    if not _installed_appimage_files(folder, prefix):
        return False
    current = _installed_version(prefix)
    if current and current == version.strip():
        logger.info(f"{prefix}: versão {version} já instalada; pulando download.")
        return True
    return False


def _cleanup_stale_gearlever(
    folder: Path, prefix: str, keep: Path, logger: TaskLogger
) -> None:
    """Remove versões antigas para não acumular AppImages/.desktop/ícones."""
    canonical_desktop = APP_DIR / f"{prefix}.desktop"
    for stale in _installed_appimage_files(folder, prefix):
        if stale.resolve() != keep.resolve():
            stale.unlink(missing_ok=True)
            gearlever_mod.forget_installed(stale)
    for stale in APP_DIR.glob(f"{prefix}*.desktop"):
        if stale.resolve() != canonical_desktop.resolve():
            stale.unlink(missing_ok=True)
    icons = gearlever_mod.icons_dir(logger)
    for pattern in (f"{prefix}*.png", f"{prefix}*.svg"):
        for stale in icons.glob(pattern):
            stale.unlink(missing_ok=True)


def _write_full_desktop(
    target: Path,
    prefix: str,
    meta: AppImageMetadata,
    *,
    name: str,
    comment: str,
    icon: str,
    version: str,
) -> None:
    """Escreve o .desktop completo, igual ao formato gerado pelo Gear Lever."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    args = shlex.split(meta.args)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Comment={comment}",
        f"Icon={icon}",
        f"TryExec={target}",
        f"Exec={gearlever_mod.exec_line(target, *args)}",
        "Terminal=false",
    ]
    if meta.categories:
        lines.append(f"Categories={meta.categories}")
    if meta.wm_class:
        lines.append(f"StartupWMClass={meta.wm_class}")
    if meta.mime:
        lines.append(f"MimeType={meta.mime}")
    if version:
        lines.append(f"X-AppImage-Version={version}")
    lines.append(f"X-AppImage-Name={name}")
    (APP_DIR / f"{prefix}.desktop").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _update_desktop_db()


def _gearlever_finalize(
    source: Path,
    *,
    logger: TaskLogger,
    name: str,
    comment: str,
    icon_name: str,
    categories: str,
    wm_class: str,
    version: str = "",
) -> Path | None:
    """Instala *source* reproduzindo toda a estrutura do Gear Lever."""
    logger.set_progress(0.85, f"{name}: aplicando estrutura Gear Lever...")
    meta = _read_metadata(source, logger)
    display = meta.name if meta and meta.name else name
    final_version = version or (meta.version if meta else "")
    folder = gearlever_mod.appimages_dir(logger)
    folder.mkdir(parents=True, exist_ok=True)
    prefix = _gearlever_prefix(display)
    existing = _installed_appimage_files(folder, prefix)
    installed_version = _installed_version(prefix)

    if (
        existing
        and installed_version
        and final_version
        and installed_version == final_version.strip()
    ):
        keep = existing[0]
        _cleanup_stale_gearlever(folder, prefix, keep, logger)
        logger.info(f"{display} {final_version} já instalado em {keep}; nada a fazer.")
        return keep

    target = folder / f"{prefix}.appimage"
    try:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        target.chmod(0o755)
    except OSError as exc:
        logger.warn(f"Falha ao copiar {name} para {target}: {exc}")
        return None

    _cleanup_stale_gearlever(folder, prefix, target, logger)
    icon = _gearlever_icon(source, prefix, logger) or "applications-other"

    effective_meta = meta or AppImageMetadata(
        categories=categories, wm_class=wm_class
    )
    _write_full_desktop(
        target,
        prefix,
        effective_meta,
        name=display,
        comment=meta.comment if meta and meta.comment else comment,
        icon=icon,
        version=final_version,
    )
    gearlever_mod.record_installed(target, display, effective_meta.args)
    logger.info(f"{display} instalado em {target} (estrutura Gear Lever)")
    return target


def _finish_install(
    dest: Path,
    *,
    use_gearlever: bool,
    logger: TaskLogger,
    app_id: str,
    name: str,
    generic_name: str,
    comment: str,
    icon_name: str,
    categories: str,
    wm_class: str,
    version: str = "",
) -> bool:
    """Register the AppImage with full Gear Lever layout or manual .desktop."""
    if use_gearlever:
        final = _gearlever_finalize(
            dest,
            logger=logger,
            name=name,
            comment=comment,
            icon_name=icon_name,
            categories=categories,
            wm_class=wm_class,
            version=version,
        )
        if final is None:
            return False
        if dest != final:
            dest.unlink(missing_ok=True)
        return True

    logger.set_progress(0.85, f"{name}: extraindo ícone...")
    icon = _extract_appimage_icon(dest, icon_name, logger) or icon_name
    _write_desktop(
        app_id,
        name,
        generic_name,
        comment,
        dest,
        icon,
        categories,
        wm_class,
    )
    logger.info(f"{name} instalado em {dest}")
    return True


def install_appimage_file(
    source: Path,
    logger: TaskLogger,
    *,
    use_gearlever: bool = True,
    name: str = "",
    comment: str = "",
    categories: str = "Game;Utility;",
    wm_class: str = "",
    icon_name: str = "applications-other",
    version: str = "",
) -> bool:
    """Instala um AppImage avulso (arrastado pelo usuário) com o nosso padrão."""
    if not source.is_file():
        logger.warn(f"Arquivo não encontrado: {source}")
        return False
    display = name or source.stem
    if use_gearlever:
        return (
            _gearlever_finalize(
                source,
                logger=logger,
                name=display,
                comment=comment,
                icon_name=icon_name,
                categories=categories,
                wm_class=wm_class,
                version=version,
            )
            is not None
        )

    dest = BIN_DIR / source.name
    if source.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, dest)
        except OSError as exc:
            logger.warn(f"Falha ao copiar {source.name}: {exc}")
            return False
    return _finish_install(
        dest,
        use_gearlever=False,
        logger=logger,
        app_id=_gearlever_filename(display).removesuffix(".appimage"),
        name=display,
        generic_name="Application",
        comment=comment,
        icon_name=icon_name,
        categories=categories,
        wm_class=wm_class,
    )


# ─────────────────────────── Public install functions ───────────────────────────


def install_heroic(logger: TaskLogger, *, use_gearlever: bool = False) -> bool:
    """Download and install Heroic Games Launcher AppImage."""
    logger.set_progress(0.0, "Heroic: consultando release...")
    YML_URL = "https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/latest/download/latest-linux.yml"
    try:
        yml = _http_get(YML_URL).decode("utf-8", errors="replace")
        match = re.search(
            r"^path:\s*['\"]?([^\s'\"#]+\.AppImage)", yml, re.MULTILINE
        )
        if not match:
            logger.warn("Não foi possível identificar o AppImage do Heroic no latest-linux.yml")
            return False
        appimage_name = Path(match.group(1).strip()).name
        url = f"https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/latest/download/{appimage_name}"
        version = _version_from_url(appimage_name)
    except Exception as exc:
        logger.warn(f"Falha ao obter metadados do Heroic: {exc}")
        return False

    if _skip_installed_version(
        _gearlever_prefix("Heroic Games Launcher"),
        version,
        logger,
        use_gearlever=use_gearlever,
    ):
        return True

    dest = _dest_for("Heroic.AppImage", use_gearlever=use_gearlever, logger=logger)
    logger.set_progress(0.1, "Heroic: baixando...")
    if not _download_file(url, dest, "Heroic (~180 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="heroic",
        name="Heroic Games Launcher",
        generic_name="Game launcher",
        comment="Launcher para Epic Games, GOG e Amazon Games",
        icon_name="heroic",
        categories="Game;Utility;",
        wm_class="heroic",
        version=version,
    )


def install_zapzap(logger: TaskLogger, *, use_gearlever: bool = False) -> bool:
    """Download and install ZapZap (WhatsApp) AppImage."""
    logger.set_progress(0.0, "ZapZap: consultando release...")
    url = _github_latest_appimage("rafatosta/zapzap", r"linux-x86_64\.AppImage", logger)
    if not url:
        return False

    version = _version_from_url(url)
    if _skip_installed_version(
        _gearlever_prefix("ZapZap"), version, logger, use_gearlever=use_gearlever
    ):
        return True

    dest = _dest_for("ZapZap.AppImage", use_gearlever=use_gearlever, logger=logger)
    logger.set_progress(0.1, "ZapZap: baixando...")
    if not _download_file(url, dest, "ZapZap (~190 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="zapzap",
        name="ZapZap",
        generic_name="WhatsApp client",
        comment="WhatsApp desktop nativo",
        icon_name="zapzap",
        categories="Network;InstantMessaging;",
        wm_class="zapzap",
        version=version,
    )


def install_protonup_qt(logger: TaskLogger, *, use_gearlever: bool = False) -> bool:
    """Download and install ProtonUp-Qt AppImage."""
    logger.set_progress(0.0, "ProtonUp-Qt: consultando release...")
    url = _github_latest_appimage("DavidoTek/ProtonUp-Qt", r"x86_64\.AppImage", logger)
    if not url:
        return False

    version = _version_from_url(url)
    if _skip_installed_version(
        _gearlever_prefix("ProtonUp-Qt"), version, logger, use_gearlever=use_gearlever
    ):
        return True

    dest = _dest_for("ProtonUp-Qt.AppImage", use_gearlever=use_gearlever, logger=logger)
    logger.set_progress(0.1, "ProtonUp-Qt: baixando...")
    if not _download_file(url, dest, "ProtonUp-Qt (~63 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="protonup-qt",
        name="ProtonUp-Qt",
        generic_name="Proton manager",
        comment="Gerenciador de Proton GE",
        icon_name="protonup-qt",
        categories="Utility;",
        wm_class="protonup-qt",
        version=version,
    )


def install_nexus_launcher(logger: TaskLogger, *, use_gearlever: bool = False) -> bool:
    """Download and install the Nexus Launcher AppImage."""
    logger.set_progress(0.0, "Nexus Launcher: consultando release...")
    url = _github_latest_appimage(
        "domsvoboda/nexus-launcher",
        r"Nexus-Launcher-.*-x86_64\.AppImage",
        logger,
    )
    if not url:
        return False

    version = _version_from_url(url)
    if _skip_installed_version(
        _gearlever_prefix("Nexus Launcher"),
        version,
        logger,
        use_gearlever=use_gearlever,
    ):
        return True

    dest = _dest_for(
        "Nexus-Launcher.AppImage", use_gearlever=use_gearlever, logger=logger
    )
    logger.set_progress(0.1, "Nexus Launcher: baixando...")
    if not _download_file(url, dest, "Nexus Launcher (~131 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="nexus-launcher",
        name="Nexus Launcher",
        generic_name="Game launcher",
        comment="Launcher independente de jogos Xodus",
        icon_name="nexus-launcher",
        categories="Game;Utility;",
        wm_class="nexus-launcher",
        version=version,
    )


def install_recomp_launcher(logger: TaskLogger, *, use_gearlever: bool = False) -> bool:
    """Download and install the latest RecompLauncher beta AppImage.

    The project currently publishes only prereleases, so the releases list is
    scanned instead of ``/releases/latest``.
    """
    logger.set_progress(0.0, "RecompLauncher: consultando release...")
    url = _github_latest_appimage(
        "elripalda/RecompLauncher",
        r"RecompLauncher_.*_amd64\.AppImage",
        logger,
        include_prereleases=True,
    )
    if not url:
        return False

    version = _version_from_url(url)
    if _skip_installed_version(
        _gearlever_prefix("RecompLauncher"),
        version,
        logger,
        use_gearlever=use_gearlever,
    ):
        return True

    dest = _dest_for(
        "RecompLauncher.AppImage", use_gearlever=use_gearlever, logger=logger
    )
    logger.set_progress(0.1, "RecompLauncher: baixando...")
    if not _download_file(url, dest, "RecompLauncher (~93 MB)", logger):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="recomp-launcher",
        name="RecompLauncher",
        generic_name="Game launcher",
        comment="Gerenciador de PC recomps",
        icon_name="recomp-launcher",
        categories="Game;Utility;",
        wm_class="recomp-launcher",
        version=version,
    )


def install_epic_games_launcher(
    logger: TaskLogger, *, use_gearlever: bool = False
) -> bool:
    """Download the official Epic Games Launcher AppImage (~193 MB)."""
    logger.set_progress(0.0, "Epic Games Launcher: preparando download...")
    dest = _dest_for(
        "EpicGamesLauncher.AppImage", use_gearlever=use_gearlever, logger=logger
    )
    if not _download_file(
        EPIC_APPIMAGE_URL, dest, "Epic Games Launcher (~193 MB)", logger
    ):
        return False

    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _finish_install(
        dest,
        use_gearlever=use_gearlever,
        logger=logger,
        app_id="epic-games-launcher",
        name="Epic Games Launcher",
        generic_name="Game launcher",
        comment="Launcher oficial da Epic Games",
        icon_name="epic-games-launcher",
        categories="Game;Utility;",
        wm_class="EpicGamesLauncher",
    )


APPIMAGE_INSTALLERS = {
    "heroic-games-launcher": install_heroic,
    "zapzap": install_zapzap,
    "protonup-qt": install_protonup_qt,
    "nexus-launcher": install_nexus_launcher,
    "recomp-launcher": install_recomp_launcher,
    "epic-games-launcher": install_epic_games_launcher,
}
