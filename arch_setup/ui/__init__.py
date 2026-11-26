"""GTK4 / Libadwaita user interface."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib  # noqa: E402


def escape_label(text: str) -> str:
    """Escape text for Adw titles/descriptions, which parse Pango markup."""
    return GLib.markup_escape_text(text)
