"""Tests for Fase 5 — desktop entry, documentation and privacy guardrails."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Phase5Tests(unittest.TestCase):
    def test_desktop_entry_installer_has_valid_bash_syntax(self) -> None:
        script = ROOT / "scripts" / "install-desktop-entry.sh"
        self.assertTrue(script.is_file())
        proc = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_desktop_entry_runs_without_terminal(self) -> None:
        content = (ROOT / "scripts" / "install-desktop-entry.sh").read_text()
        self.assertIn("Terminal=false", content)
        self.assertIn('Exec="$RUNNER"', content)
        self.assertIn("io.github.rbgameslinux.ArchSetup.desktop", content)

    def test_readme_documents_app_and_usage(self) -> None:
        readme = (ROOT / "README.md").read_text()
        for expected in (
            "run.sh",
            "pkexec",
            "## Como usar",
            "## O que ele faz",
            "83 testes automatizados",
            "GNU General Public License",
        ):
            self.assertIn(expected, readme)

    def test_private_conversation_log_is_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn("conversa.log", gitignore)
        self.assertIn("*.log", gitignore)


if __name__ == "__main__":
    unittest.main()
