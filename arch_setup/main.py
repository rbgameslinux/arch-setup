"""GTK4 / Libadwaita application entry point."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from arch_setup import APP_ID, APP_NAME, APP_VERSION
from arch_setup.ui.window import ArchSetupWindow


class ArchSetupApplication(Adw.Application):
    """Main Adw.Application managing window lifecycle and global actions."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def do_activate(self) -> None:
        win = self.get_active_window()
        if win is None:
            win = ArchSetupWindow(application=self)
        win.present()

    def _on_about(self, *_args: object) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            version=APP_VERSION,
            developer_name="rbgameslinux",
            website="https://github.com/rbgameslinux/arch-setup",
            comments="Interface gráfica GTK4/Libadwaita para pós-formatação e ajustes no Arch Linux.",
            application_icon="system-software-install-symbolic",
        )
        dialog.present(self.get_active_window())


def main(argv: list[str] | None = None) -> int:
    app = ArchSetupApplication()
    return app.run(argv)
