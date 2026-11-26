"""Sistema page — Fase 3: individual switches for each system tweak."""

from __future__ import annotations

import getpass
import re
import subprocess
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend.privileged import (
    AUDIO_LIMITS_CONTENT,
    DEFAULT_ENV_VARS,
    SYSCTL_CONTENT,
    user_in_group,
)
from arch_setup.backend.runner import ExecutionPlan, PrivilegedBatch, PrivilegedTask
from arch_setup.models.catalog import SYSTEM_TWEAKS, TweakItem
from arch_setup.ui.execution_dialog import ExecutionDialog
from arch_setup.ui.pages import escape_label

TWEAK_ACTIONS: dict[str, str] = {
    "env_vars": "configure_env",
    "sysctl": "configure_sysctl",
    "audio_limits": "configure_audio_limits",
    "fstrim": "enable_fstrim",
    "systemd_timeout": "configure_systemd_timeout",
}


def _read_text(path: Path) -> str:
    """Read a text file, returning an empty string when absent/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _systemctl_state(service: str, verb: str, expected: str) -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", verb, service],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return proc.returncode == 0 and proc.stdout.strip() == expected
    except (OSError, subprocess.TimeoutExpired):
        return False


def _systemctl_is_enabled(service: str) -> bool:
    return _systemctl_state(service, "is-enabled", "enabled")


def _systemctl_is_active(service: str) -> bool:
    return _systemctl_state(service, "is-active", "active")


def _expected_lines(content: str) -> set[str]:
    return {
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def detect_tweak_state(key: str) -> bool:
    """Return True when the tweak appears to be already applied on this system."""
    try:
        if key == "env_vars":
            lines = _read_text(Path("/etc/environment")).splitlines()
            return all(
                any(line.strip() == f"{name}={value}" for line in lines)
                for name, value in DEFAULT_ENV_VARS.items()
            )
        if key == "sysctl":
            path = Path("/etc/sysctl.d/99-performance.conf")
            expected = _expected_lines(SYSCTL_CONTENT)
            return path.is_file() and expected.issubset(
                _expected_lines(_read_text(path))
            )
        if key == "audio_limits":
            path = Path("/etc/security/limits.d/99-audio.conf")
            expected = _expected_lines(AUDIO_LIMITS_CONTENT)
            return (
                path.is_file()
                and expected.issubset(_expected_lines(_read_text(path)))
                and user_in_group(getpass.getuser(), "audio")
            )
        if key == "fstrim":
            return _systemctl_is_enabled("fstrim.timer") and _systemctl_is_active(
                "fstrim.timer"
            )
        if key == "systemd_timeout":
            return bool(
                re.search(
                    r"^DefaultTimeoutStopSec=10s\s*$",
                    _read_text(Path("/etc/systemd/system.conf")),
                    re.MULTILINE,
                )
            )
    except (OSError, ValueError):
        return False
    return False


class SystemPage(Adw.PreferencesPage):
    """System configuration page with individual tweak switches."""

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Sistema")
        self.set_name("system")
        self.set_icon_name("preferences-system-symbolic")

        self._tweaks: dict[str, TweakItem] = {item.key: item for item in SYSTEM_TWEAKS}
        self._switch_rows: dict[str, Adw.SwitchRow] = {}
        self._build_ui()
        GLib.idle_add(self._refresh_state)

    # ─────────────────────────── UI construction ────────────────────────────

    def _build_ui(self) -> None:
        tweaks_group = Adw.PreferencesGroup(
            title="Ajustes do sistema",
            description=(
                "Cada tweak é aplicado de forma independente. "
                "Ajustes já presentes aparecem desmarcados."
            ),
        )
        for tweak in SYSTEM_TWEAKS:
            row = Adw.SwitchRow(
                title=escape_label(tweak.title),
                subtitle=escape_label(tweak.description),
            )
            row.set_active(False)
            self._switch_rows[tweak.key] = row
            tweaks_group.add(row)
        self.add(tweaks_group)

        action_group = Adw.PreferencesGroup()
        apply_row = Adw.ActionRow(
            title="Aplicar configurações habilitadas",
            subtitle="Apenas os switches ligados serão executados (uma senha pkexec)",
        )
        self._apply_btn = Gtk.Button(label="Aplicar")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_valign(Gtk.Align.CENTER)
        self._apply_btn.connect("clicked", self._on_apply)
        apply_row.add_suffix(self._apply_btn)
        action_group.add(apply_row)
        self.add(action_group)

    # ─────────────────────────── State helpers ──────────────────────────────

    def _refresh_state(self) -> bool:
        for key, row in self._switch_rows.items():
            tweak = self._tweaks[key]
            if detect_tweak_state(key):
                row.set_active(False)
                row.set_subtitle(
                    escape_label(f"✓ Já aplicado  •  {tweak.description}")
                )
            else:
                row.set_active(False)
                row.set_subtitle(escape_label(tweak.description))
        return GLib.SOURCE_REMOVE

    def build_tasks(self) -> list[PrivilegedTask]:
        """Build the privileged tasks for the enabled tweaks."""
        tasks: list[PrivilegedTask] = []
        for key, action in TWEAK_ACTIONS.items():
            if not self._switch_rows[key].get_active():
                continue
            tasks.append(PrivilegedTask(action, self._tweaks[key].title))
        return tasks

    # ────────────────────────────── Actions ─────────────────────────────────

    def _on_apply(self, _button: Gtk.Button) -> None:
        tasks = self.build_tasks()
        if not tasks:
            alert = Adw.AlertDialog.new(
                "Nada selecionado",
                "Habilite ao menos um ajuste antes de aplicar.",
            )
            alert.add_response("ok", "OK")
            alert.present(self.get_root())
            return

        plan = ExecutionPlan(
            title="Configurações do Sistema",
            stages=[PrivilegedBatch(title="Ajustes do sistema via pkexec", tasks=tasks)],
        )
        dialog = ExecutionDialog(plan)
        dialog.start(self.get_root(), on_complete=lambda _ok: self._refresh_state())
