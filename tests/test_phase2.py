"""Tests for Phase 2 — AUR backend, AppImages backend, and PackagesPage plan builder."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from arch_setup.backend import aur as aur_mod
from arch_setup.backend import appimages as appimages_mod
from arch_setup.backend.search import PackageResult
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
        self._cmd_returns: list[int] | None = None

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
        self._cmd_returns = None

    def set_cmd_returns(self, returns: list[int]) -> None:
        self._cmd_returns = list(returns)

    def run_command(
        self,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        env: dict | None = None,
    ) -> int:
        self.last_cmd = cmd
        if self._cmd_returns is not None:
            return self._cmd_returns.pop(0) if self._cmd_returns else self._cmd_return
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
        self.assertEqual(
            sum("Falha ao clonar" in line for line in logger.lines), 2
        )
        self.assertTrue(any("base-devel" in line for line in logger.lines))

    @patch("arch_setup.backend.aur.shutil.which", return_value="/usr/bin/yay")
    def test_install_aur_helper_falls_back_to_source(self, _mock_which: object) -> None:
        logger = FakeLogger()
        # clone/makepkg de yay-bin falham; clone/makepkg de yay funcionam.
        logger.set_cmd_returns([0, 1, 0, 0])
        result = aur_mod.install_aur_helper("yay", logger=logger)
        self.assertEqual(result, "yay")
        self.assertTrue(
            any("makepkg falhou para yay-bin" in line for line in logger.lines)
        )
        self.assertTrue(any("via yay" in line for line in logger.lines))

    def test_askpass_script_gains_executable_bit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "askpass.py"
            script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            script.chmod(0o644)
            with patch.object(aur_mod, "ASKPASS_SCRIPT", script):
                env = aur_mod._build_env_with_askpass()
            self.assertEqual(env["SUDO_ASKPASS"], str(script))
            self.assertTrue(script.stat().st_mode & 0o111)


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


class PackagesUIRowsTests(unittest.TestCase):
    @unittest.skipUnless(
        bool(
            __import__("os").environ.get("DISPLAY")
            or __import__("os").environ.get("WAYLAND_DISPLAY")
        ),
        "Sem display gráfico disponível",
    )
    def test_categories_are_collapsible_expanders(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gtk

            from arch_setup.ui.pages.packages import PackagesPage
        except Exception:
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        if not Gtk.init_check():
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        Adw.init()
        page = PackagesPage()
        expected = len({p.category for p in OPTIONAL_PACKAGES}) + 1  # + ícones/fontes
        self.assertEqual(len(page._expanders), expected)
        self.assertTrue(
            all(isinstance(row, Adw.ExpanderRow) for row in page._expanders.values())
        )

        first = page._rows[0]
        first._check.set_active(True)
        subtitle = page._expanders[first.item.category].get_subtitle()
        self.assertIn("1 selecionado", subtitle)
        total = sum(
            1
            for r in page._rows
            if r.item.category == first.item.category and r.get_visible()
        )
        self.assertEqual(
            page._counts[first.item.category].get_label(), f"1/{total}"
        )
        plan = page._build_plan()
        self.assertIsNotNone(plan)
        self.assertTrue(plan.stages)

        page._clear_selections()
        self.assertFalse(first._check.get_active())
        self.assertIn(
            "0 selecionado", page._expanders[first.item.category].get_subtitle()
        )

        page._aur_switch_row.set_active(True)
        aur_row = next(r for r in page._rows if r.item.source == "aur")
        self.assertTrue(aur_row.get_visible())

    @unittest.skipUnless(
        bool(
            __import__("os").environ.get("DISPLAY")
            or __import__("os").environ.get("WAYLAND_DISPLAY")
        ),
        "Sem display gráfico disponível",
    )
    def test_searched_repo_package_enters_plan_and_aur_needs_toggle(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gtk

            from arch_setup.ui.pages.packages import PackagesPage
        except Exception:
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        if not Gtk.init_check():
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        Adw.init()
        page = PackagesPage()
        self.assertFalse(page._results_group.get_visible())

        page._render_results(
            [
                PackageResult("mpv", "Reprodutor repo", "repo", "extra"),
                PackageResult("yay", "Helper AUR", "aur"),
            ]
        )
        self.assertTrue(page._results_group.get_visible())
        self.assertFalse(page._custom_rows["yay"].get_visible())

        page._custom_rows["mpv"]._check.set_active(True)
        # Selected packages are promoted to the top on the next render.
        page._render_results(
            [
                PackageResult("gimp", "Editor repo", "repo", "extra"),
                PackageResult("mpv", "Reprodutor repo", "repo", "extra"),
            ]
        )
        self.assertEqual(
            [row.item.name for row in page._rendered_rows], ["mpv", "gimp"]
        )
        self.assertIn("1 selecionado no topo", page._results_group.get_description())

        # Clicking the clear ('x') button drops results but keeps selections.
        page._searching = True
        generation = page._search_generation
        page._search_entry.set_text("")
        page._search_entry.emit("search-changed")
        self.assertFalse(page._searching)
        self.assertGreater(page._search_generation, generation)
        self.assertEqual(page._last_results, [])
        self.assertEqual(
            [row.item.name for row in page._rendered_rows], ["mpv"]
        )
        self.assertNotIn("resultado", page._results_group.get_description())

        plan = page._build_plan()
        self.assertIsNotNone(plan)
        assert plan is not None
        batch = plan.stages[0]
        self.assertTrue(
            any("mpv" in task.params.get("packages", []) for task in batch.tasks)
        )

        page._aur_switch_row.set_active(True)
        self.assertTrue(page._custom_rows["yay"].get_visible())

        # With nothing selected and an empty field, the results group hides.
        page._custom_rows["mpv"]._check.set_active(False)
        page._search_entry.emit("search-changed")
        self.assertFalse(page._results_group.get_visible())


if __name__ == "__main__":
    unittest.main()
