"""Unit and integration tests for Fase 1 (Fundação)."""

from __future__ import annotations

import getpass
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gi.repository import GLib

from arch_setup.backend import privileged
from arch_setup.backend.runner import (
    CommandRunner,
    ExecutionPlan,
    PrivilegedBatch,
    PrivilegedTask,
    RunnerCallbacks,
    TaskLogger,
    UserStep,
)
from arch_setup.models import catalog


class CatalogTests(unittest.TestCase):
    def test_catalog_counts_and_uniqueness(self) -> None:
        self.assertEqual(len(catalog.BASE_PACKAGES), len(set(catalog.BASE_PACKAGES)))
        self.assertIn("base-devel", catalog.BASE_PACKAGES)
        self.assertIn("git", catalog.BASE_PACKAGES)
        self.assertEqual(len(catalog.OPTIONAL_PACKAGES), 35)
        self.assertEqual(len(catalog.ICON_FONT_PACKAGES), 5)

        obs = next(p for p in catalog.OPTIONAL_PACKAGES if p.name == "obs-studio")
        self.assertIn("obs-studio-plugin-browser", obs.extra_packages)

    def test_environment_summary_keys(self) -> None:
        summary = catalog.detect_environment_summary()
        for key in (
            "cpu_cores",
            "aur_helper",
            "total_installed_packages",
            "base_installed_count",
            "base_total_count",
            "has_niri",
            "has_resolve",
            "has_resolve_wrapper",
            "has_zapzap_fix",
            "has_wallpapers",
        ):
            self.assertIn(key, summary)


class PrivilegedTests(unittest.TestCase):
    def test_validate_packages_rejects_flags_and_injection(self) -> None:
        self.assertEqual(
            privileged.validate_packages(["git", "obs-studio", "lib32-mesa"]),
            ["git", "obs-studio", "lib32-mesa"],
        )
        for bad in ([], ["-rf"], ["git;rm"], ["pkg name"], "git"):
            with self.assertRaises(privileged.PrivilegedError):
                privileged.validate_packages(bad)

    def test_resolve_target_user_rejects_root(self) -> None:
        with self.assertRaises(privileged.PrivilegedError):
            privileged.resolve_target_user("root")
        with self.assertRaises(privileged.PrivilegedError):
            privileged.resolve_target_user("nonexistent_user_xyz_123")
        self.assertEqual(
            privileged.resolve_target_user(getpass.getuser()),
            getpass.getuser(),
        )

    def test_execute_manifest_dry_run_all_actions(self) -> None:
        manifest = {
            "target_user": getpass.getuser(),
            "tasks": [
                {"action": "noop_check", "label": "Check", "params": {"message": "ok"}},
                {"action": "pacman_install", "label": "Pacman", "params": {"packages": ["git"]}},
                {"action": "configure_makepkg_jobs", "label": "Makepkg", "params": {"cores": 4}},
                {"action": "configure_env", "label": "Env"},
                {"action": "configure_sysctl", "label": "Sysctl"},
                {"action": "configure_audio_limits", "label": "Audio"},
                {"action": "enable_fstrim", "label": "TRIM"},
                {"action": "configure_systemd_timeout", "label": "Timeout"},
                {"action": "configure_grub_quiet", "label": "GRUB"},
                {"action": "setup_virt_manager", "label": "Virt"},
                {"action": "setup_samba", "label": "Samba"},
                {"action": "setup_cups", "label": "CUPS"},
            ],
        }
        privileged.execute_manifest(manifest, dry_run=True)

    def test_execute_manifest_rejects_unknown_action(self) -> None:
        with self.assertRaises(privileged.PrivilegedError):
            privileged.execute_manifest(
                {"target_user": getpass.getuser(), "tasks": [{"action": "rm_rf"}]}
            )

    def test_cli_dry_run_and_non_root_guard(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(
                {
                    "target_user": getpass.getuser(),
                    "tasks": [{"action": "noop_check", "label": "CLI test"}],
                },
                tf,
            )
            tf_path = Path(tf.name)

        try:
            ok_proc = subprocess.run(
                [sys.executable, "-m", "arch_setup.backend.privileged", "--dry-run", str(tf_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("@@STEP 1 1 CLI test", ok_proc.stdout)

            denied_proc = subprocess.run(
                [sys.executable, "-m", "arch_setup.backend.privileged", str(tf_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(denied_proc.returncode, 1)
            self.assertIn("pkexec", denied_proc.stdout)
        finally:
            tf_path.unlink(missing_ok=True)


class RunnerTests(unittest.TestCase):
    def _run_plan_with_mainloop(
        self, plan: ExecutionPlan, *, continue_on_error: bool = False
    ) -> tuple[bool, str, list[str], list[float], Path]:
        loop = GLib.MainLoop()
        logs: list[str] = []
        progress_values: list[float] = []
        result: dict[str, object] = {}

        def on_log(line: str, _level: str) -> bool:
            logs.append(line)
            return GLib.SOURCE_REMOVE

        def on_progress(frac: float, _status: str) -> bool:
            progress_values.append(frac)
            return GLib.SOURCE_REMOVE

        def on_error_prompt(_title: str, _err: str, respond: object) -> bool:
            respond(continue_on_error)  # type: ignore[operator]
            return GLib.SOURCE_REMOVE

        def on_finished(success: bool, summary: str, log_path: Path) -> bool:
            result["success"] = success
            result["summary"] = summary
            result["log_path"] = log_path
            loop.quit()
            return GLib.SOURCE_REMOVE

        runner = CommandRunner()
        runner.start(
            plan,
            RunnerCallbacks(
                on_log=on_log,
                on_progress=on_progress,
                on_error_prompt=on_error_prompt,
                on_finished=on_finished,
            ),
        )
        GLib.timeout_add_seconds(10, loop.quit)
        loop.run()

        self.assertIn("success", result, "Runner timed out before finishing")
        return (
            bool(result["success"]),
            str(result["summary"]),
            logs,
            progress_values,
            result["log_path"],  # type: ignore[return-value]
        )

    def test_runner_executes_dry_run_and_user_step(self) -> None:
        def _user_fn(logger: TaskLogger) -> None:
            logger.info("hello from user step")
            rc = logger.run_command([sys.executable, "-c", "print('subproc ok')"])
            self.assertEqual(rc, 0)

        plan = ExecutionPlan(
            title="Test plan",
            stages=[
                PrivilegedBatch(
                    title="Batch",
                    dry_run=True,
                    tasks=[
                        PrivilegedTask("noop_check", "Step 1", {"message": "m1"}),
                        PrivilegedTask("configure_env", "Step 2"),
                    ],
                ),
                UserStep(title="User stage", fn=_user_fn),
            ],
        )

        success, _summary, logs, progress, log_path = self._run_plan_with_mainloop(plan)
        try:
            self.assertTrue(success)
            self.assertTrue(any("subproc ok" in line for line in logs))
            self.assertTrue(any("Lote privilegiado concluído" in line for line in logs))
            self.assertAlmostEqual(progress[-1], 1.0)
            self.assertTrue(log_path.is_file())
        finally:
            log_path.unlink(missing_ok=True)

    def test_runner_abort_on_error_prompt(self) -> None:
        ran_second = {"value": False}

        def _failing(_logger: TaskLogger) -> None:
            raise RuntimeError("boom")

        def _second(_logger: TaskLogger) -> None:
            ran_second["value"] = True

        plan = ExecutionPlan(
            title="Abort test",
            stages=[
                UserStep(title="Failing step", fn=_failing),
                UserStep(title="Second step", fn=_second),
            ],
        )

        success, summary, _logs, _progress, log_path = self._run_plan_with_mainloop(
            plan, continue_on_error=False
        )
        try:
            self.assertFalse(success)
            self.assertIn("Abortado", summary)
            self.assertFalse(ran_second["value"])
        finally:
            log_path.unlink(missing_ok=True)


class UISmokeTests(unittest.TestCase):
    def test_ui_imports_and_window_instantiation(self) -> None:
        from gi.repository import Adw, Gtk

        from arch_setup.main import ArchSetupApplication
        from arch_setup.ui.execution_dialog import ExecutionDialog
        from arch_setup.ui.window import ArchSetupWindow

        if not Gtk.init_check():
            self.skipTest("Sem display gráfico disponível neste ambiente")

        Adw.init()
        app = ArchSetupApplication()
        win = ArchSetupWindow(application=app)
        dlg = ExecutionDialog(ExecutionPlan(title="Smoke", stages=[]))
        self.assertIsNotNone(win)
        self.assertIsNotNone(dlg)
        win.destroy()


if __name__ == "__main__":
    unittest.main()
