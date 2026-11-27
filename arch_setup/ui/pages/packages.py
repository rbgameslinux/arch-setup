"""Pós-formatação & Pacotes page — Fase 2.

This page covers:
 • AUR toggle + helper selection (paru / yay)
 • Category-grouped package list with installed-state detection
 • Icon Themes & Fonts sub-section
 • Package search (official repos first, AUR only when enabled)
  • Build button that assembles an ExecutionPlan and opens the ExecutionDialog
"""

from __future__ import annotations

import threading
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from arch_setup.backend import appimages as appimages_mod
from arch_setup.backend import aur as aur_mod
from arch_setup.backend import gearlever as gearlever_mod
from arch_setup.backend import search as search_mod
from arch_setup.backend.runner import (
    ExecutionPlan,
    PrivilegedBatch,
    PrivilegedTask,
    TaskLogger,
    UserStep,
)
from arch_setup.models.catalog import (
    BASE_PACKAGES,
    ICON_FONT_PACKAGES,
    OPTIONAL_PACKAGES,
    PackageItem,
    detect_aur_helper,
    detect_cpu_cores,
    get_installed_pacman_packages,
)
from arch_setup.ui.execution_dialog import ExecutionDialog
from arch_setup.ui.pages import escape_label


class _CheckRow(Adw.ActionRow):
    """ActionRow with a leading check-button for package selection."""

    def __init__(
        self, item: PackageItem, installed: bool, badge: str | None = None
    ) -> None:
        super().__init__()
        self.item = item
        self.set_title(escape_label(item.name))

        badge_text = badge or {
            "repo": "repo",
            "aur": "AUR",
            "appimage": "AppImage",
        }.get(item.source, item.source)
        self.set_subtitle(escape_label(f"{item.description}  •  {badge_text}"))

        self._check = Gtk.CheckButton()
        self._check.set_active(False)
        self.add_prefix(self._check)
        self.set_activatable_widget(self._check)

        if installed:
            installed_lbl = Gtk.Label(label="Instalado")
            installed_lbl.add_css_class("dim-label")
            installed_lbl.add_css_class("caption")
            self.add_suffix(installed_lbl)

    @property
    def is_checked(self) -> bool:
        return self._check.get_active()

    def set_aur_visible(self, aur_enabled: bool) -> None:
        """Show/hide this row based on AUR-enabled state."""
        if self.item.source == "aur":
            self.set_visible(aur_enabled)


class PackagesPage(Adw.PreferencesPage):
    """Full pós-formatação page: AUR toggle, packages, and icon themes/fonts."""

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Pós-formatação")
        self.set_name("packages")
        self.set_icon_name("system-software-install-symbolic")

        self._installed: set[str] = set()
        self._aur_enabled = False
        self._helper: str | None = None
        self._rows: list[_CheckRow] = []
        self._icon_rows: list[_CheckRow] = []
        self._expanders: dict[str, Adw.ExpanderRow] = {}
        self._category_rows: dict[str, list[_CheckRow]] = {}
        self._counts: dict[str, Gtk.Label] = {}
        self._custom_rows: dict[str, _CheckRow] = {}
        self._last_results: list[search_mod.PackageResult] = []
        self._rendered_rows: list[_CheckRow] = []
        self._search_generation = 0
        self._searching = False
        self._gearlever_detected: bool = gearlever_mod.is_available()
        self._gearlever_user_changed = False
        self._gearlever_updating = False
        self._dropped_appimages: list[Path] = []

        self._build_ui()
        GLib.idle_add(self._refresh_state)

    # ─────────────────────────── UI construction ────────────────────────────

    def _build_ui(self) -> None:
        self._build_aur_group()
        self._build_packages_group()
        self._build_appimage_group()
        self._build_search_group()
        self._build_action_group()

    def _build_aur_group(self) -> None:
        aur_group = Adw.PreferencesGroup(
            title="Suporte ao AUR",
            description=(
                "O AUR é mantido pela comunidade e não é auditado oficialmente. "
                "Habilite apenas se souber o que está fazendo."
            ),
        )

        self._aur_switch_row = Adw.SwitchRow(
            title="Habilitar pacotes AUR",
            subtitle="Instala paru ou yay antes dos pacotes",
        )
        self._aur_switch_row.connect("notify::active", self._on_aur_toggled)
        aur_group.add(self._aur_switch_row)

        self._helper_row = Adw.ComboRow(
            title="Helper AUR preferido",
            subtitle="Usado quando nenhum helper está instalado",
        )
        helper_model = Gtk.StringList()
        helper_model.append("paru")
        helper_model.append("yay")
        self._helper_row.set_model(helper_model)
        self._helper_row.set_visible(False)
        aur_group.add(self._helper_row)

        self._helper_status_row = Adw.ActionRow(title="Helper AUR detectado")
        self._helper_status_row.set_visible(False)
        aur_group.add(self._helper_status_row)

        self.add(aur_group)

    def _build_packages_group(self) -> None:
        """One collapse/expand row per category, inside a single clean group."""
        self._packages_group = Adw.PreferencesGroup(
            title="Pacotes opcionais",
            description="Clique numa categoria para expandir e escolher os itens.",
        )

        categories: dict[str, list[PackageItem]] = {}
        for pkg in OPTIONAL_PACKAGES:
            categories.setdefault(pkg.category, []).append(pkg)

        for cat_name, pkgs in categories.items():
            self._add_category_expander(cat_name, pkgs)

        self._build_icon_fonts_group()
        self._update_counts()
        self.add(self._packages_group)

    def _build_appimage_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="AppImages",
            description=(
                "Estrutura completa estilo Gear Lever, mesmo sem ele instalado: "
                "pasta própria, ícone em .icons/ e .desktop com "
                "DESKTOPINTEGRATION=1. Arraste um AppImage avulso para a linha "
                "abaixo para instalá-lo com o mesmo padrão."
            ),
        )
        self._gearlever_switch = Adw.SwitchRow(
            title="Integrar no estilo Gear Lever",
            subtitle="Preparando pasta...",
        )
        self._gearlever_switch.connect(
            "notify::active", self._on_gearlever_toggled
        )
        group.add(self._gearlever_switch)

        self._drop_row = Adw.ActionRow(
            title="Instalar AppImage avulso",
            subtitle="Arraste um .AppImage para cá ou escolha o arquivo",
        )
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_appimage_drop)
        self._drop_row.add_controller(drop_target)
        choose_btn = Gtk.Button(label="Escolher arquivo")
        choose_btn.connect("clicked", self._on_choose_appimage)
        self._drop_row.add_suffix(choose_btn)
        group.add(self._drop_row)
        self.add(group)

    def _on_gearlever_toggled(self, row: Adw.SwitchRow, *_: object) -> None:
        if self._gearlever_updating:
            return
        self._gearlever_user_changed = True
        if row.get_active():
            row.set_subtitle(
                f"Pasta deste usuário: {gearlever_mod.appimages_dir()} • "
                "DESKTOPINTEGRATION=1"
            )
        else:
            row.set_subtitle("Será usada a integração padrão (ícone + .desktop)")

    def _on_appimage_drop(
        self, _target: Gtk.DropTarget, gio_file: Gio.File, *_: object
    ) -> None:
        path = gio_file.get_path()
        if path:
            self._queue_appimage(Path(path))

    def _on_choose_appimage(self, *_: object) -> None:
        dialog = Gtk.FileDialog(title="Escolher AppImage")
        file_filter = Gtk.FileFilter()
        file_filter.add_pattern("*.AppImage")
        file_filter.add_pattern("*.appimage")
        dialog.set_default_filter(file_filter)
        dialog.open(self.get_root(), None, self._on_appimage_chosen)

    def _on_appimage_chosen(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            gio_file = dialog.open_finish(result)
        except Exception:
            return
        path = gio_file.get_path()
        if path:
            self._queue_appimage(Path(path))

    def _queue_appimage(self, path: Path) -> None:
        if path.suffix.lower() != ".appimage" or not path.is_file():
            self._drop_row.set_subtitle("Arquivo inválido — escolha um .AppImage")
            return
        if path not in self._dropped_appimages:
            self._dropped_appimages.append(path)
        self._drop_row.set_subtitle(
            f"{len(self._dropped_appimages)} AppImage(s) na fila — instalando..."
        )
        GLib.idle_add(lambda: self._on_install_clicked(None))

    def _add_category_expander(
        self, title: str, pkgs: list[PackageItem], *, is_icon_group: bool = False
    ) -> None:
        """Create an Adw.ExpanderRow holding selectable package rows."""
        expander = Adw.ExpanderRow(title=escape_label(title))
        count_lbl = Gtk.Label()
        count_lbl.add_css_class("dim-label")
        count_lbl.add_css_class("caption")
        expander.add_suffix(count_lbl)

        self._expanders[title] = expander
        self._counts[title] = count_lbl

        rows: list[_CheckRow] = []
        for pkg in pkgs:
            row = _CheckRow(pkg, installed=False)
            row.set_aur_visible(self._aur_enabled)
            row._check.connect("toggled", self._on_selection_toggled)
            rows.append(row)
            if is_icon_group:
                self._icon_rows.append(row)
            else:
                self._rows.append(row)
            expander.add_row(row)

        self._category_rows[title] = rows
        self._packages_group.add(expander)

    def _build_icon_fonts_group(self) -> None:
        self._add_category_expander(
            "Ícones e fontes",
            list(ICON_FONT_PACKAGES),
            is_icon_group=True,
        )

    def _build_search_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Buscar pacote",
            description=(
                "Busca primeiro nos repositórios oficiais. Com o AUR ativado, "
                "resultados do AUR aparecem depois — repo sempre primeiro."
            ),
        )
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Ex.: mpv, gimp, visual-studio-code")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("activate", lambda *_: self._start_search())
        self._search_entry.connect("search-changed", self._on_search_changed)

        self._search_btn = Gtk.Button(label="Buscar")
        self._search_btn.connect("clicked", lambda *_: self._start_search())

        self._search_spinner = Gtk.Spinner()
        self._search_spinner.set_visible(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_hexpand(True)
        box.append(self._search_entry)
        box.append(self._search_btn)
        box.append(self._search_spinner)

        search_row = Adw.ActionRow(
            title="Pacote",
            subtitle="Pressione Enter ou clique em Buscar",
        )
        search_row.add_suffix(box)
        group.add(search_row)
        self.add(group)

        self._results_group = Adw.PreferencesGroup(title="Resultados da busca")
        self._results_group.set_visible(False)
        self.add(self._results_group)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Clear results when the user empties the field (the 'x' button)."""
        if entry.get_text().strip():
            return

        # Invalidate any search still running so stale results don't come back.
        if self._searching:
            self._search_generation += 1
            self._searching = False
            self._search_spinner.stop()
            self._search_spinner.set_visible(False)
            self._search_btn.set_sensitive(True)

        self._render_results([])
        if not any(row.is_checked for row in self._custom_rows.values()):
            self._results_group.set_visible(False)

    def _start_search(self) -> None:
        query = self._search_entry.get_text().strip()
        if not query or len(query) > 100:
            return

        self._search_generation += 1
        generation = self._search_generation
        self._searching = True
        self._search_btn.set_sensitive(False)
        self._search_spinner.set_visible(True)
        self._search_spinner.start()
        self._results_group.set_visible(True)
        self._results_group.set_description("Buscando...")

        def worker() -> None:
            results = search_mod.search_packages(query, include_aur=self._aur_enabled)
            GLib.idle_add(self._finish_search, generation, results)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_search(
        self, generation: int, results: list[search_mod.PackageResult]
    ) -> bool:
        # Discard answers from older searches.
        if generation != self._search_generation:
            return GLib.SOURCE_REMOVE
        self._searching = False
        self._search_spinner.stop()
        self._search_spinner.set_visible(False)
        self._search_btn.set_sensitive(True)
        self._render_results(results)
        return GLib.SOURCE_REMOVE

    def _get_custom_row(self, result: search_mod.PackageResult) -> _CheckRow:
        row = self._custom_rows.get(result.name)
        if row is None:
            item = PackageItem(
                name=result.name,
                description=result.description or "Sem descrição",
                source=result.source,  # type: ignore[arg-type]
                category="Busca",
            )
            badge = (
                f"repo/{result.repository}"
                if result.source == "repo"
                else "AUR"
            )
            row = _CheckRow(
                item, installed=result.name in self._installed, badge=badge
            )
            # Re-render on toggle so checked packages move to the top.
            row._check.connect("toggled", self._on_custom_toggled)
            self._custom_rows[result.name] = row
        return row

    def _on_custom_toggled(self, _check: Gtk.CheckButton) -> None:
        # Defer: removing the emitting widget during its own signal is unsafe.
        GLib.idle_add(self._reorder_custom_rows)

    def _reorder_custom_rows(self) -> bool:
        self._render_results(self._last_results)
        return GLib.SOURCE_REMOVE

    def _render_results(self, results: list[search_mod.PackageResult]) -> None:
        self._last_results = list(results)
        for row in list(self._custom_rows.values()):
            if row.get_parent() is not None:
                self._results_group.remove(row)

        self._rendered_rows = []
        shown: set[str] = set()

        def add_row(row: _CheckRow) -> None:
            self._results_group.add(row)
            self._rendered_rows.append(row)
            shown.add(row.item.name)

        # 1) Selected packages always stay on top, even across searches.
        for row in self._custom_rows.values():
            if row.is_checked:
                add_row(row)

        # 2) New results are appended below, in repo-first order.
        for result in results:
            row = self._get_custom_row(result)
            if row.item.name not in shown:
                add_row(row)

        selected_count = sum(
            1 for row in self._custom_rows.values() if row.is_checked
        )
        repo_count = sum(1 for result in results if result.source == "repo")
        aur_count = len(results) - repo_count
        pieces: list[str] = []
        if selected_count:
            noun = "selecionado" if selected_count == 1 else "selecionados"
            pieces.append(f"{selected_count} {noun} no topo")
        if results:
            text = (
                f"{len(results)} resultado(s) — {repo_count} do repositório oficial"
            )
            if aur_count:
                text += f" e {aur_count} do AUR"
            pieces.append(text)
        if pieces:
            description = "  •  ".join(pieces)
        else:
            description = "Nenhum pacote encontrado nos repositórios"
            description += " nem no AUR." if self._aur_enabled else "."
        self._results_group.set_description(description)
        self._update_custom_visibility()
        self._results_group.set_visible(True)

    def _update_custom_visibility(self) -> None:
        for row in self._custom_rows.values():
            row.set_visible(
                self._aur_enabled if row.item.source == "aur" else True
            )

    def _build_action_group(self) -> None:
        action_group = Adw.PreferencesGroup()

        select_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        select_box.set_halign(Gtk.Align.CENTER)
        select_box.set_margin_top(4)
        select_box.set_margin_bottom(4)

        select_all_btn = Gtk.Button(label="Selecionar todos")
        select_all_btn.connect("clicked", lambda *_: self._select_all(True))
        select_box.append(select_all_btn)

        deselect_all_btn = Gtk.Button(label="Desmarcar todos")
        deselect_all_btn.connect("clicked", lambda *_: self._select_all(False))
        select_box.append(deselect_all_btn)

        select_row = Adw.ActionRow()
        select_row.set_child(select_box)
        action_group.add(select_row)

        install_row = Adw.ActionRow(
            title="Instalar pacotes selecionados",
            subtitle="Clique para revisar e iniciar a instalação",
        )
        self._install_btn = Gtk.Button(label="Instalar")
        self._install_btn.add_css_class("suggested-action")
        self._install_btn.set_valign(Gtk.Align.CENTER)
        self._install_btn.connect("clicked", self._on_install_clicked)
        install_row.add_suffix(self._install_btn)
        action_group.add(install_row)

        self.add(action_group)

    # ─────────────────────────── State helpers ──────────────────────────────

    def _refresh_state(self) -> bool:
        self._installed = get_installed_pacman_packages()
        self._helper = detect_aur_helper()

        # Update installed badges
        for row in self._rows + self._icon_rows:
            installed = row.item.name in self._installed
            # Rebuild suffix label state
            # (simpler: just update the subtitle to show installed state)
            if installed:
                row.set_subtitle(
                    f"{row.item.description}  •  {row.item.source.upper()}  ✓ instalado"
                )

        # Update helper status
        if self._helper:
            self._helper_status_row.set_title(f"Helper detectado: {self._helper}")
            self._helper_status_row.set_subtitle("Será usado para instalação AUR")
            self._helper_status_row.set_visible(self._aur_switch_row.get_active())
            self._helper_row.set_visible(False)
        else:
            self._helper_status_row.set_visible(False)
            self._helper_row.set_visible(self._aur_switch_row.get_active())

        # A estrutura é aplicada por padrão mesmo sem o Gear Lever instalado;
        # a presença do binário AUR só muda o texto informativo.
        self._gearlever_detected = gearlever_mod.is_available()
        if not self._gearlever_user_changed:
            self._gearlever_updating = True
            self._gearlever_switch.set_active(True)
            self._gearlever_updating = False
        if self._gearlever_switch.get_active():
            self._gearlever_switch.set_subtitle(
                f"Pasta deste usuário: {gearlever_mod.appimages_dir()} • "
                "DESKTOPINTEGRATION=1"
                + (
                    " (Gear Lever AUR detectado)"
                    if self._gearlever_detected
                    else " (padrão; Gear Lever não instalado)"
                )
            )
        else:
            self._gearlever_switch.set_subtitle(
                "Será usada a integração padrão (ícone + .desktop)"
            )

        self._update_counts()
        self._update_custom_visibility()
        return GLib.SOURCE_REMOVE

    def _on_selection_toggled(self, _check: Gtk.CheckButton) -> None:
        """Keep expander subtitles/badges in sync with the current selection."""
        self._update_counts()

    def _update_counts(self) -> None:
        for title, expander in self._expanders.items():
            visible = [row for row in self._category_rows[title] if row.get_visible()]
            selected = sum(1 for row in visible if row.is_checked)
            total = len(visible)
            item_word = "item" if total == 1 else "itens"
            selected_word = "selecionado" if selected == 1 else "selecionados"
            expander.set_subtitle(
                escape_label(f"{total} {item_word}  •  {selected} {selected_word}")
            )
            self._counts[title].set_label(f"{selected}/{total}")

    def _on_aur_toggled(self, switch_row: Adw.SwitchRow, _param: object) -> None:
        self._aur_enabled = switch_row.get_active()
        for row in self._rows:
            row.set_aur_visible(self._aur_enabled)
        # Show helper selector or detected helper
        if self._aur_enabled:
            if self._helper:
                self._helper_status_row.set_visible(True)
                self._helper_row.set_visible(False)
            else:
                self._helper_row.set_visible(True)
                self._helper_status_row.set_visible(False)
        else:
            self._helper_row.set_visible(False)
            self._helper_status_row.set_visible(False)

        self._update_counts()
        self._update_custom_visibility()

    def _select_all(self, state: bool) -> None:
        for row in self._rows:
            if row.get_visible():
                row._check.set_active(state)
        for row in self._icon_rows:
            row._check.set_active(state)
        for row in self._custom_rows.values():
            if row.get_visible():
                row._check.set_active(state)

    # ─────────────────────────── Plan building ──────────────────────────────

    def _on_install_clicked(self, button: Gtk.Button | None = None) -> None:
        plan = self._build_plan()
        if plan is None:
            self._show_nothing_selected()
            return
        dialog = ExecutionDialog(plan)
        root = self.get_root()
        dialog.start(root, on_complete=lambda _ok: GLib.idle_add(self._refresh_state))

    def _show_nothing_selected(self) -> None:
        alert = Adw.AlertDialog.new(
            "Nada selecionado",
            "Selecione ao menos um pacote ou item antes de instalar.",
        )
        alert.add_response("ok", "OK")
        alert.present(self.get_root())

    def _build_plan(self) -> ExecutionPlan | None:
        # Collect selections
        repo_pkgs: list[str] = []
        aur_pkgs: list[str] = []
        appimage_pkgs: list[str] = []
        icon_pkgs: list[str] = []

        for row in self._rows:
            if not row.is_checked or not row.get_visible():
                continue
            item = row.item
            if item.source == "repo":
                repo_pkgs.append(item.name)
                repo_pkgs.extend(item.extra_packages)
            elif item.source == "aur":
                aur_pkgs.append(item.name)
            elif item.source == "appimage":
                appimage_pkgs.append(item.name)

        for row in self._icon_rows:
            if row.is_checked:
                icon_pkgs.append(row.item.name)

        # Packages found through the search field (persist across searches).
        for row in self._custom_rows.values():
            if not row.is_checked:
                continue
            if row.item.source == "repo":
                if row.item.name not in repo_pkgs:
                    repo_pkgs.append(row.item.name)
            elif row.item.source == "aur" and self._aur_enabled:
                if row.item.name not in aur_pkgs:
                    aur_pkgs.append(row.item.name)

        # Merge all repo packages (base + selected repo + icons)
        all_repo = list(BASE_PACKAGES) + repo_pkgs + icon_pkgs
        # De-duplicate preserving order
        seen: set[str] = set()
        deduped_repo: list[str] = []
        for p in all_repo:
            if p not in seen:
                seen.add(p)
                deduped_repo.append(p)

        # Nothing selected at all?
        if (
            not repo_pkgs
            and not aur_pkgs
            and not appimage_pkgs
            and not icon_pkgs
            and not self._dropped_appimages
        ):
            # Check if at least base packages differ from installed
            new_repo = [p for p in deduped_repo if p not in self._installed]
            if not new_repo and not aur_pkgs and not appimage_pkgs:
                return None

        stages: list[object] = []

        # ── Stage 1: Privileged — pacman install base + repo ──
        priv_tasks: list[PrivilegedTask] = []
        cores = detect_cpu_cores()
        priv_tasks.append(
            PrivilegedTask(
                "configure_makepkg_jobs",
                f"Configurar MAKEFLAGS=-j{cores}",
                {"cores": cores},
            )
        )
        priv_tasks.append(
            PrivilegedTask(
                "pacman_install",
                f"Instalar {len(deduped_repo)} pacote(s) base + repo via pacman",
                {"packages": deduped_repo},
            )
        )
        stages.append(
            PrivilegedBatch(
                title="Pacman: base + repo + ícones/fontes",
                tasks=priv_tasks,
            )
        )

        # ── Stage 2 (optional): User — AUR helper + AUR packages ──
        if self._aur_enabled:
            chosen_helper = self._helper
            if not chosen_helper:
                # Determine from ComboRow selection
                idx = self._helper_row.get_selected()
                chosen_helper = "yay" if idx == 1 else "paru"

            aur_pkgs_to_install = aur_pkgs[:]

            def _aur_stage(logger: TaskLogger, _helper: str = chosen_helper, _pkgs: list[str] = aur_pkgs_to_install) -> None:
                helper = detect_aur_helper() or aur_mod.install_aur_helper(
                    _helper, logger=logger
                )
                if not helper:
                    raise RuntimeError(
                        "Não foi possível instalar um AUR helper; pacotes AUR não instalados. "
                        "Verifique base-devel/git e a conexão com os repositórios "
                        "(sudo pacman -S --needed base-devel git)."
                    )
                # Install electron29-bin as base AUR dependency
                if aur_mod.install_electron29_bin(helper=helper, logger=logger) != 0:
                    raise RuntimeError("Falha ao instalar electron29-bin (AUR).")
                if _pkgs and aur_mod.aur_install(
                    _pkgs, helper=helper, logger=logger
                ) != 0:
                    raise RuntimeError(
                        f"Falha ao instalar pacotes AUR: {', '.join(_pkgs)}"
                    )

            stages.append(
                UserStep(
                    title=f"AUR: electron29-bin + {len(aur_pkgs)} pacote(s)",
                    fn=_aur_stage,
                )
            )

        # ── Stage 3 (optional): User — AppImages ──
        if appimage_pkgs:
            use_gearlever = self._gearlever_switch.get_active()

            def _appimage_stage(logger: TaskLogger, _pkgs: list[str] = appimage_pkgs) -> None:
                total = len(_pkgs)
                for i, pkg_name in enumerate(_pkgs, 1):
                    logger.set_progress((i - 1) / total, f"AppImage {i}/{total}: {pkg_name}")
                    installer = appimages_mod.APPIMAGE_INSTALLERS.get(pkg_name)
                    if installer:
                        ok = installer(logger, use_gearlever=use_gearlever)
                        if not ok:
                            logger.warn(f"Falha ao instalar AppImage: {pkg_name}")
                    else:
                        logger.warn(f"Sem instalador para AppImage: {pkg_name}")

            suffix = " (estilo Gear Lever)" if use_gearlever else ""
            stages.append(
                UserStep(
                    title=f"AppImages ({', '.join(appimage_pkgs)}){suffix}",
                    fn=_appimage_stage,
                )
            )

        # ── Stage 3b (optional): User — AppImages arrastados pelo usuário ──
        if self._dropped_appimages:
            use_gearlever = self._gearlever_switch.get_active()
            dropped = list(self._dropped_appimages)
            self._dropped_appimages.clear()
            GLib.idle_add(
                lambda: self._drop_row.set_subtitle(
                    "Arraste um .AppImage para cá ou escolha o arquivo"
                )
            )

            def _dropped_stage(logger: TaskLogger) -> None:
                total = len(dropped)
                for i, source in enumerate(dropped, 1):
                    logger.set_progress(
                        (i - 1) / total, f"AppImage avulso {i}/{total}: {source.name}"
                    )
                    ok = appimages_mod.install_appimage_file(
                        source, logger, use_gearlever=use_gearlever
                    )
                    if not ok:
                        logger.warn(f"Falha ao instalar AppImage avulso: {source}")

            suffix = " (estilo Gear Lever)" if use_gearlever else ""
            stages.append(
                UserStep(
                    title=f"AppImages avulsos ({len(dropped)}){suffix}",
                    fn=_dropped_stage,
                )
            )

        return ExecutionPlan(
            title="Pós-formatação & Pacotes",
            stages=stages,
        )
