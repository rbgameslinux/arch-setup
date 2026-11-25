"""Live execution dialog with progress bar, streaming log, and error prompt."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend.runner import CommandRunner, ExecutionPlan, RunnerCallbacks


class ExecutionDialog(Adw.Dialog):
    """Modal dialog that runs an ExecutionPlan and displays live output."""

    def __init__(self, plan: ExecutionPlan) -> None:
        super().__init__()
        self._plan = plan
        self._runner = CommandRunner()
        self._on_complete: Callable[[bool], None] | None = None
        self._finished = False

        self.set_title(plan.title)
        self.set_content_width(760)
        self.set_content_height(540)
        self.set_can_close(False)

        self._build_ui()

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        self._status_label = Gtk.Label(label="Preparando execução...")
        self._status_label.set_xalign(0.0)
        self._status_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self._status_label.add_css_class("heading")
        content.append(self._status_label)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_show_text(True)
        self._progress_bar.set_fraction(0.0)
        self._progress_bar.set_text("0%")
        content.append(self._progress_bar)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_has_frame(True)

        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_monospace(True)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_top_margin(8)
        self._text_view.set_bottom_margin(8)
        self._text_view.set_left_margin(10)
        self._text_view.set_right_margin(10)

        self._buffer = self._text_view.get_buffer()
        self._setup_tags()

        scrolled.set_child(self._text_view)
        content.append(scrolled)
        self._scrolled = scrolled

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._log_label = Gtk.Label(label="")
        self._log_label.set_xalign(0.0)
        self._log_label.set_hexpand(True)
        self._log_label.set_ellipsize(2)  # PANGO_ELLIPSIZE_MIDDLE
        self._log_label.add_css_class("dim-label")
        self._log_label.add_css_class("caption")
        footer.append(self._log_label)

        self._action_button = Gtk.Button(label="Cancelar")
        self._action_button.add_css_class("destructive-action")
        self._action_button.connect("clicked", self._on_action_clicked)
        footer.append(self._action_button)

        content.append(footer)
        toolbar_view.set_content(content)
        self.set_child(toolbar_view)

    def _setup_tags(self) -> None:
        self._buffer.create_tag("info", foreground="#2ec27e")
        self._buffer.create_tag("warn", foreground="#e5a50a")
        self._buffer.create_tag("error", foreground="#e01b24")
        self._buffer.create_tag("normal")

    def start(
        self,
        parent: Gtk.Widget,
        on_complete: Callable[[bool], None] | None = None,
    ) -> None:
        """Present dialog over parent and start running the plan."""
        self._on_complete = on_complete
        self.present(parent)

        callbacks = RunnerCallbacks(
            on_log=self._append_log,
            on_progress=self._update_progress,
            on_error_prompt=self._prompt_continue,
            on_finished=self._handle_finished,
        )
        log_path = self._runner.start(self._plan, callbacks)
        self._log_label.set_text(f"Log: {log_path}")

    def _append_log(self, line: str, level: str) -> bool:
        end_iter = self._buffer.get_end_iter()
        tag_name = level if level in {"info", "warn", "error"} else "normal"
        self._buffer.insert_with_tags_by_name(end_iter, f"{line}\n", tag_name)
        GLib.idle_add(self._scroll_to_bottom)
        return GLib.SOURCE_REMOVE

    def _scroll_to_bottom(self) -> bool:
        vadj = self._scrolled.get_vadjustment()
        vadj.set_value(max(0.0, vadj.get_upper() - vadj.get_page_size()))
        return GLib.SOURCE_REMOVE

    def _update_progress(self, fraction: float, status: str) -> bool:
        self._progress_bar.set_fraction(fraction)
        self._progress_bar.set_text(f"{int(round(fraction * 100))}%")
        if status:
            self._status_label.set_text(status)
        return GLib.SOURCE_REMOVE

    def _prompt_continue(
        self,
        stage_title: str,
        error_msg: str,
        respond: Callable[[bool], None],
    ) -> bool:
        alert = Adw.AlertDialog.new(
            f"Falha em: {stage_title}",
            f"{error_msg}\n\nDeseja continuar com as próximas etapas mesmo assim?",
        )
        alert.add_response("abort", "Abortar")
        alert.add_response("continue", "Continuar mesmo assim")
        alert.set_response_appearance("abort", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_default_response("abort")
        alert.set_close_response("abort")

        def _on_response(_dlg: Adw.AlertDialog, response: str) -> None:
            respond(response == "continue")

        alert.connect("response", _on_response)
        alert.present(self)
        return GLib.SOURCE_REMOVE

    def _handle_finished(
        self, success: bool, summary: str, log_path: Path
    ) -> bool:
        self._finished = True
        self.set_can_close(True)
        self._progress_bar.set_fraction(1.0 if success else self._progress_bar.get_fraction())
        if success:
            self._progress_bar.set_text("100%")
        self._status_label.set_text(summary)
        self._log_label.set_text(f"Log: {log_path}")

        self._action_button.remove_css_class("destructive-action")
        self._action_button.add_css_class("suggested-action")
        self._action_button.set_label("Fechar")
        self._action_button.set_sensitive(True)

        if self._on_complete is not None:
            self._on_complete(success)
        return GLib.SOURCE_REMOVE

    def _on_action_clicked(self, _button: Gtk.Button) -> None:
        if self._finished:
            self.close()
            return
        self._action_button.set_sensitive(False)
        self._status_label.set_text("Cancelando execução...")
        self._runner.cancel()
