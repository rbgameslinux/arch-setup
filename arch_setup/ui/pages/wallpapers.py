"""Wallpapers page — Fase 4: download da coleção Rbgames (~1.2 GB)."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend import wallpapers as wallpapers_mod
from arch_setup.backend.runner import ExecutionPlan, TaskLogger, UserStep
from arch_setup.ui.execution_dialog import ExecutionDialog


class WallpapersPage(Adw.PreferencesPage):
    """Installs the Rbgames wallpaper collection with live progress."""

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Wallpapers")
        self.set_name("wallpapers")
        self.set_icon_name("preferences-desktop-wallpaper-symbolic")

        self._build_ui()
        GLib.idle_add(self._refresh_state)

    def _build_ui(self) -> None:
        group = Adw.PreferencesGroup(
            title="Coleção Rbgames",
            description=(
                "Coleção de ~932 imagens (~1.2 GB) hospedada no Google Drive. "
                "Os arquivos são instalados em ~/Wallpapers."
            ),
        )

        self._status_row = Adw.ActionRow(title="Estado da instalação")
        group.add(self._status_row)

        self._destination_row = Adw.ActionRow(
            title="Destino",
            subtitle=str(wallpapers_mod.DEST_DIR),
        )
        group.add(self._destination_row)

        install_row = Adw.ActionRow(
            title="Baixar e instalar wallpapers",
            subtitle="Download grande: verifique sua conexão e o limite de cota do Drive",
        )
        self._install_btn = Gtk.Button(label="Instalar")
        self._install_btn.add_css_class("suggested-action")
        self._install_btn.set_valign(Gtk.Align.CENTER)
        self._install_btn.connect("clicked", self._on_install)
        install_row.add_suffix(self._install_btn)
        group.add(install_row)

        self.add(group)

    def _refresh_state(self) -> bool:
        installed = wallpapers_mod.wallpapers_installed()
        self._status_row.set_subtitle(
            f"✓ Instalados em {wallpapers_mod.DEST_DIR}"
            if installed
            else "Ainda não instalados"
        )
        self._install_btn.set_label("Atualizar instalação" if installed else "Instalar")
        return GLib.SOURCE_REMOVE

    def _on_install(self, _button: Gtk.Button) -> None:
        def _install(logger: TaskLogger) -> None:
            if not wallpapers_mod.download_and_install_wallpapers(logger):
                raise RuntimeError(
                    "Falha ao baixar/instalar os wallpapers. "
                    "O Google Drive pode ter atingido o limite de cota."
                )

        plan = ExecutionPlan(
            title="Instalar Wallpapers Rbgames",
            stages=[UserStep(title="Download e extração dos wallpapers", fn=_install)],
        )
        dialog = ExecutionDialog(plan)
        dialog.start(
            self.get_root(),
            on_complete=lambda _ok: GLib.idle_add(self._refresh_state),
        )
