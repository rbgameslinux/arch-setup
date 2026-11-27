"""AUR helper installation and package building in user space."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from arch_setup.backend.runner import TaskLogger

ASKPASS_SCRIPT = Path(__file__).resolve().parent.parent / "ui" / "askpass.py"

AUR_HELPERS_PRIORITY = ("paru", "yay", "paru-bin", "yay-bin")


def detect_aur_helper() -> str | None:
    for h in AUR_HELPERS_PRIORITY:
        if shutil.which(h):
            return h
    return None


def _build_env_with_askpass() -> dict[str, str]:
    """Return an env copy that sets SUDO_ASKPASS to our GTK4 dialog."""
    env = os.environ.copy()
    if ASKPASS_SCRIPT.is_file():
        # ZIPs e clones podem perder o bit de execução; o sudo exige um
        # SUDO_ASKPASS executável, senão falha antes de abrir a janela.
        try:
            ASKPASS_SCRIPT.chmod(ASKPASS_SCRIPT.stat().st_mode | 0o111)
        except OSError:
            pass
        env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
    return env


def install_aur_helper(
    choice: str,
    *,
    logger: TaskLogger,
) -> str | None:
    """Clone and build the chosen AUR helper via makepkg -si.

    Prefers the ``-bin`` package on fresh systems (no go/rust makedepends) and
    falls back to the source package. Returns the helper command name on
    success or None on failure.
    makepkg refuses to run as root so this must run as the normal user.
    SUDO_ASKPASS is set so that any sudo call inside makepkg uses our
    GTK4 password dialog.
    """
    helper = "paru" if choice == "paru" else "yay"

    # Em VM recém-instalada o -bin evita makedepends como go>=1.26/rust.
    for package in (f"{helper}-bin", helper):
        aur_url = f"https://aur.archlinux.org/{package}.git"
        tmp_dir = Path(f"/tmp/{package}-aur-build")

        logger.info(f"Instalando AUR helper: {package}")

        # Remove stale clone
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        env = _build_env_with_askpass()

        # Clone
        rc = logger.run_command(["git", "clone", aur_url, str(tmp_dir)])
        if rc != 0:
            logger.warn(f"Falha ao clonar {aur_url}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            continue

        # makepkg -si --noconfirm: instala o helper e suas deps via sudo
        rc = logger.run_command(
            ["makepkg", "-si", "--noconfirm"],
            cwd=tmp_dir,
            env=env,
        )

        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)

        if rc != 0:
            logger.warn(f"makepkg falhou para {package}")
            continue

        # Tanto o build normal quanto o -bin fornecem o mesmo comando.
        if shutil.which(helper):
            logger.info(f"{helper} instalado com sucesso via {package}.")
            return helper

        logger.warn(f"{helper} não encontrado no PATH após instalar {package}.")

    logger.warn(
        f"Não foi possível instalar {helper}. Verifique base-devel, git e o acesso "
        "aos repositórios; instale manualmente: sudo pacman -S --needed base-devel git"
    )
    return None


def aur_install(
    packages: list[str],
    *,
    helper: str,
    logger: TaskLogger,
) -> int:
    """Install AUR packages using the given helper.

    Sets SUDO_ASKPASS so that any sudo escalation inside the helper uses
    our graphical password dialog.
    """
    if not packages:
        return 0
    env = _build_env_with_askpass()
    logger.info(f"Instalando {len(packages)} pacote(s) AUR via {helper}: {' '.join(packages)}")
    return logger.run_command(
        [helper, "-S", "--needed", "--noconfirm", *packages],
        env=env,
    )


def install_electron29_bin(
    *,
    helper: str,
    logger: TaskLogger,
) -> int:
    """Install electron29-bin as AUR base dependency."""
    logger.info("Instalando electron29-bin (dependência AUR base)...")
    return aur_install(["electron29-bin"], helper=helper, logger=logger)
