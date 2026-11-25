"""Pós-formatação & Pacotes page — Fase 2.

This page covers:
 • AUR toggle + helper selection (paru / yay)
 • Category-grouped package list with installed-state detection
 • Icon Themes & Fonts sub-section
 • Build button that assembles an ExecutionPlan and opens the ExecutionDialog
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from arch_setup.backend import appimages as appimages_mod
from arch_setup.backend import aur as aur_mod
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
    get_installed_pacman_packages,
)
from arch_setup.ui.execution_dialog import ExecutionDialog


class _CheckRow(Adw.ActionRow):
    """ActionRow with a leading check-button for package selection."""

    def __init__(self, item: PackageItem, installed: bool) -> None:
        super().__init__()
        self.item = item
        self.set_title(item.name)

        badge = {
            "repo": "repo",
            "aur": "AUR",
            "appimage": "AppImage",
        }.get(item.source, item.source)
        self.set_subtitle(f"{item.description}  •  {badge}")

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

        self._build_ui()
        GLib.idle_add(self._refresh_state)

    # ─────────────────────────── UI construction ────────────────────────────

    def _build_ui(self) -> None:
        self._build_aur_group()
        self._build_packages_group()
        self._build_icon_fonts_group()
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
        # Group packages by category
        categories: dict[str, list[PackageItem]] = {}
        for pkg in OPTIONAL_PACKAGES:
            categories.setdefault(pkg.category, []).append(pkg)

        for cat_name, pkgs in categories.items():
            group = Adw.PreferencesGroup(title=cat_name)
            for pkg in pkgs:
                row = _CheckRow(pkg, installed=False)
                row.set_aur_visible(self._aur_enabled)
                self._rows.append(row)
                group.add(row)
            self.add(group)

    def _build_icon_fonts_group(self) -> None:
        icon_group = Adw.PreferencesGroup(
            title="Icon Themes & Fonts",
            description="Todos do repositório oficial — sem AUR.",
        )
        for pkg in ICON_FONT_PACKAGES:
            row = _CheckRow(pkg, installed=False)
            self._icon_rows.append(row)
            icon_group.add(row)
        self.add(icon_group)

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

        return GLib.SOURCE_REMOVE

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

    def _select_all(self, state: bool) -> None:
        for row in self._rows:
            if row.get_visible():
                row._check.set_active(state)
        for row in self._icon_rows:
            row._check.set_active(state)

    # ─────────────────────────── Plan building ──────────────────────────────

    def _on_install_clicked(self, button: Gtk.Button) -> None:
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

        # Merge all repo packages (base + selected repo + icons)
        all_repo = list(BASE_PACKAGES) + repo_pkgs + icon_pkgs
        # De-duplicate preserving order
        seen: set[str] = set()
        deduped_repo: list[str] = []
        for p in all_repo:
            if p not in seen:
                seen.add(p)
                deduped_repo.append(p)

        needs_aur = self._aur_enabled and (aur_pkgs or True)  # always offer if toggled

        # Nothing selected at all?
        if not repo_pkgs and not aur_pkgs and not appimage_pkgs and not icon_pkgs:
            # Check if at least base packages differ from installed
            new_repo = [p for p in deduped_repo if p not in self._installed]
            if not new_repo and not aur_pkgs and not appimage_pkgs:
                return None

        stages: list[object] = []

        # ── Stage 1: Privileged — pacman install base + repo ──
        priv_tasks: list[PrivilegedTask] = []
        cores = os.cpu_count() or 1
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
                helper = detect_aur_helper() or aur_mod.install_aur_helper(_helper, logger=logger)
                if not helper:
                    logger.warn("Nenhum AUR helper disponível. Pacotes AUR não instalados.")
                    return
                # Install electron29-bin as base AUR dependency
                aur_mod.install_electron29_bin(helper=helper, logger=logger)
                if _pkgs:
                    aur_mod.aur_install(_pkgs, helper=helper, logger=logger)

            stages.append(
                UserStep(
                    title=f"AUR: electron29-bin + {len(aur_pkgs)} pacote(s)",
                    fn=_aur_stage,
                )
            )

        # ── Stage 3 (optional): User — AppImages ──
        if appimage_pkgs:
            def _appimage_stage(logger: TaskLogger, _pkgs: list[str] = appimage_pkgs) -> None:
                total = len(_pkgs)
                for i, pkg_name in enumerate(_pkgs, 1):
                    logger.set_progress((i - 1) / total, f"AppImage {i}/{total}: {pkg_name}")
                    installer = appimages_mod.APPIMAGE_INSTALLERS.get(pkg_name)
                    if installer:
                        ok = installer(logger)
                        if not ok:
                            logger.warn(f"Falha ao instalar AppImage: {pkg_name}")
                    else:
                        logger.warn(f"Sem instalador para AppImage: {pkg_name}")

            stages.append(
                UserStep(
                    title=f"AppImages ({', '.join(appimage_pkgs)})",
                    fn=_appimage_stage,
                )
            )

        return ExecutionPlan(
            title="Pós-formatação & Pacotes",
            stages=stages,
        )
