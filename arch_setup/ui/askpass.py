#!/usr/bin/env python3
"""SUDO_ASKPASS helper gráfico para operações AUR (paru/yay/makepkg).

Executado via SUDO_ASKPASS=.../askpass.py quando o helper AUR precisa de
senha para chamar sudo. Exibe um Adw.Dialog minimal de senha e imprime
o resultado no stdout para que o sudo o capture.

Uso (definido pelo backend/aur.py antes de chamar o helper AUR):
    export SUDO_ASKPASS=/path/to/arch_setup/ui/askpass.py
    sudo -A ...
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402


def run_askpass(prompt: str) -> int:
    """Display a password dialog and print the entered password to stdout."""
    app = Adw.Application(application_id="io.github.rbgameslinux.ArchSetup.AskPass")
    result_holder: dict[str, object] = {"password": None, "exit_code": 1}

    def on_activate(_application: Adw.Application) -> None:
        # Build a lightweight dialog — no main window needed
        dialog = Adw.Dialog()
        dialog.set_title("Autenticação necessária")
        dialog.set_content_width(400)
        dialog.set_content_height(-1)
        dialog.set_can_close(False)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Icon + prompt
        icon = Gtk.Image.new_from_icon_name("dialog-password-symbolic")
        icon.set_pixel_size(48)
        content.append(icon)

        lbl = Gtk.Label(label=prompt or "Senha sudo:")
        lbl.set_wrap(True)
        lbl.set_xalign(0.5)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.add_css_class("heading")
        content.append(lbl)

        entry_row = Adw.PasswordEntryRow(title="Senha")
        content.append(entry_row)

        hint = Gtk.Label(
            label="Esta senha é necessária para instalar pacotes AUR como usuário."
        )
        hint.set_wrap(True)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        hint.set_justify(Gtk.Justification.CENTER)
        content.append(hint)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancelar")
        cancel_btn.add_css_class("destructive-action")
        btn_box.append(cancel_btn)

        ok_btn = Gtk.Button(label="OK")
        ok_btn.add_css_class("suggested-action")
        btn_box.append(ok_btn)
        content.append(btn_box)

        toolbar_view.set_content(content)
        dialog.set_child(toolbar_view)

        # Fake window to host the dialog (Adw.Dialog requires a parent widget)
        win = Gtk.Window(application=_application)
        win.set_visible(False)

        def _submit(*_: object) -> None:
            password = entry_row.get_text()
            if password:
                result_holder["password"] = password
                result_holder["exit_code"] = 0
            dialog.close()
            _application.quit()

        def _cancel(*_: object) -> None:
            dialog.close()
            _application.quit()

        ok_btn.connect("clicked", _submit)
        cancel_btn.connect("clicked", _cancel)
        entry_row.connect("apply", _submit)

        # Also submit on Enter key in the entry
        key_ctrl = Gtk.EventControllerKey()

        def _on_key(_ctrl: Gtk.EventControllerKey, keyval: int, *_rest: object) -> bool:
            if keyval in (65293, 65421):  # GDK_KEY_Return, GDK_KEY_KP_Enter
                _submit()
                return True
            return False

        key_ctrl.connect("key-pressed", _on_key)
        entry_row.add_controller(key_ctrl)

        win.present()
        # Present dialog after a short idle so the window is realized
        GLib.timeout_add(50, lambda: dialog.present(win) or False)

    app.connect("activate", on_activate)
    app.run([])

    password = result_holder.get("password")
    if password:
        sys.stdout.write(f"{password}\n")
        sys.stdout.flush()
        return 0
    return int(result_holder.get("exit_code", 1))


if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Senha sudo:"
    sys.exit(run_askpass(prompt))
