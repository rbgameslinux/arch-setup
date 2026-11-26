"""Tests for package search: repo-first ordering and optional AUR results."""

from __future__ import annotations

import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from arch_setup.backend import search as search_mod


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._data = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self._data.close()

    def read(self) -> bytes:
        return self._data.read()


PACMAN_OUTPUT = """core/bash 5.3.20-1 [instalado]
    The GNU Bourne Again shell
extra/bash-completion 2.18.0-1
    Programmable completion for the bash shell
extra/bash 5.0-1
    Duplicado que deve ser ignorado
"""


class PackageSearchTests(unittest.TestCase):
    def test_parse_pacman_output(self) -> None:
        results = search_mod.parse_pacman_search(PACMAN_OUTPUT)
        self.assertEqual([r.name for r in results], ["bash", "bash-completion"])
        self.assertEqual(results[0].repository, "core")
        self.assertEqual(results[0].source, "repo")
        self.assertEqual(results[0].description, "The GNU Bourne Again shell")
        self.assertEqual(results[1].repository, "extra")

    def test_official_search_calls_pacman_with_terminator(self) -> None:
        with patch.object(
            search_mod.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=PACMAN_OUTPUT),
        ) as mock_run:
            results = search_mod.search_official_packages("bash")
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_run.call_args.args[0], ["pacman", "-Ss", "--", "bash"])

    def test_exact_name_is_ranked_before_description_matches(self) -> None:
        output = """extra/foo-utils 1.0-1
    Ferramenta relacionada a foo
core/foo 2.0-1
    O pacote foo propriamente dito
"""
        with patch.object(
            search_mod.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=output),
        ):
            results = search_mod.search_official_packages("foo")
        self.assertEqual([r.name for r in results], ["foo", "foo-utils"])

    def test_official_search_handles_missing_pacman(self) -> None:
        logger = FakeLogger()
        with patch.object(search_mod.subprocess, "run", side_effect=OSError("no pacman")):
            self.assertEqual(
                search_mod.search_official_packages("bash", logger=logger), []
            )
        self.assertTrue(any("indisponível" in w for w in logger.warnings))

    def test_aur_rpc_is_parsed(self) -> None:
        payload = {
            "type": "search",
            "results": [
                {
                    "Name": "visual-studio-code-bin",
                    "Description": "Editor <b>de código</b>",
                    "OutOfDate": 1700000000,
                },
                {"Name": "not valid!", "Description": "ignorado"},
            ],
        }
        with patch.object(
            search_mod.urllib.request,
            "urlopen",
            return_value=FakeResponse(payload),
        ) as mock_urlopen:
            results = search_mod.search_aur_packages("visual Studio")
        self.assertEqual([r.name for r in results], ["visual-studio-code-bin"])
        self.assertIn("Editor de código", results[0].description)
        self.assertIn("desatualizado", results[0].description)
        self.assertEqual(results[0].source, "aur")
        self.assertIn("by=name-desc", mock_urlopen.call_args.args[0].full_url)

    def test_aur_search_failure_is_not_fatal(self) -> None:
        logger = FakeLogger()
        with patch.object(
            search_mod.urllib.request, "urlopen", side_effect=OSError("offline")
        ):
            self.assertEqual(search_mod.search_aur_packages("foo", logger=logger), [])
        self.assertTrue(any("AUR" in w for w in logger.warnings))

    def test_repo_results_come_first_and_win_over_aur(self) -> None:
        official = [
            search_mod.PackageResult("mpv", "Reprodutor repo", "repo", "extra")
        ]
        aur = [
            search_mod.PackageResult("mpv", "Mesmo nome no AUR", "aur"),
            search_mod.PackageResult("mpv-git", "Versão git", "aur"),
        ]
        with (
            patch.object(search_mod, "search_official_packages", return_value=official),
            patch.object(search_mod, "search_aur_packages", return_value=aur) as mock_aur,
        ):
            self.assertEqual(
                search_mod.search_packages("mpv", include_aur=False), official
            )
            mock_aur.assert_not_called()

            results = search_mod.search_packages("mpv", include_aur=True)
        self.assertEqual([r.name for r in results], ["mpv", "mpv-git"])
        self.assertEqual([r.source for r in results], ["repo", "aur"])
        self.assertEqual(results[0].description, "Reprodutor repo")

    def test_empty_query_skips_network(self) -> None:
        with (
            patch.object(search_mod.subprocess, "run") as mock_run,
            patch.object(search_mod.urllib.request, "urlopen") as mock_urlopen,
        ):
            self.assertEqual(search_mod.search_packages("   ", include_aur=True), [])
        mock_run.assert_not_called()
        mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
