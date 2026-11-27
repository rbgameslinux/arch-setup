"""Integração estilo Gear Lever, sem Flatpak e sem chamar o aplicativo.

O Gear Lever (AUR: ``gearlever``) guarda AppImages na pasta definida pela
chave GSettings ``appimages-default-folder`` do schema ``it.mijorus.gearlever``
(padrão ``~/AppImages``) e escreve no arquivo ``.desktop`` uma linha Exec com
``env DESKTOPINTEGRATION=1``. Essa variável faz o runtime do AppImage pular
parte do trabalho de integração, que é o motivo da abertura mais rápida.

Aqui reproduzimos exatamente essa lógica: lemos a pasta configurada pelo
próprio Gear Lever quando o schema GSettings existe e geramos o ``.desktop``
com a mesma variável. Sem o schema (máquina sem o Gear Lever), usamos
``~/AppImages`` sem abortar. Nenhum comando do Gear Lever é executado e nenhum
Flatpak é utilizado.
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


def _schema_available() -> bool:
    """Verifica se o schema GSettings existe antes de instanciar Gio.Settings.

    Chamar ``Gio.Settings.new()`` com um schema inexistente gera um
    ``GLib-GIO-ERROR`` fatal (o processo aborta), então a checagem precisa
    acontecer primeiro.
    """
    try:
        from gi.repository import Gio

        source = Gio.SettingsSchemaSource.get_default()
        return source is not None and source.lookup(SCHEMA, True) is not None
    except Exception:
        return False


def _configured_folder() -> str | None:
    """Lê a pasta configurada no Gear Lever via GSettings/dconf, se existir."""
    if not _schema_available():
        return None
    try:
        from gi.repository import Gio

        settings = Gio.Settings.new(SCHEMA)
        folder = settings.get_string(FOLDER_KEY)
        return folder or None
    except Exception:
        return None


def appimages_dir(logger: Any | None = None) -> Path:
    """Pasta de AppImages escolhida no Gear Lever (com ``~`` expandido)."""
    folder = _configured_folder()
    path = Path(os.path.expanduser(folder or DEFAULT_FOLDER)).expanduser()
    if logger is not None and hasattr(logger, "info"):
        origem = "configuração Gear Lever" if folder else "padrão (schema ausente)"
        logger.info(f"Pasta de AppImages ({origem}): {path}")
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


def forget_installed(appimage: Path) -> None:
    """Remove a seção ``app.<md5>`` correspondente ao AppImage informado."""
    parser = configparser.ConfigParser(interpolation=None)
    path = config_path()
    try:
        if not path.exists():
            return
        parser.read(path)
        section = f"app.{hashlib.md5(str(appimage).encode()).hexdigest()}"
        if not parser.has_section(section):
            return
        parser.remove_section(section)
        with path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
    except (OSError, configparser.Error):
        pass
