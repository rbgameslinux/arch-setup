"""Main application window using Adw.NavigationSplitView."""

from __future__ import annotations

from gi.repository import Adw, Gio, Gtk

from arch_setup import APP_NAME
from arch_setup.backend.runner import (
    ExecutionPlan,
    PrivilegedBatch,
    PrivilegedTask,
    TaskLogger,
    UserStep,
)
from arch_setup.models.catalog import NAV_SECTIONS, NavSection, detect_environment_summary
from arch_setup.ui.execution_dialog import ExecutionDialog
from arch_setup.ui.pages.fixes import FixesPage
from arch_setup.ui.pages.packages import PackagesPage
from arch_setup.ui.pages.services import ServicesPage
from arch_setup.ui.pages.system import SystemPage
from arch_setup.ui.pages.wallpapers import WallpapersPage


class ArchSetupWindow(Adw.ApplicationWindow):
    """Primary window with sidebar navigation and stacked pages."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1020, 700)
        self.set_size_request(680, 480)

        self._sections_by_key: dict[str, NavSection] = {
            sec.key: sec for sec in NAV_SECTIONS
        }
        self._overview_rows: dict[str, Adw.ActionRow] = {}

        self._build_ui()
        self._refresh_overview()

    def _build_ui(self) -> None:
        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_min_sidebar_width(240)
        self._split_view.set_max_sidebar_width(300)

        breakpoint_narrow = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 740sp")
        )
        breakpoint_narrow.add_setter(self._split_view, "collapsed", True)
        self.add_breakpoint(breakpoint_narrow)

        sidebar_page = self._build_sidebar()
        content_page = self._build_content()

        self._split_view.set_sidebar(sidebar_page)
        self._split_view.set_content(content_page)
        self.set_content(self._split_view)

        first_row = self._sidebar_list.get_row_at_index(0)
        if first_row is not None:
            self._sidebar_list.select_row(first_row)

    def _build_sidebar(self) -> Adw.NavigationPage:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        menu_model = Gio.Menu()
        menu_model.append("Sobre o Arch Setup", "app.about")
        menu_model.append("Sair", "app.quit")

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu_model)
        menu_button.set_tooltip_text("Menu principal")
        header.pack_end(menu_button)

        toolbar.add_top_bar(header)

        self._sidebar_list = Gtk.ListBox()
        self._sidebar_list.add_css_class("navigation-sidebar")
        self._sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._sidebar_list.connect("row-selected", self._on_sidebar_row_selected)

        for section in NAV_SECTIONS:
            row = Gtk.ListBoxRow()
            row.section_key = section.key  # type: ignore[attr-defined]

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(10)
            box.set_margin_bottom(10)
            box.set_margin_start(8)
            box.set_margin_end(8)

            icon = Gtk.Image.new_from_icon_name(section.icon_name)
            box.append(icon)

            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=section.title)
            title.set_xalign(0.0)
            labels.append(title)

            subtitle = Gtk.Label(label=section.subtitle)
            subtitle.set_xalign(0.0)
            subtitle.set_ellipsize(3)
            subtitle.add_css_class("dim-label")
            subtitle.add_css_class("caption")
            labels.append(subtitle)

            box.append(labels)
            row.set_child(box)
            self._sidebar_list.append(row)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self._sidebar_list)
        toolbar.set_content(scrolled)

        return Adw.NavigationPage.new(toolbar, APP_NAME)

    def _build_content(self) -> Adw.NavigationPage:
        toolbar = Adw.ToolbarView()
        self._content_header = Adw.HeaderBar()

        self._refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._refresh_button.set_tooltip_text("Atualizar detecção desta página")
        self._refresh_button.connect("clicked", lambda *_: self._refresh_current_page())
        self._content_header.pack_end(self._refresh_button)

        toolbar.add_top_bar(self._content_header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._build_overview_page(), "overview")

        # ── Páginas funcionais ──
        self._pages: dict[str, Adw.PreferencesPage] = {
            "packages": PackagesPage(),
            "system": SystemPage(),
            "services": ServicesPage(),
            "fixes": FixesPage(),
            "wallpapers": WallpapersPage(),
        }
        for key, page in self._pages.items():
            self._stack.add_named(page, key)

        toolbar.set_content(self._stack)
        self._content_page = Adw.NavigationPage.new(toolbar, "Visão Geral")
        return self._content_page

    def _build_overview_page(self) -> Gtk.Widget:
        prefs_page = Adw.PreferencesPage()

        hero_group = Adw.PreferencesGroup(
            title="Teste do motor de execução",
            description=(
                "Ambiente detectado automaticamente. Use o botão de teste para validar "
                "o worker privilegiado (dry-run), barra de progresso e log ao vivo."
            ),
        )

        test_row = Adw.ActionRow(
            title="Testar motor de execução (Dry-Run)",
            subtitle="Simula lote privilegiado + etapa de usuário sem alterar o sistema",
        )
        test_btn = Gtk.Button(label="Executar teste")
        test_btn.add_css_class("suggested-action")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect("clicked", self._on_run_foundation_test)
        test_row.add_suffix(test_btn)
        hero_group.add(test_row)
        prefs_page.add(hero_group)

        sys_group = Adw.PreferencesGroup(title="Estado detectado do sistema")
        row_defs = (
            ("cpu", "Processador (MAKEFLAGS)", "Detectando..."),
            ("aur", "Helper AUR", "Detectando..."),
            ("base_pkgs", "Pacotes base de pós-formatação", "Detectando..."),
            ("niri", "Compositor Wayland (niri)", "Detectando..."),
            ("resolve", "DaVinci Resolve", "Detectando..."),
            ("zapzap_fix", "Fix Microfone ZapZap", "Detectando..."),
            ("wallpapers", "Pasta ~/Wallpapers", "Detectando..."),
        )
        for key, title, subtitle in row_defs:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            self._overview_rows[key] = row
            sys_group.add(row)
        prefs_page.add(sys_group)

        return prefs_page

    def _refresh_overview(self) -> None:
        summary = detect_environment_summary()
        cores = summary["cpu_cores"]
        aur = summary["aur_helper"]
        base_ok = summary["base_installed_count"]
        base_total = summary["base_total_count"]
        total_pkgs = summary["total_installed_packages"]

        self._overview_rows["cpu"].set_subtitle(
            f"{cores} thread(s) detectadas (MAKEFLAGS=\"-j{cores}\")"
        )
        self._overview_rows["aur"].set_subtitle(
            f"Encontrado: {aur}" if aur else "Nenhum instalado (paru/yay na página Pós-formatação)"
        )
        self._overview_rows["base_pkgs"].set_subtitle(
            f"{base_ok} de {base_total} pacotes base instalados ({total_pkgs} pacotes no sistema)"
        )
        self._overview_rows["niri"].set_subtitle(
            "Instalado no PATH" if summary["has_niri"] else "Não detectado"
        )

        if summary["has_resolve"]:
            wrapper_msg = (
                "wrapper instalado"
                if summary["has_resolve_wrapper"]
                else "wrapper ainda não instalado"
            )
            self._overview_rows["resolve"].set_subtitle(
                f"Instalado em /opt/resolve ({wrapper_msg})"
            )
        else:
            self._overview_rows["resolve"].set_subtitle("Não encontrado em /opt/resolve")

        self._overview_rows["zapzap_fix"].set_subtitle(
            "Regra PipeWire presente"
            if summary["has_zapzap_fix"]
            else "Não configurado"
        )
        self._overview_rows["wallpapers"].set_subtitle(
            "Diretório ~/Wallpapers existente"
            if summary["has_wallpapers"]
            else "Ainda não baixado"
        )

    def _on_sidebar_row_selected(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if row is None:
            return
        key = getattr(row, "section_key", "overview")
        section = self._sections_by_key.get(key)
        self._stack.set_visible_child_name(key)
        if section is not None:
            self._content_page.set_title(section.title)
        self._refresh_button.set_visible(True)
        if self._split_view.get_collapsed():
            self._split_view.set_show_content(True)

    def _refresh_current_page(self) -> None:
        """Re-run the environment detection of the currently visible page."""
        key = self._stack.get_visible_child_name()
        if key == "overview":
            self._refresh_overview()
            return
        page = self._pages.get(key or "")
        refresh = getattr(page, "_refresh_state", None)
        if callable(refresh):
            refresh()

    def _on_run_foundation_test(self, _button: Gtk.Button) -> None:
        summary = detect_environment_summary()
        cores = int(summary["cpu_cores"])  # type: ignore[arg-type]

        def _user_check(logger: TaskLogger) -> None:
            logger.info("Validando etapa em espaço de usuário...")
            logger.set_progress(0.75, "Verificando comandos locais")
            logger.run_command(["uname", "-srm"])
            logger.info("Etapa de usuário concluída.")

        plan = ExecutionPlan(
            title="Teste de Fundação (Dry-Run)",
            stages=[
                PrivilegedBatch(
                    title="Simulação do worker privilegiado",
                    dry_run=True,
                    tasks=[
                        PrivilegedTask(
                            action="noop_check",
                            label="Validando manifesto JSON do worker",
                            params={"message": "Manifesto válido"},
                        ),
                        PrivilegedTask(
                            action="configure_makepkg_jobs",
                            label=f"Simulando MAKEFLAGS=-j{cores}",
                            params={"cores": cores},
                        ),
                        PrivilegedTask(
                            action="configure_env",
                            label="Simulando configuração de /etc/environment",
                        ),
                    ],
                ),
                UserStep(
                    title="Verificação em espaço de usuário",
                    fn=_user_check,
                ),
            ],
        )

        dialog = ExecutionDialog(plan)
        dialog.start(self, on_complete=lambda _ok: self._refresh_overview())
