"""Runtime localization helpers for UI strings."""

LANGUAGE_LABELS = {
    "en": "English",
    "es": "Spanish",
}

CATALOGS = {
    "es": {
        "search.placeholder": "Buscar archivos y carpetas...",
        "tab.search": "Buscar",
        "menu.file": "Archivo",
        "menu.file.new_tab": "Nueva pestana",
        "menu.file.close_tab": "Cerrar pestana",
        "menu.file.new_window": "Nueva ventana",
        "menu.file.open_efu": "Abrir lista de archivos",
        "menu.file.export_efu": "Exportar resultados",
        "menu.file.exit": "Salir",
        "menu.edit": "Editar",
        "menu.edit.select_all": "Seleccionar todo",
        "menu.edit.copy_path": "Copiar ruta",
        "menu.edit.copy_name": "Copiar nombre",
        "menu.view": "Vista",
        "menu.view.details": "Detalles",
        "menu.view.thumbnails": "Miniaturas",
        "menu.view.columns": "Columnas",
        "menu.view.preview_pane": "Panel de vista previa",
        "menu.view.bookmarks": "Panel de marcadores",
        "menu.view.status_bar": "Barra de estado",
        "menu.search": "Buscar",
        "menu.search.focus": "Enfocar busqueda",
        "menu.search.match_case": "Coincidir mayusculas",
        "menu.search.regex": "Regex",
        "menu.search.match_path": "Coincidir ruta",
        "menu.search.whole_word": "Palabra completa",
        "menu.search.clear_history": "Borrar historial de busqueda",
        "menu.search.filter": "Filtro",
        "menu.search.manage_filters": "Administrar filtros",
        "menu.search.tab_switcher": "Cambiar pestana",
        "menu.search.import_filters": "Importar filtros de Everything",
        "menu.search.export_filters": "Exportar filtros a CSV",
        "menu.bookmarks": "Marcadores",
        "menu.bookmarks.add": "Agregar marcador",
        "menu.bookmarks.manage": "Administrar marcadores",
        "menu.bookmarks.import": "Importar marcadores de Everything",
        "menu.bookmarks.export": "Exportar marcadores a CSV",
        "menu.tools": "Herramientas",
        "menu.tools.rebuild_index": "Reconstruir indice",
        "menu.tools.start_content_index": "Iniciar indexado de contenido",
        "menu.tools.stop_content_index": "Detener indexado de contenido",
        "menu.tools.settings": "Configuracion",
        "menu.tools.diagnostics": "Diagnosticos",
        "menu.tools.hidden_paths": "Administrar rutas ocultas",
        "menu.help": "Ayuda",
        "menu.help.syntax": "Ayuda de sintaxis",
        "menu.help.about": "Acerca de QuickFind",
        "status.select_result_preview": "Seleccione un resultado para vista previa",
        "settings.language": "Idioma:",
    }
}

_active_language = "en"


def available_languages() -> tuple[tuple[str, str], ...]:
    return tuple((code, LANGUAGE_LABELS[code]) for code in LANGUAGE_LABELS)


def normalize_language(code: str) -> str:
    return code if isinstance(code, str) and code in LANGUAGE_LABELS else "en"


def set_language(code: str) -> str:
    global _active_language
    _active_language = normalize_language(code)
    return _active_language


def active_language() -> str:
    return _active_language


def translate(key: str, default: str | None = None, **values) -> str:
    text = CATALOGS.get(_active_language, {}).get(key, default if default is not None else key)
    if values:
        try:
            return text.format(**values)
        except (KeyError, ValueError):
            return text
    return text


def tr(key: str, default: str | None = None, **values) -> str:
    return translate(key, default, **values)
