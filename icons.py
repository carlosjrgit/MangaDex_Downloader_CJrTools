"""
Sistema de Ícones Phosphor Icons para CJ Manga Downloader.
Segue o Design System:
- Biblioteca: Phosphor Icons
- Peso Padrão: Regular
- Peso Ativo/Selecionado: Fill
- Tamanhos Padrão: 16px, 20px, 24px (padrão), 32px, 48px
- Cores dinâmicas vetoriais em alta fidelidade.
"""

import sys
from pathlib import Path
import re
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

# Diretório base dos ícones (compatível com execução via script e binário PyInstaller)
_BASE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
_ASSETS_DIR = _BASE_DIR / "assets" / "icons"

# Mapeamento de apelidos para os arquivos Phosphor
ICON_ALIASES: Dict[str, str] = {
    "add": "plus",
    "plus": "plus",
    "txt": "file-text",
    "file": "file-text",
    "import": "file-text",
    "folder": "folder-open",
    "folder-open": "folder-open",
    "play": "play",
    "start": "play",
    "pause": "pause",
    "stop": "stop",
    "delete": "trash",
    "trash": "trash",
    "clean": "broom",
    "clear": "broom",
    "broom": "broom",
    "settings": "gear",
    "gear": "gear",
    "info": "info",
    "about": "info",
    "question": "question",
    "help": "question",
    "book": "book-open",
    "manga": "book-open",
    "download": "download-simple",
    "check": "check",
    "check-circle": "check-circle",
    "success": "check-circle",
    "warning": "warning",
    "warning-circle": "warning-circle",
    "error": "x-circle",
    "x-circle": "x-circle",
    "close": "x",
    "x": "x",
    "speed": "lightning",
    "lightning": "lightning",
    "clock": "clock",
    "time": "clock",
    "storage": "hard-drive",
    "hard-drive": "hard-drive",
    "terminal": "terminal-window",
    "console": "terminal-window",
    "refresh": "arrows-clockwise",
    "search": "magnifying-glass",
}

_SVG_RAW_CACHE: Dict[Tuple[str, str], str] = {}
_ICON_CACHE: Dict[Tuple[str, str, int, str], QIcon] = {}
_PIXMAP_CACHE: Dict[Tuple[str, str, int, str], QPixmap] = {}


def _resolve_icon_path(name: str, weight: str = "regular") -> Optional[Path]:
    """Localiza o arquivo SVG para o nome e peso especificados."""
    clean_name = ICON_ALIASES.get(name, name.replace("_", "-"))
    weight_dir = "fill" if weight == "fill" else "regular"
    filename = f"{clean_name}-fill.svg" if weight == "fill" else f"{clean_name}.svg"

    icon_path = _ASSETS_DIR / weight_dir / filename
    if icon_path.is_file():
        return icon_path

    # Fallback para o outro peso caso não encontre
    alt_dir = "regular" if weight == "fill" else "fill"
    alt_filename = f"{clean_name}.svg" if alt_dir == "regular" else f"{clean_name}-fill.svg"
    alt_path = _ASSETS_DIR / alt_dir / alt_filename
    if alt_path.is_file():
        return alt_path

    return None


def _colorize_svg(svg_content: str, color: str) -> str:
    """Aplica a cor desejada no SVG."""
    return svg_content.replace("currentColor", color)


def get_pixmap(
    name: str,
    color: str = "#F0F0F0",
    size: int = 24,
    weight: str = "regular"
) -> QPixmap:
    """Retorna um QPixmap renderizado em vetor com a cor e tamanho definidos."""
    cache_key = (name, color, size, weight)
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]

    raw_key = (name, weight)
    if raw_key not in _SVG_RAW_CACHE:
        path = _resolve_icon_path(name, weight)
        if not path:
            pix = QPixmap(size, size)
            pix.fill(Qt.transparent)
            _PIXMAP_CACHE[cache_key] = pix
            return pix
        try:
            with open(path, "r", encoding="utf-8") as f:
                _SVG_RAW_CACHE[raw_key] = f.read()
        except Exception:
            pix = QPixmap(size, size)
            pix.fill(Qt.transparent)
            _PIXMAP_CACHE[cache_key] = pix
            return pix

    colored_svg = _colorize_svg(_SVG_RAW_CACHE[raw_key], color)
    renderer = QSvgRenderer(QByteArray(colored_svg.encode("utf-8")))

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()

    _PIXMAP_CACHE[cache_key] = pix
    return pix


def get_icon(
    name: str,
    color: str = "#F0F0F0",
    size: int = 24,
    weight: str = "regular",
    active_color: Optional[str] = None
) -> QIcon:
    """Retorna um QIcon com suporte a estado normal e ativo."""
    cache_key = (name, f"{color}:{active_color}", size, weight)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    pix_normal = get_pixmap(name, color=color, size=size, weight=weight)
    icon = QIcon(pix_normal)

    # Adiciona variante ativa se fornecida (por padrão #FFAC2B com peso fill)
    if active_color:
        pix_active = get_pixmap(name, color=active_color, size=size, weight="fill")
        icon.addPixmap(pix_active, QIcon.Active, QIcon.On)
        icon.addPixmap(pix_active, QIcon.Selected, QIcon.On)

    _ICON_CACHE[cache_key] = icon
    return icon
