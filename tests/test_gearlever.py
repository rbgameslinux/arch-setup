"""Testes da lógica de integração estilo Gear Lever (sem Flatpak, sem CLI)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from arch_setup.backend import appimages as appimages_mod
from arch_setup.backend import gearlever as gearlever_mod
from arch_setup.models.catalog import OPTIONAL_PACKAGES


class FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, msg: str) -> None:
        self.lines.append(f"[INFO] {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"[AVISO] {msg}")

    def set_progress(self, frac: float, status: str = "") -> None:
        pass


class GearLeverLogicTests(unittest.TestCase):
    def test_no_flatpak_or_cli_api(self) -> None:
        for name in ("detect", "install_flatpak", "has_flatpak", "GearLeverInstall"):
            self.assertFalse(
                hasattr(gearlever_mod, name), f"API legada ainda presente: {name}"
            )

    def test_native_binary_detection(self) -> None:
        with patch.object(
            gearlever_mod.shutil,
            "which",
            return_value="/usr/bin/gearlever",
        ):
            self.assertEqual(gearlever_mod.native_binary(), "/usr/bin/gearlever")
            self.assertTrue(gearlever_mod.is_available())
        with patch.object(gearlever_mod.shutil, "which", return_value=None):
            self.assertFalse(gearlever_mod.is_available())

    def test_appimages_dir_uses_configured_folder(self) -> None:
        with patch.object(
            gearlever_mod,
            "_configured_folder",
            return_value="/home/rodrigo/appimages",
        ):
            self.assertEqual(
                gearlever_mod.appimages_dir(), Path("/home/rodrigo/appimages")
            )

    def test_appimages_dir_expands_tilde_and_falls_back(self) -> None:
        with patch.object(gearlever_mod, "_configured_folder", return_value="~/AppImages"):
            self.assertEqual(
                gearlever_mod.appimages_dir(), Path.home() / "AppImages"
            )
        with patch.object(gearlever_mod, "_configured_folder", return_value=None):
            self.assertEqual(
                gearlever_mod.appimages_dir(), Path.home() / "AppImages"
            )

    def test_missing_schema_does_not_call_gio_settings(self) -> None:
        """Schema ausente nao pode abortar o processo com GLib-GIO-ERROR."""
        settings_new = "gi.repository.Gio.Settings.new"
        with (
            patch.object(gearlever_mod, "_schema_available", return_value=False),
            patch(settings_new) as mock_new,
        ):
            self.assertIsNone(gearlever_mod._configured_folder())
        mock_new.assert_not_called()

    def test_schema_lookup_is_checked_before_use(self) -> None:
        with patch("gi.repository.Gio.SettingsSchemaSource.get_default") as mock_src:
            mock_src.return_value.lookup.return_value = None
            self.assertFalse(gearlever_mod._schema_available())
            mock_src.return_value.lookup.assert_called_once_with(
                gearlever_mod.SCHEMA, True
            )

    def test_configured_folder_reads_value_when_schema_exists(self) -> None:
        settings = MagicMock()
        settings.get_string.return_value = "/home/usuario/Appimages"
        with (
            patch.object(gearlever_mod, "_schema_available", return_value=True),
            patch("gi.repository.Gio.Settings.new", return_value=settings) as mock_new,
        ):
            self.assertEqual(
                gearlever_mod._configured_folder(), "/home/usuario/Appimages"
            )
        mock_new.assert_called_once_with(gearlever_mod.SCHEMA)

    def test_prepare_destination_creates_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gearlever_mod, "_configured_folder", return_value=tmp):
                dest = gearlever_mod.prepare_destination("Nexus-Launcher.AppImage")
            self.assertEqual(dest, Path(tmp) / "Nexus-Launcher.AppImage")
            self.assertTrue(dest.parent.is_dir())

    def test_exec_line_matches_gearlever(self) -> None:
        line = gearlever_mod.exec_line(Path("/tmp/Meus Apps/App.AppImage"), "--flag")
        self.assertEqual(
            line,
            "env DESKTOPINTEGRATION=1 '/tmp/Meus Apps/App.AppImage' --flag",
        )

    def test_desktop_file_has_integration_env_and_tryexec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(appimages_mod, "APP_DIR", Path(tmp)):
                appimages_mod._write_desktop(
                    "nexus-launcher",
                    "Nexus Launcher",
                    "Game launcher",
                    "Launcher independente de jogos Xodus",
                    Path("/home/rodrigo/appimages/Nexus-Launcher.AppImage"),
                    "nexus-launcher",
                    "Game;Utility;",
                    "nexus-launcher",
                    exec_line=gearlever_mod.exec_line(
                        Path("/home/rodrigo/appimages/Nexus-Launcher.AppImage")
                    ),
                )
            content = (Path(tmp) / "nexus-launcher.desktop").read_text()
        self.assertIn(
            "TryExec=/home/rodrigo/appimages/Nexus-Launcher.AppImage", content
        )
        self.assertIn(
            "Exec=env DESKTOPINTEGRATION=1 "
            "/home/rodrigo/appimages/Nexus-Launcher.AppImage",
            content,
        )
        self.assertNotIn("flatpak", content.lower())


class GearLeverStructureTests(unittest.TestCase):
    def test_filename_normalization(self) -> None:
        self.assertEqual(
            appimages_mod._gearlever_filename("Nexus Launcher.AppImage"),
            "nexus_launcher.appimage",
        )
        self.assertEqual(
            appimages_mod._gearlever_filename("ProtonUp-Qt.AppImage"),
            "protonupqt.appimage",
        )

    def test_unique_target_uses_version_then_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "app.appimage").write_bytes(b"old")
            self.assertEqual(
                appimages_mod._unique_target(folder, "app.appimage", "1.2.3"),
                folder / "app.appimage_1_2_3.appimage",
            )
            (folder / "app.appimage_1_2_3.appimage").write_bytes(b"old")
            self.assertEqual(
                appimages_mod._unique_target(folder, "app.appimage", "1.2.3"),
                folder / "app.appimage_1.appimage",
            )

    def test_full_desktop_content(self) -> None:
        target = Path("/home/usuario/Appimages/nexus_launcher.appimage")
        meta = appimages_mod.AppImageMetadata(
            name="Nexus Launcher",
            comment="Launcher",
            args="--no-sandbox",
            categories="Game;",
            wm_class="Nexus Launcher",
            mime="x-scheme-handler/nexus;",
            version="0.5.1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(appimages_mod, "APP_DIR", Path(tmp)):
                appimages_mod._write_full_desktop(
                    target,
                    "nexus_launcher",
                    meta,
                    name="Nexus Launcher",
                    comment="Launcher",
                    icon="applications-other",
                    version="0.5.1",
                )
            content = (Path(tmp) / "nexus_launcher.desktop").read_text()
        self.assertIn(f"TryExec={target}", content)
        self.assertIn(f"Exec=env DESKTOPINTEGRATION=1 {target} --no-sandbox", content)
        self.assertIn("X-AppImage-Version=0.5.1", content)
        self.assertIn("X-AppImage-Name=Nexus Launcher", content)
        self.assertIn("MimeType=x-scheme-handler/nexus;", content)

    def test_record_installed_preserves_existing_sections(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "gearlever.conf"
            conf.write_text("[app.existente]\nname = Antigo\n", encoding="utf-8")
            target = Path("/home/usuario/Appimages/meu_app.appimage")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                gearlever_mod.record_installed(target, "Meu App", "--flag")
            content = conf.read_text()
        digest = hashlib.md5(str(target).encode()).hexdigest()
        self.assertIn("[app.existente]", content)
        self.assertIn(f"[app.{digest}]", content)
        self.assertIn("default_exec_arguments = --flag", content)

    def test_dropped_appimage_keeps_original_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Meu App.AppImage"
            source.write_bytes(b"fake-appimage")
            folder = Path(tmp) / "appimages"
            folder.mkdir()
            (folder / "meu_app.appimage").write_text("versão antiga", encoding="utf-8")
            meta = appimages_mod.AppImageMetadata(name="Meu App", version="1.0")
            with (
                patch.object(
                    gearlever_mod, "_configured_folder", return_value=str(folder)
                ),
                patch.object(appimages_mod, "_read_metadata", return_value=meta),
                patch.object(appimages_mod, "_write_full_desktop"),
                patch.object(gearlever_mod, "record_installed"),
            ):
                self.assertTrue(
                    appimages_mod.install_appimage_file(
                        source, FakeLogger(), use_gearlever=True
                    )
                )
            self.assertTrue(source.is_file(), "o arquivo arrastado não deve ser apagado")
            self.assertTrue((folder / "meu_app.appimage_1_0.appimage").is_file())


class NewAppImageInstallTests(unittest.TestCase):
    def _meta(self, name: str, version: str) -> appimages_mod.AppImageMetadata:
        return appimages_mod.AppImageMetadata(
            name=name,
            comment="Comentário interno",
            args="--no-sandbox",
            categories="Game;",
            wm_class=name,
            version=version,
        )

    def _install(
        self,
        installer,
        *,
        use_gearlever: bool,
        expected_url: str,
        meta_name: str,
        meta_version: str,
        expected_name: str,
    ) -> None:
        logger = FakeLogger()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "appimages"
            folder.mkdir()
            if meta_name == "Nexus Launcher":
                (folder / "nexus_launcher.appimage").write_text(
                    "versão antiga", encoding="utf-8"
                )
            staging = Path(tmp) / "staging"

            def fake_download(url: str, dest: Path, label: str, log) -> bool:
                self.assertEqual(url, expected_url)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"fake-appimage")
                return True

            with (
                patch.object(appimages_mod, "BIN_DIR", Path(tmp) / "bin"),
                patch.object(appimages_mod, "STAGING_DIR", staging),
                patch.object(
                    gearlever_mod, "_configured_folder", return_value=str(folder)
                ),
                patch.object(appimages_mod, "_download_file", side_effect=fake_download),
                patch.object(
                    appimages_mod,
                    "_read_metadata",
                    return_value=self._meta(meta_name, meta_version),
                ),
                patch.object(appimages_mod, "_write_desktop") as mock_simple,
                patch.object(appimages_mod, "_write_full_desktop") as mock_full,
                patch.object(
                    appimages_mod, "_gearlever_icon", return_value="applications-other"
                ) as mock_icon,
                patch.object(gearlever_mod, "record_installed") as mock_record,
            ):
                self.assertTrue(installer(logger, use_gearlever=use_gearlever))

            if use_gearlever:
                target = folder / expected_name
                self.assertTrue(target.is_file())
                mock_icon.assert_called_once()
                mock_simple.assert_not_called()
                mock_full.assert_called_once()
                self.assertEqual(mock_full.call_args.args[0], target)
                self.assertEqual(mock_record.call_args.args[0], target)
                self.assertEqual(list(staging.iterdir()), [])
            else:
                mock_full.assert_not_called()
                mock_icon.assert_not_called()
                mock_record.assert_not_called()
                mock_simple.assert_called_once()
                self.assertEqual(
                    mock_simple.call_args.args[4].parent, Path(tmp) / "bin"
                )

    def test_gearlever_icon_uses_fresh_extraction(self) -> None:
        logger = FakeLogger()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            squash = root / "squashfs-root"
            icon = squash / "usr/share/icons/hicolor/256x256/apps/heroic.png"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"png")
            icons = root / "icons"

            @contextmanager
            def fake_extracted(appimage: Path, log: object):
                yield squash

            source = root / "Heroic.AppImage"
            source.write_bytes(b"fake-appimage")
            with (
                patch.object(appimages_mod, "_extracted", fake_extracted),
                patch.object(appimages_mod, "_refresh_icon_cache"),
                patch.object(gearlever_mod, "icons_dir", return_value=icons),
            ):
                result = appimages_mod._gearlever_icon(source, "heroic", logger)

            self.assertEqual(result, str(icons / "heroic.png"))
            self.assertEqual((icons / "heroic.png").read_bytes(), b"png")
            self.assertFalse(
                any("Falha ao copiar ícone" in line for line in logger.lines)
            )

    def test_nexus_launcher(self) -> None:
        url = "https://github.com/domsvoboda/nexus-launcher/releases/download/v0.5.1/Nexus-Launcher-0.5.1-x86_64.AppImage"
        with patch.object(appimages_mod, "_github_latest_appimage", return_value=url):
            self._install(
                appimages_mod.install_nexus_launcher,
                use_gearlever=True,
                expected_url=url,
                meta_name="Nexus Launcher",
                meta_version="0.5.1",
                expected_name="nexus_launcher.appimage_0_5_1.appimage",
            )
            self._install(
                appimages_mod.install_nexus_launcher,
                use_gearlever=False,
                expected_url=url,
                meta_name="Nexus Launcher",
                meta_version="0.5.1",
                expected_name="Nexus-Launcher.AppImage",
            )

    def test_recomp_launcher(self) -> None:
        url = "https://github.com/elripalda/RecompLauncher/releases/download/v0.90.0-beta.68/RecompLauncher_0.90.0-beta.68_amd64.AppImage"
        with patch.object(appimages_mod, "_github_latest_appimage", return_value=url):
            self._install(
                appimages_mod.install_recomp_launcher,
                use_gearlever=True,
                expected_url=url,
                meta_name="RecompLauncher",
                meta_version="0.90.0-beta.68",
                expected_name="recomplauncher.appimage",
            )

    def test_epic_launcher(self) -> None:
        self._install(
            appimages_mod.install_epic_games_launcher,
            use_gearlever=True,
            expected_url=appimages_mod.EPIC_APPIMAGE_URL,
            meta_name="Epic Games Launcher",
            meta_version="",
            expected_name="epic_games_launcher.appimage",
        )

    def test_prerelease_appimage_is_found_in_releases_list(self) -> None:
        payload = [
            {
                "tag_name": "v0.90.0-beta.68",
                "assets": [
                    {
                        "browser_download_url": "https://x/RecompLauncher_0.90.0-beta.68_amd64.AppImage"
                    }
                ],
            }
        ]
        with patch.object(
            appimages_mod, "_http_get", return_value=json.dumps(payload).encode()
        ) as mock_get:
            url = appimages_mod._github_latest_appimage(
                "elripalda/RecompLauncher",
                r"RecompLauncher_.*_amd64\.AppImage",
                FakeLogger(),
                include_prereleases=True,
            )
        self.assertEqual(url, payload[0]["assets"][0]["browser_download_url"])
        self.assertIn("/releases", mock_get.call_args.args[0])
        self.assertNotIn("/latest", mock_get.call_args.args[0])

    def test_registry_and_catalog_are_complete(self) -> None:
        for name in (
            "heroic-games-launcher",
            "zapzap",
            "protonup-qt",
            "nexus-launcher",
            "recomp-launcher",
            "epic-games-launcher",
        ):
            self.assertIn(name, appimages_mod.APPIMAGE_INSTALLERS)
        for name in ("nexus-launcher", "recomp-launcher", "epic-games-launcher"):
            items = [p for p in OPTIONAL_PACKAGES if p.name == name]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].source, "appimage")
            self.assertTrue(items[0].appimage_bin)


@unittest.skipUnless(
    bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    "Sem display gráfico disponível",
)
class GearLeverUIPlanTests(unittest.TestCase):
    def test_switch_is_forwarded_to_appimage_installers(self) -> None:
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
        row = next(r for r in page._rows if r.item.name == "nexus-launcher")
        row._check.set_active(True)
        page._gearlever_switch.set_active(True)

        plan = page._build_plan()
        self.assertIsNotNone(plan)
        assert plan is not None
        stage = plan.stages[-1]
        self.assertIn("estilo Gear Lever", stage.title)

        installer = MagicMock(return_value=True)
        with (
            patch.object(
                appimages_mod, "APPIMAGE_INSTALLERS", {"nexus-launcher": installer}
            ),
            patch.object(gearlever_mod, "is_available", return_value=True),
        ):
            stage.fn(FakeLogger())
        installer.assert_called_once()
        self.assertTrue(installer.call_args.kwargs["use_gearlever"])


if __name__ == "__main__":
    unittest.main()
