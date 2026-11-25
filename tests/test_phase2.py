"""Tests for Phase 2 — AUR backend, AppImages backend, and PackagesPage plan builder."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from arch_setup.backend import aur as aur_mod
from arch_setup.backend import appimages as appimages_mod
from arch_setup.models.catalog import (
    OPTIONAL_PACKAGES,
    ICON_FONT_PACKAGES,
    PackageItem,
    get_installed_pacman_packages,
)


class FakeLogger:
    """Minimal TaskLogger for unit tests."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.progress: list[float] = []
        self.last_cmd: list[str] = []
        self._cmd_return = 0

    def info(self, msg: str) -> None:
        self.lines.append(f"[INFO] {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"[AVISO] {msg}")

    def error(self, msg: str) -> None:
        self.lines.append(f"[ERRO] {msg}")

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def set_progress(self, frac: float, status: str = "") -> None:
        self.progress.append(frac)

    def set_cmd_return(self, rc: int) -> None:
        self._cmd_return = rc

    def run_command(
        self,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        env: dict | None = None,
    ) -> int:
        self.last_cmd = cmd
        return self._cmd_return


class AurBackendTests(unittest.TestCase):
    def test_detect_aur_helper_returns_none_or_string(self) -> None:
        result = aur_mod.detect_aur_helper()
        self.assertIsInstance(result, (str, type(None)))

    def test_aur_install_calls_helper(self) -> None:
        logger = FakeLogger()
        aur_mod.aur_install(["paru"], helper="paru", logger=logger)
        self.assertIn("paru", logger.last_cmd)
        self.assertIn("paru", logger.last_cmd)

    def test_aur_install_empty_list_noop(self) -> None:
        logger = FakeLogger()
        rc = aur_mod.aur_install([], helper="paru", logger=logger)
        self.assertEqual(rc, 0)
        self.assertEqual(logger.last_cmd, [])

    def test_install_electron29_bin(self) -> None:
        logger = FakeLogger()
        aur_mod.install_electron29_bin(helper="paru", logger=logger)
        self.assertIn("electron29-bin", logger.last_cmd)

    @patch("arch_setup.backend.aur.shutil.which", return_value=None)
    def test_install_aur_helper_clone_failure(self, _mock_which: object) -> None:
        logger = FakeLogger()
        logger.set_cmd_return(1)
        result = aur_mod.install_aur_helper("paru", logger=logger)
        self.assertIsNone(result)
        self.assertTrue(any("Falha ao clonar" in l for l in logger.lines))


class AppImagesBackendTests(unittest.TestCase):
    def test_appimage_installers_registry(self) -> None:
        self.assertIn("heroic-games-launcher", appimages_mod.APPIMAGE_INSTALLERS)
        self.assertIn("zapzap", appimages_mod.APPIMAGE_INSTALLERS)
        self.assertIn("protonup-qt", appimages_mod.APPIMAGE_INSTALLERS)

    @patch("arch_setup.backend.appimages._http_get", side_effect=Exception("no network"))
    def test_install_heroic_fails_gracefully(self, _mock: object) -> None:
        logger = FakeLogger()
        ok = appimages_mod.install_heroic(logger)
        self.assertFalse(ok)
        self.assertTrue(any("Falha" in l for l in logger.lines))

    @patch("arch_setup.backend.appimages._github_latest_appimage", return_value=None)
    def test_install_zapzap_no_url(self, _mock: object) -> None:
        logger = FakeLogger()
        ok = appimages_mod.install_zapzap(logger)
        self.assertFalse(ok)

    @patch("arch_setup.backend.appimages._github_latest_appimage", return_value=None)
    def test_install_protonup_qt_no_url(self, _mock: object) -> None:
        logger = FakeLogger()
        ok = appimages_mod.install_protonup_qt(logger)
        self.assertFalse(ok)


class CatalogPhase2Tests(unittest.TestCase):
    def test_all_optional_packages_have_valid_source(self) -> None:
        valid_sources = {"repo", "aur", "appimage"}
        for pkg in OPTIONAL_PACKAGES:
            self.assertIn(pkg.source, valid_sources, f"{pkg.name} has invalid source")

    def test_obs_studio_has_browser_plugin_in_extra(self) -> None:
        obs = next(p for p in OPTIONAL_PACKAGES if p.name == "obs-studio")
        self.assertIn("obs-studio-plugin-browser", obs.extra_packages)

    def test_icon_font_packages_all_repo(self) -> None:
        for pkg in ICON_FONT_PACKAGES:
            self.assertEqual(pkg.source, "repo", f"{pkg.name} should be repo")

    def test_appimage_items_have_bin_name(self) -> None:
        for pkg in OPTIONAL_PACKAGES:
            if pkg.source == "appimage":
                self.assertIsNotNone(
                    pkg.appimage_bin,
                    f"{pkg.name} AppImage should have appimage_bin set",
                )

    def test_no_duplicate_package_names(self) -> None:
        names = [p.name for p in OPTIONAL_PACKAGES]
        self.assertEqual(len(names), len(set(names)), "Duplicate package names found")

    def test_categories_present(self) -> None:
        cats = {p.category for p in OPTIONAL_PACKAGES}
        self.assertTrue(len(cats) > 1, "Expected multiple categories")


if __name__ == "__main__":
    unittest.main()
