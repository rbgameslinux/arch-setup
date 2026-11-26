"""Tests for Fase 3 — system tweaks and service blocks."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from arch_setup.backend.privileged import (
    AUDIO_LIMITS_CONTENT,
    DEFAULT_ENV_VARS,
    SYSCTL_CONTENT,
)
from arch_setup.backend.runner import PrivilegedBatch, UserStep
from arch_setup.models.catalog import SERVICE_BLOCKS, SYSTEM_TWEAKS
from arch_setup.ui.pages import services as services_mod
from arch_setup.ui.pages import system as system_mod


class FakeRow:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def get_active(self) -> bool:
        return self._active

    def set_active(self, value: bool) -> None:
        self._active = value

    def set_subtitle(self, value: str) -> None:
        self.subtitle = value


class FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, msg: str) -> None:
        self.lines.append(f"[INFO] {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"[AVISO] {msg}")

    def error(self, msg: str) -> None:
        self.lines.append(f"[ERRO] {msg}")

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def set_progress(self, fraction: float, status: str | None = None) -> None:
        pass

    def run_command(self, cmd: list[str], **_: object) -> int:
        return 0


class SystemDetectionTests(unittest.TestCase):
    def test_every_tweak_has_a_privileged_action(self) -> None:
        self.assertEqual(
            set(system_mod.TWEAK_ACTIONS), {tweak.key for tweak in SYSTEM_TWEAKS}
        )

    def test_env_detection_requires_all_variables(self) -> None:
        full = "\n".join(f"{k}={v}" for k, v in DEFAULT_ENV_VARS.items()) + "\n"
        with patch.object(system_mod, "_read_text", return_value=full):
            self.assertTrue(system_mod.detect_tweak_state("env_vars"))
        with patch.object(system_mod, "_read_text", return_value="MANGOHUD=1\n"):
            self.assertFalse(system_mod.detect_tweak_state("env_vars"))

    def test_sysctl_detection_checks_content(self) -> None:
        with (
            patch.object(system_mod, "Path") as mock_path,
            patch.object(system_mod, "_read_text", return_value=SYSCTL_CONTENT),
        ):
            mock_path.return_value.is_file.return_value = True
            self.assertTrue(system_mod.detect_tweak_state("sysctl"))
        with (
            patch.object(system_mod, "Path") as mock_path,
            patch.object(system_mod, "_read_text", return_value="vm.swappiness=10\n"),
        ):
            mock_path.return_value.is_file.return_value = True
            self.assertFalse(system_mod.detect_tweak_state("sysctl"))

    def test_audio_detection_checks_content_and_group(self) -> None:
        with (
            patch.object(system_mod, "Path") as mock_path,
            patch.object(system_mod, "_read_text", return_value=AUDIO_LIMITS_CONTENT),
            patch.object(system_mod, "user_in_group", return_value=True),
        ):
            mock_path.return_value.is_file.return_value = True
            self.assertTrue(system_mod.detect_tweak_state("audio_limits"))
        with (
            patch.object(system_mod, "Path") as mock_path,
            patch.object(system_mod, "_read_text", return_value=AUDIO_LIMITS_CONTENT),
            patch.object(system_mod, "user_in_group", return_value=False),
        ):
            mock_path.return_value.is_file.return_value = True
            self.assertFalse(system_mod.detect_tweak_state("audio_limits"))

    def test_fstrim_detection_requires_enabled_and_active(self) -> None:
        with (
            patch.object(system_mod, "_systemctl_is_enabled", return_value=True),
            patch.object(system_mod, "_systemctl_is_active", return_value=True),
        ):
            self.assertTrue(system_mod.detect_tweak_state("fstrim"))
        with (
            patch.object(system_mod, "_systemctl_is_enabled", return_value=True),
            patch.object(system_mod, "_systemctl_is_active", return_value=False),
        ):
            self.assertFalse(system_mod.detect_tweak_state("fstrim"))

    def test_systemd_timeout_ignores_commented_line(self) -> None:
        with patch.object(system_mod, "_read_text", return_value="DefaultTimeoutStopSec=10s\n"):
            self.assertTrue(system_mod.detect_tweak_state("systemd_timeout"))
        with patch.object(system_mod, "_read_text", return_value="#DefaultTimeoutStopSec=10s\n"):
            self.assertFalse(system_mod.detect_tweak_state("systemd_timeout"))

    def test_unknown_tweak_is_not_applied(self) -> None:
        self.assertFalse(system_mod.detect_tweak_state("unknown"))

    def test_build_tasks_only_for_enabled_tweaks(self) -> None:
        fake = SimpleNamespace(
            _switch_rows={
                tweak.key: FakeRow(tweak.key == "env_vars") for tweak in SYSTEM_TWEAKS
            },
            _tweaks={t.key: t for t in SYSTEM_TWEAKS},
        )
        tasks = system_mod.SystemPage.build_tasks(fake)
        self.assertEqual([task.action for task in tasks], ["configure_env"])
        self.assertEqual(tasks[0].label, "Variáveis de ambiente AMD/Mesa")


class ServicesTests(unittest.TestCase):
    def test_every_block_has_a_setup_action(self) -> None:
        self.assertEqual(
            set(services_mod.BLOCK_ACTIONS), {block.key for block in SERVICE_BLOCKS}
        )

    def test_is_enabled_rejects_static_units(self) -> None:
        with patch.object(
            services_mod.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="static\n"),
        ):
            self.assertFalse(services_mod.service_is_enabled("smb.service"))
        with patch.object(
            services_mod.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="enabled\n"),
        ):
            self.assertTrue(services_mod.service_is_enabled("smb.service"))

    def test_detect_block_state_checks_packages_services_groups_and_config(self) -> None:
        block = SERVICE_BLOCKS[1]  # Samba
        with (
            patch.object(
                services_mod,
                "_installed_packages",
                return_value=frozenset(block.repo_packages),
            ),
            patch.object(services_mod, "service_is_enabled", return_value=True),
            patch.object(services_mod, "service_is_active", return_value=True),
            patch.object(services_mod, "user_in_group", return_value=True),
            patch.object(services_mod, "Path") as mock_path,
            patch.object(
                services_mod, "_read_text", return_value="usershare path = /var/lib/samba/usershares\n"
            ),
        ):
            mock_path.return_value.is_dir.return_value = True
            self.assertTrue(services_mod.detect_block_state(block))

        with (
            patch.object(
                services_mod,
                "_installed_packages",
                return_value=frozenset(),
            ),
            patch.object(services_mod, "service_is_enabled", return_value=True),
            patch.object(services_mod, "service_is_active", return_value=True),
            patch.object(services_mod, "user_in_group", return_value=True),
        ):
            self.assertFalse(services_mod.detect_block_state(block))

    def test_build_plan_for_samba(self) -> None:
        fake = SimpleNamespace(
            _blocks={block.key: block for block in SERVICE_BLOCKS},
            _switch_rows={
                "virt_manager": FakeRow(False),
                "samba": FakeRow(True),
                "cups": FakeRow(False),
            },
        )
        plan = services_mod.ServicesPage.build_plan(fake)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(len(plan.stages), 2)  # lote root + etapa AUR
        batch = plan.stages[0]
        self.assertIsInstance(batch, PrivilegedBatch)
        actions = [task.action for task in batch.tasks]
        self.assertIn("pacman_install", actions)
        self.assertIn("setup_samba", actions)
        self.assertNotIn("setup_cups", actions)

        step = plan.stages[1]
        self.assertIsInstance(step, UserStep)
        with patch.object(services_mod.aur_mod, "detect_aur_helper", return_value=None):
            logger = FakeLogger()
            step.fn(logger)  # type: ignore[union-attr]
        self.assertTrue(any("fusesmb" in line for line in logger.lines))

    def test_build_plan_returns_none_when_nothing_selected(self) -> None:
        fake = SimpleNamespace(
            _blocks={block.key: block for block in SERVICE_BLOCKS},
            _switch_rows={block.key: FakeRow(False) for block in SERVICE_BLOCKS},
        )
        self.assertIsNone(services_mod.ServicesPage.build_plan(fake))


class ServicesUIRowsTests(unittest.TestCase):
    @unittest.skipUnless(
        bool(
            __import__("os").environ.get("DISPLAY")
            or __import__("os").environ.get("WAYLAND_DISPLAY")
        ),
        "Sem display gráfico disponível",
    )
    def test_blocks_are_collapsible_expanders(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gtk

            from arch_setup.ui.pages.services import ServicesPage
        except Exception:
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        if not Gtk.init_check():
            self.skipTest("Sem display gráfico disponível neste ambiente")
            return

        Adw.init()
        page = ServicesPage()
        self.assertEqual(len(page._expanders), len(SERVICE_BLOCKS))
        self.assertTrue(
            all(isinstance(row, Adw.ExpanderRow) for row in page._expanders.values())
        )

        block = SERVICE_BLOCKS[1]  # Samba
        switch = page._switch_rows[block.key]
        switch.set_active(True)
        plan = page.build_plan()
        self.assertIsNotNone(plan)
        assert plan is not None
        batch = plan.stages[0]
        self.assertIsInstance(batch, PrivilegedBatch)
        self.assertIn("setup_samba", [t.action for t in batch.tasks])


if __name__ == "__main__":
    unittest.main()
