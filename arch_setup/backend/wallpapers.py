"""Wallpaper download backend — Fase 4."""

from __future__ import annotations

import gzip
import shutil
import tarfile
import urllib.request
from pathlib import Path

from arch_setup.backend.runner import TaskLogger

WALLPAPERS_URL = (
    "https://drive.usercontent.google.com/download"
    "?id=1siQhnSD-MO8gEXxusMocu_feXn60SzXw&export=download&confirm=t"
)
DEST_DIR = Path.home() / "Wallpapers"
TMP_TAR = Path("/tmp/rbgames-wallpapers.tar.gz")
TMP_EXTRACT = Path("/tmp/rbgames-wallpapers-extract")
_UA = "arch-setup-gui/2.0 (https://github.com/rbgameslinux/arch-setup)"
_EXPECTED_SIZE = 1_200_000_000  # ~1.2 GB, usado quando o servidor não informa Content-Length
_MAX_ATTEMPTS = 3


def wallpapers_installed() -> bool:
    try:
        return DEST_DIR.is_dir() and any(DEST_DIR.iterdir())
    except OSError:
        return False


def _human_mb(size_bytes: int) -> str:
    return f"{size_bytes / 1_048_576:.1f} MB"


def _download(logger: TaskLogger) -> bool:
    """Download with retries, equivalent to curl --retry 3."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(WALLPAPERS_URL, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=600) as resp:
                total_raw = resp.headers.get("Content-Length")
                total = int(total_raw) if total_raw else 0
                downloaded = 0
                with TMP_TAR.open("wb") as fh:
                    while True:
                        chunk = resp.read(131072)  # 128 KB
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            fraction = min(downloaded / total, 0.85)
                            status = f"Download: {_human_mb(downloaded)} / {_human_mb(total)}"
                        else:
                            fraction = 0.05 + 0.8 * min(downloaded / _EXPECTED_SIZE, 1.0)
                            status = f"Download: {_human_mb(downloaded)}..."
                        logger.set_progress(fraction, status)
            return True
        except Exception as exc:
            TMP_TAR.unlink(missing_ok=True)
            if attempt == _MAX_ATTEMPTS:
                logger.warn(
                    f"Falha no download após {_MAX_ATTEMPTS} tentativas "
                    f"(pode ser limite de cota do Google Drive): {exc}"
                )
                return False
            logger.warn(f"Tentativa {attempt}/{_MAX_ATTEMPTS} falhou: {exc}. Tentando novamente...")
    return False


def _verify_gzip(logger: TaskLogger) -> bool:
    """Full gzip integrity check (equivalente a `gzip -t`)."""
    logger.set_progress(0.86, "Verificando integridade...")
    try:
        with gzip.open(TMP_TAR, "rb") as fh:
            while fh.read(4 * 1024 * 1024):
                pass
    except Exception as exc:
        logger.warn(f"Arquivo baixado está corrompido (ou o Drive retornou uma página HTML): {exc}")
        return False
    return True


def _extract(logger: TaskLogger) -> bool:
    logger.set_progress(0.88, "Extraindo wallpapers...")
    if TMP_EXTRACT.exists():
        shutil.rmtree(TMP_EXTRACT, ignore_errors=True)
    TMP_EXTRACT.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(TMP_TAR, "r:gz") as tar:
            # filter="data" impede path traversal em arquivos hostis.
            tar.extractall(TMP_EXTRACT, filter="data")
    except Exception as exc:
        logger.warn(f"Falha ao extrair arquivo: {exc}")
        return False
    return True


def _install(logger: TaskLogger) -> bool:
    logger.set_progress(0.95, "Instalando wallpapers...")
    extracted = TMP_EXTRACT / "Rbgames-Wallpapers"
    if not extracted.is_dir():
        logger.warn("Estrutura do arquivo inesperada; nada foi instalado.")
        return False
    try:
        if DEST_DIR.exists():
            for item in extracted.iterdir():
                dest_item = DEST_DIR / item.name
                if item.is_dir():
                    shutil.copytree(item, dest_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest_item)
        else:
            shutil.move(str(extracted), str(DEST_DIR))
    except Exception as exc:
        logger.error(f"Falha ao mover wallpapers: {exc}")
        return False
    logger.info(f"Wallpapers instalados em {DEST_DIR}")
    return True


def download_and_install_wallpapers(logger: TaskLogger) -> bool:
    """Stream-download, verify, extract and install the wallpapers collection."""
    logger.info("Baixando wallpapers (~1.2 GB)... Isso pode demorar.")
    logger.set_progress(0.0, "Iniciando download...")
    try:
        if not _download(logger):
            return False
        if not _verify_gzip(logger):
            return False
        if not _extract(logger):
            return False
        if not _install(logger):
            return False
        logger.set_progress(1.0, "Wallpapers instalados com sucesso!")
        return True
    finally:
        # Limpa temporários em qualquer caminho de saída (inclusive falhas).
        TMP_TAR.unlink(missing_ok=True)
        shutil.rmtree(TMP_EXTRACT, ignore_errors=True)
