"""Package search backend — official repositories first, AUR optionally after.

The official pacman databases are queried locally with ``pacman -Ss``.  The AUR
is queried through its public RPC only when the user enabled AUR support, and
results are de-duplicated so a repository package always wins over an AUR
package with the same name.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_UA = "arch-setup-gui/2.0 (https://github.com/rbgameslinux/arch-setup)"
_AUR_RPC = "https://aur.archlinux.org/rpc/v5/search/{query}?by=name-desc"
_PACMAN_TIMEOUT = 20
_AUR_TIMEOUT = 20
_MAX_OFFICIAL = 30
_MAX_AUR = 20
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class PackageResult:
    """A package found in a repository or in the AUR."""

    name: str
    description: str
    source: str  # "repo" | "aur"
    repository: str = ""


def _warn(logger: Any | None, message: str) -> None:
    if logger is not None and hasattr(logger, "warn"):
        logger.warn(message)


def _valid_query(query: str) -> str:
    cleaned = query.strip()
    if not cleaned or len(cleaned) > 100:
        return ""
    return cleaned


def parse_pacman_search(text: str) -> list[PackageResult]:
    """Parse ``pacman -Ss`` output into results (header + indented description)."""
    lines = text.splitlines()
    results: list[PackageResult] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        if not line or line[0].isspace():
            continue
        first = line.split(maxsplit=1)[0]
        if "/" not in first:
            continue
        repository, name = first.split("/", 1)
        if not repository or not _NAME_RE.fullmatch(name):
            continue

        description = ""
        if index + 1 < len(lines) and lines[index + 1].startswith(("    ", "\t")):
            description = lines[index + 1].strip()
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            PackageResult(
                name=name,
                description=description,
                source="repo",
                repository=repository,
            )
        )
        if len(results) >= _MAX_OFFICIAL:
            break

    return results


def _rank_by_query(
    results: list[PackageResult], query: str
) -> list[PackageResult]:
    """Exact name first, then prefix matches, then description matches."""
    term = query.casefold()

    def sort_key(result: PackageResult) -> tuple[int, str]:
        name = result.name.casefold()
        if name == term:
            return (0, name)
        if name.startswith(term):
            return (1, name)
        return (2, name)

    return sorted(results, key=sort_key)


def search_official_packages(query: str, logger: Any | None = None) -> list[PackageResult]:
    """Search the synchronised official repositories via ``pacman -Ss``."""
    cleaned = _valid_query(query)
    if not cleaned:
        return []
    try:
        proc = subprocess.run(
            ["pacman", "-Ss", "--", cleaned],
            capture_output=True,
            text=True,
            check=False,
            timeout=_PACMAN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _warn(logger, f"Busca nos repositórios indisponível: {exc}")
        return []
    if proc.returncode not in (0, 1):
        _warn(logger, f"pacman -Ss falhou (código {proc.returncode})")
        return []
    return _rank_by_query(parse_pacman_search(proc.stdout), cleaned)


def search_aur_packages(query: str, logger: Any | None = None) -> list[PackageResult]:
    """Search the AUR through its RPC. Returns [] on any network/JSON error."""
    cleaned = _valid_query(query)
    if not cleaned:
        return []
    url = _AUR_RPC.format(query=urllib.parse.quote(cleaned, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_AUR_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        _warn(logger, f"Busca no AUR indisponível: {exc}")
        return []

    if not isinstance(payload, dict) or payload.get("type") != "search":
        _warn(logger, "Resposta inesperada da API do AUR.")
        return []

    results: list[PackageResult] = []
    for item in payload.get("results", [])[:_MAX_AUR]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "")
        if not _NAME_RE.fullmatch(name):
            continue
        description = _TAG_RE.sub("", str(item.get("Description") or "")).strip()
        if item.get("OutOfDate"):
            description = f"{description} (desatualizado)".strip()
        results.append(
            PackageResult(name=name, description=description, source="aur")
        )
    return results


def search_packages(
    query: str, *, include_aur: bool = False, logger: Any | None = None
) -> list[PackageResult]:
    """Return official results first, then non-duplicated AUR results."""
    results = search_official_packages(query, logger=logger)
    if not include_aur:
        return results

    seen = {result.name.casefold() for result in results}
    aur_results = _rank_by_query(
        search_aur_packages(query, logger=logger), _valid_query(query)
    )
    for result in aur_results:
        key = result.name.casefold()
        if key in seen:
            continue  # repositório oficial sempre tem prioridade
        seen.add(key)
        results.append(result)
    return results
