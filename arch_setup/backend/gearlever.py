"""Integração estilo Gear Lever, sem Flatpak e sem chamar o aplicativo.

O Gear Lever (AUR: ``gearlever``) guarda AppImages na pasta definida pela
chave GSettings ``appimages-default-folder`` do schema ``it.mijorus.gearlever``
(padrão ``~/AppImages``) e escreve no arquivo ``.desktop`` uma linha Exec com
``env DESKTOPINTEGRATION=1``. Essa variável faz o runtime do AppImage pular
parte do trabalho de integração, que é o motivo da abertura mais rápida.

Aqui reproduzimos exatamente essa lógica: lemos a pasta configurada pelo
próprio Gear Lever e geramos o ``.desktop`` com a mesma variável. Nenhum
comando do Gear Lever é executado e nenhum Flatpak é utilizado.
"""

from __future__ import annotations

import configparser
import hashlib
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "it.mijorus.gearlever"
FOLDER_KEY = "appimages-default-folder"
DEFAULT_FOLDER = "~/AppImages"
INTEGRATION_ENV = "DESKTOPINTEGRATION=1"


def native_binary() -> str | None:
    """Retorna o caminho do `gearlever` nativo (AUR), se instalado."""
    return shutil.which("gearlever")


def is_available() -> bool:
    return native_binary() is not None


def _configured_folder() -> str | None:
    """Lê a pasta configurada no Gear Lever via GSettings/dconf."""
    try:
        from gi.repository import Gio

        settings = Gio.Settings.new(SCHEMA)
        folder = settings.get_string(FOLDER_KEY)
        return folder or None
    except Exception:
        return None


def appimages_dir(logger: Any | None = None) -> Path:
    """Pasta de AppImages escolhida no Gear Lever (com ``~`` expandido)."""
    folder = _configured_folder() or DEFAULT_FOLDER
    path = Path(os.path.expanduser(folder)).expanduser()
    if logger is not None and hasattr(logger, "info"):
        logger.info(f"Pasta de AppImages (configuração Gear Lever): {path}")
    return path


def prepare_destination(filename: str, logger: Any | None = None) -> Path:
    """Cria a pasta configurada e devolve o destino do AppImage."""
    target_dir = appimages_dir(logger)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / filename


def icons_dir(logger: Any | None = None) -> Path:
    """Subpasta ``.icons`` usada pelo Gear Lever dentro da pasta de AppImages."""
    path = appimages_dir(logger) / ".icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exec_line(appimage: Path, *args: str) -> str:
    """Linha Exec no formato usado pelo Gear Lever."""
    return f"env {INTEGRATION_ENV} {shlex.join([str(appimage), *args])}"


def config_path() -> Path:
    """Arquivo ``gearlever.conf`` do usuário (respeita XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gearlever.conf"


def record_installed(appimage: Path, name: str, exec_args: str = "") -> None:
    """Grava a seção ``app.<md5>`` do Gear Lever, preservando as existentes."""
    parser = configparser.ConfigParser(interpolation=None)
    path = config_path()
    try:
        if path.exists():
            parser.read(path)
        section = f"app.{hashlib.md5(str(appimage).encode()).hexdigest()}"
        parser[section] = {
            "name": name,
            "file_path": str(appimage),
            "default_exec_arguments": exec_args,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
    except (OSError, configparser.Error):
        # Config é apenas para interoperabilidade; falha não impede a instalação.
        pass
