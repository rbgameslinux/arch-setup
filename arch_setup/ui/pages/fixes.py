"""Correções page — Fase 4: ZapZap (PipeWire) e DaVinci Resolve (niri)."""

from __future__ import annotations

import shutil

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend import fixes as fixes_mod
from arch_setup.backend.runner import (
    ExecutionPlan,
    PrivilegedBatch,
    PrivilegedTask,
    TaskLogger,
    UserStep,
)
from arch_setup.ui.execution_dialog import ExecutionDialog


class FixesPage(Adw.PreferencesPage):
    """User-space fixes with detection, apply and revert actions."""

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Correções")
        self.set_name("fixes")
        self.set_icon_name("applications-engineering-symbolic")

        self._build_ui()
        GLib.idle_add(self._refresh_state)

    # ─────────────────────────── UI construction ────────────────────────────

    def _build_ui(self) -> None:
        zap_group = Adw.PreferencesGroup(
            title="Microfone do ZapZap",
            description=(
                "Bloqueia o controle de volume da fonte pelo QtWebEngineProcess "
                "no PipeWire (o ZapZap reduz o microfone ao abrir)."
            ),
        )
        self._zap_status = Adw.ActionRow(title="Regra PipeWire")
        zap_group.add(self._zap_status)

        zap_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        zap_actions.set_halign(Gtk.Align.END)

        self._zap_revert_btn = Gtk.Button(label="Reverter")
        self._zap_revert_btn.connect("clicked", self._on_revert_zapzap)
        zap_actions.append(self._zap_revert_btn)

        self._zap_apply_btn = Gtk.Button(label="Aplicar fix")
        self._zap_apply_btn.add_css_class("suggested-action")
        self._zap_apply_btn.connect("clicked", self._on_apply_zapzap)
        zap_actions.append(self._zap_apply_btn)

        zap_action_row = Adw.ActionRow(
            title="Aplicar ou remover a regra",
            subtitle="Reinicia o pipewire-pulse automaticamente",
        )
        zap_action_row.add_suffix(zap_actions)
        zap_group.add(zap_action_row)
        self.add(zap_group)

        resolve_group = Adw.PreferencesGroup(
            title="DaVinci Resolve (Wayland/niri)",
            description=(
                "Cria o wrapper ~/.local/bin/resolve com QT_QPA_PLATFORM=xcb, "
                "atualiza o .desktop e adiciona as regras de janela no niri."
            ),
        )

        self._output_row = Adw.ComboRow(
            title="Monitor para a janela flutuante",
            subtitle="Detectado via 'niri msg outputs'",
        )
        self._output_model = Gtk.StringList()
        self._output_row.set_model(self._output_model)
        resolve_group.add(self._output_row)

        self._resolve_status = Adw.ActionRow(title="Wrapper do Resolve")
        resolve_group.add(self._resolve_status)

        self._resolve_tools_row = Adw.ActionRow(title="Janela isca de foco")
        resolve_group.add(self._resolve_tools_row)

        self._install_decoy_row = Adw.SwitchRow(
            title="Instalar kitty se a isca estiver ausente",
            subtitle="kitty é nativo Wayland; xterm serve como fallback",
        )
        self._install_decoy_row.set_active(True)
        resolve_group.add(self._install_decoy_row)

        resolve_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        resolve_actions.set_halign(Gtk.Align.END)

        self._resolve_revert_btn = Gtk.Button(label="Reverter")
        self._resolve_revert_btn.connect("clicked", self._on_revert_resolve)
        resolve_actions.append(self._resolve_revert_btn)

        self._resolve_apply_btn = Gtk.Button(label="Aplicar fix")
        self._resolve_apply_btn.add_css_class("suggested-action")
        self._resolve_apply_btn.connect("clicked", self._on_apply_resolve)
        resolve_actions.append(self._resolve_apply_btn)

        resolve_action_row = Adw.ActionRow(
            title="Instalar/atualizar o wrapper e as regras",
            subtitle="Requer o Resolve em /opt/resolve/bin/resolve",
        )
        resolve_action_row.add_suffix(resolve_actions)
        resolve_group.add(resolve_action_row)
        self.add(resolve_group)

    # ─────────────────────────── State helpers ──────────────────────────────

    def _refresh_state(self) -> bool:
        zap_done = fixes_mod.zapzap_fix_is_applied()
        self._zap_status.set_subtitle(
            f"✓ Aplicada ({fixes_mod.PIPEWIRE_CONF_FILE})"
            if zap_done
            else "Não aplicada"
        )
        self._zap_apply_btn.set_label("Atualizar fix" if zap_done else "Aplicar fix")
        self._zap_revert_btn.set_sensitive(zap_done)

        resolve_done = fixes_mod.resolve_fix_is_applied()
        self._resolve_status.set_subtitle(
            f"✓ Instalado ({fixes_mod.WRAPPER_PATH})" if resolve_done else "Não instalado"
        )
        self._resolve_apply_btn.set_label(
            "Atualizar fix" if resolve_done else "Aplicar fix"
        )
        self._resolve_revert_btn.set_sensitive(resolve_done)

        outputs = fixes_mod.get_niri_outputs()
        self._output_model.remove_all()
        for output in outputs:
            self._output_model.append(output)
        # O seletor continua habilitado: trocar de monitor atualiza as regras.
        self._output_row.set_sensitive(True)

        # Atualiza a detecção (kitty pode ter sido instalado pelo próprio fix).
        fixes_mod.KITTY_PATH = shutil.which("kitty")
        fixes_mod.XTERM_PATH = shutil.which("xterm")
        tools = [
            name
            for name, path in (
                ("kitty", fixes_mod.KITTY_PATH),
                ("xterm", fixes_mod.XTERM_PATH),
            )
            if path is not None
        ]
        self._resolve_tools_row.set_subtitle(
            f"Disponíveis: {', '.join(tools)}" if tools else "Nenhum encontrado"
        )
        self._install_decoy_row.set_visible(not tools)
        return GLib.SOURCE_REMOVE

    def _selected_output(self) -> str:
        index = self._output_row.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return "DP-1"
        item = self._output_model.get_item(index)
        return item.get_string() if item is not None else "DP-1"

    def _run_plan(self, title: str, stages: list[object]) -> None:
        plan = ExecutionPlan(title, stages)
        view = ExecutionDialog(plan)
        view.start(
            self.get_root(),
            on_complete=lambda _ok: GLib.idle_add(self._refresh_state),
        )

    def _run_step(self, title: str, fn) -> None:
        self._run_plan(title, [UserStep(title=title, fn=fn)])

    # ────────────────────────────── Actions ─────────────────────────────────

    def _on_apply_zapzap(self, _button: Gtk.Button) -> None:
        def _apply(logger: TaskLogger) -> None:
            if not fixes_mod.apply_zapzap_fix(logger):
                raise RuntimeError("Não foi possível aplicar o fix do ZapZap.")

        self._run_step("Fix Microfone ZapZap", _apply)

    def _on_revert_zapzap(self, _button: Gtk.Button) -> None:
        def _revert(logger: TaskLogger) -> None:
            if not fixes_mod.revert_zapzap_fix(logger):
                raise RuntimeError("Não foi possível remover o fix do ZapZap.")

        self._run_step("Reverter Fix Microfone ZapZap", _revert)

    def _on_apply_resolve(self, _button: Gtk.Button) -> None:
        output = self._selected_output()
        stages: list[object] = []

        needs_decoy = fixes_mod.KITTY_PATH is None and fixes_mod.XTERM_PATH is None
        if needs_decoy and self._install_decoy_row.get_active():
            stages.append(
                PrivilegedBatch(
                    title="Instalar kitty para a isca de foco",
                    tasks=[
                        PrivilegedTask(
                            "pacman_install",
                            "Instalar kitty (isca de foco do Resolve)",
                            {"packages": ["kitty"]},
                        )
                    ],
                )
            )
        elif needs_decoy:
            # O wrapper instala o fix, mas avisará no log que a isca não abriu.
            pass

        def _apply(logger: TaskLogger) -> None:
            if not fixes_mod.apply_resolve_fix(output, logger):
                raise RuntimeError("Não foi possível aplicar o fix do DaVinci Resolve.")

        stages.append(UserStep(title="Wrapper, .desktop e regras do niri", fn=_apply))
        self._run_plan(f"Fix DaVinci Resolve ({output})", stages)

    def _on_revert_resolve(self, _button: Gtk.Button) -> None:
        def _revert(logger: TaskLogger) -> None:
            if not fixes_mod.revert_resolve_fix(logger):
                raise RuntimeError("Não foi possível remover o fix do DaVinci Resolve.")

        self._run_step("Reverter Fix DaVinci Resolve", _revert)
