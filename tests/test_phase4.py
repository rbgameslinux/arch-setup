"""Tests for Fase 4 — fixes (ZapZap/Resolve) and wallpapers backend."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arch_setup.backend import fixes as fixes_mod
from arch_setup.backend import wallpapers as wallpapers_mod


class FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.progress: list[float] = []

    def info(self, msg: str) -> None:
        self.lines.append(f"[INFO] {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"[AVISO] {msg}")

    def error(self, msg: str) -> None:
        self.lines.append(f"[ERRO] {msg}")

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def set_progress(self, fraction: float, status: str | None = None) -> None:
        self.progress.append(fraction)

    def run_command(self, cmd: list[str], **_: object) -> int:
        return 0


class FakeResponse:
    """Minimal urlopen() response with chunked reads."""

    def __init__(self, data: bytes) -> None:
        self._data = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self._data.close()

    def read(self, size: int = -1) -> bytes:
        return self._data.read(size)


def _make_targz() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        payload = b"fake wallpaper"
        info = tarfile.TarInfo("Rbgames-Wallpapers/wallpaper.jpg")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class FixesBackendTests(unittest.TestCase):
    def test_wrapper_template_has_valid_sh_syntax(self) -> None:
        proc = subprocess.run(
            ["sh", "-n"],
            input=fixes_mod.WRAPPER_TEMPLATE,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_zapzap_apply_and_revert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "pipewire-pulse.conf.d"
            conf_file = conf_dir / "99-block-source-volume.conf"
            home = root / "home"
            with (
                patch.object(fixes_mod, "PIPEWIRE_CONF_DIR", conf_dir),
                patch.object(fixes_mod, "PIPEWIRE_CONF_FILE", conf_file),
                patch("pathlib.Path.home", return_value=home),
                patch.object(
                    fixes_mod.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
            ):
                logger = FakeLogger()
                self.assertTrue(fixes_mod.apply_zapzap_fix(logger))
                self.assertTrue(conf_file.is_file())
                self.assertIn("block-source-volume", conf_file.read_text())
                self.assertTrue(
                    (home / "backup-config" / "99-block-source-volume.conf").is_file()
                )
                self.assertTrue(fixes_mod.zapzap_fix_is_applied())

                logger = FakeLogger()
                self.assertTrue(fixes_mod.revert_zapzap_fix(logger))
                self.assertFalse(conf_file.exists())
                self.assertFalse(fixes_mod.zapzap_fix_is_applied())

    def test_get_niri_outputs_parses_quoted_names(self) -> None:
        stdout = (
            'Output "DP-1" (connected: yes, current mode: 2560x1440)\n'
            'Output "HDMI-A-1" (connected: no)\n'
        )
        with patch.object(
            fixes_mod.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=stdout),
        ):
            self.assertEqual(fixes_mod.get_niri_outputs(), ["DP-1", "HDMI-A-1"])

    def test_get_niri_outputs_fallback(self) -> None:
        with patch.object(fixes_mod.subprocess, "run", side_effect=OSError("no niri")):
            self.assertEqual(fixes_mod.get_niri_outputs(), ["DP-1"])

    def test_resolve_apply_creates_wrapper_desktop_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolve_bin = root / "resolve-bin"
            resolve_bin.write_text("")
            resolve_bin.chmod(0o755)
            wrapper = root / ".local" / "bin" / "resolve"
            desktop_dir = root / ".local" / "share" / "applications"
            desktop_file = desktop_dir / "com.blackmagicdesign.resolve.desktop"
            niri_conf = root / ".config" / "niri" / "config.kdl"
            niri_conf.parent.mkdir(parents=True)
            niri_conf.write_text("// config\n")
            with (
                patch.object(fixes_mod, "RESOLVE_BIN", resolve_bin),
                patch.object(fixes_mod, "WRAPPER_PATH", wrapper),
                patch.object(fixes_mod, "DESKTOP_DIR", desktop_dir),
                patch.object(fixes_mod, "DESKTOP_FILE", desktop_file),
                patch.object(fixes_mod, "NIRI_CONFIG", niri_conf),
                patch.object(
                    fixes_mod.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
            ):
                logger = FakeLogger()
                self.assertTrue(fixes_mod.apply_resolve_fix("DP-2", logger))
                self.assertTrue(wrapper.is_file())
                self.assertIn("QT_QPA_PLATFORM=xcb", wrapper.read_text())
                self.assertTrue(wrapper.stat().st_mode & 0o111)
                self.assertIn(str(wrapper), desktop_file.read_text())
                self.assertIn('open-on-output "DP-2"', niri_conf.read_text())
                self.assertTrue(fixes_mod.resolve_fix_is_applied())

                self.assertTrue(fixes_mod.revert_resolve_fix(FakeLogger()))
                self.assertFalse(wrapper.exists())

    def test_resolve_apply_updates_selected_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolve_bin = root / "resolve-bin"
            resolve_bin.write_text("")
            resolve_bin.chmod(0o755)
            wrapper = root / "resolve"
            desktop = root / "resolve.desktop"
            niri_conf = root / "config.kdl"
            niri_conf.write_text(
                'window-rule {\n    match app-id="resolve"\n'
                '    open-on-output "DP-1"\n}\n'
            )
            with (
                patch.object(fixes_mod, "RESOLVE_BIN", resolve_bin),
                patch.object(fixes_mod, "WRAPPER_PATH", wrapper),
                patch.object(fixes_mod, "DESKTOP_DIR", desktop.parent),
                patch.object(fixes_mod, "DESKTOP_FILE", desktop),
                patch.object(fixes_mod, "NIRI_CONFIG", niri_conf),
                patch.object(
                    fixes_mod.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
            ):
                self.assertTrue(fixes_mod.apply_resolve_fix("DP-2", FakeLogger()))
                text = niri_conf.read_text()
                self.assertIn('open-on-output "DP-2"', text)
                self.assertNotIn('open-on-output "DP-1"', text)

    def test_resolve_apply_requires_resolve_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "resolve"
            with patch.object(fixes_mod, "RESOLVE_BIN", missing):
                logger = FakeLogger()
                self.assertFalse(fixes_mod.apply_resolve_fix("DP-1", logger))
                self.assertTrue(any("não encontrado" in line for line in logger.lines))


class WallpapersBackendTests(unittest.TestCase):
    def test_install_from_targz(self) -> None:
        data = _make_targz()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tar_path = root / "wallpapers.tar.gz"
            extract_dir = root / "extract"
            dest_dir = root / "Wallpapers"
            with (
                patch.object(wallpapers_mod, "TMP_TAR", tar_path),
                patch.object(wallpapers_mod, "TMP_EXTRACT", extract_dir),
                patch.object(wallpapers_mod, "DEST_DIR", dest_dir),
                patch.object(
                    wallpapers_mod.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(data),
                ),
            ):
                logger = FakeLogger()
                self.assertTrue(wallpapers_mod.download_and_install_wallpapers(logger))
                self.assertTrue((dest_dir / "wallpaper.jpg").is_file())
                self.assertEqual(logger.progress[-1], 1.0)
                self.assertFalse(tar_path.exists())
                self.assertFalse(extract_dir.exists())
                with patch.object(wallpapers_mod, "DEST_DIR", dest_dir):
                    self.assertTrue(wallpapers_mod.wallpapers_installed())

    def test_download_retries_three_times(self) -> None:
        data = _make_targz()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(wallpapers_mod, "TMP_TAR", root / "wallpapers.tar.gz"),
                patch.object(wallpapers_mod, "TMP_EXTRACT", root / "extract"),
                patch.object(wallpapers_mod, "DEST_DIR", root / "Wallpapers"),
                patch.object(
                    wallpapers_mod.urllib.request,
                    "urlopen",
                    side_effect=[OSError("timeout"), OSError("timeout"), FakeResponse(data)],
                ) as mock_urlopen,
            ):
                logger = FakeLogger()
                self.assertTrue(wallpapers_mod.download_and_install_wallpapers(logger))
                self.assertEqual(mock_urlopen.call_count, 3)
                self.assertTrue(any("Tentativa" in line for line in logger.lines))

    def test_truncated_gzip_is_rejected(self) -> None:
        data = _make_targz()[:-12]
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = Path(tmp) / "wallpapers.tar.gz"
            with (
                patch.object(wallpapers_mod, "TMP_TAR", tar_path),
                patch.object(
                    wallpapers_mod.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(data),
                ),
            ):
                logger = FakeLogger()
                self.assertFalse(wallpapers_mod.download_and_install_wallpapers(logger))
                self.assertTrue(any("corrompido" in line for line in logger.lines))
                self.assertFalse(tar_path.exists())

    def test_corrupt_download_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = Path(tmp) / "wallpapers.tar.gz"
            with (
                patch.object(wallpapers_mod, "TMP_TAR", tar_path),
                patch.object(
                    wallpapers_mod.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(b"<html>quota exceeded</html>"),
                ),
            ):
                logger = FakeLogger()
                self.assertFalse(wallpapers_mod.download_and_install_wallpapers(logger))
                self.assertFalse(tar_path.exists())
                self.assertTrue(any("corrompido" in line for line in logger.lines))

    def test_empty_destination_is_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(wallpapers_mod, "DEST_DIR", Path(tmp)):
                self.assertFalse(wallpapers_mod.wallpapers_installed())


if __name__ == "__main__":
    unittest.main()
