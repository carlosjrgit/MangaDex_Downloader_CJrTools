"""
Implementação Oficial do Design System para MangaDex_Downloader_CJrTools.
Direção Visual: Dark, Minimal, Flat, Geometric, Technical.
Princípio Visual: Flat, not plain.
"""

# =============================================================================
# DESIGN TOKENS
# =============================================================================

# Cores de Superfície e Fundo
COLOR_BACKGROUND = "#2E2D2D"
COLOR_SURFACE = "#363535"
COLOR_SURFACE_ELEVATED = "#3D3C3C"
COLOR_SURFACE_ACTIVE = "#454444"
COLOR_SURFACE_DISABLED = "#303030"

# Destaque / Identidade Visual
COLOR_ACCENT = "#FFAC2B"
COLOR_ACCENT_HOVER = "#FFB74D"
COLOR_ACCENT_PRESSED = "#E6951A"

# Bordas e Linhas
COLOR_BORDER_STRONG = "#9E9E9E"
COLOR_BORDER_SUBTLE = "#4A4949"

# Tipografia
COLOR_TEXT_PRIMARY = "#F0F0F0"
COLOR_TEXT_SECONDARY = "#BDBDBD"
COLOR_TEXT_DISABLED = "#666666"

# Cores Semânticas
COLOR_SUCCESS = "#22C55E"
COLOR_WARNING = "#F59E0B"
COLOR_ERROR = "#EF4444"
COLOR_INFO = "#38BDF8"

# Famílias Tipográficas
FONT_PRIMARY = 'Inter, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
FONT_MONOSPACE = '"JetBrains Mono", "Cascadia Code", Consolas, "Courier New", monospace'

# Raio e Geometria
RADIUS_DEFAULT = "4px"
RADIUS_SECONDARY = "2px"
BORDER_WIDTH_DEFAULT = "1px"


# =============================================================================
# FOLHA DE ESTILOS QSS OFICIAL (DARK, MINIMAL, FLAT, GEOMETRIC)
# =============================================================================
DARK_THEME = f"""
/* Reset Geral e Tipografia Base */
QWidget {{
    background-color: {COLOR_BACKGROUND};
    color: {COLOR_TEXT_PRIMARY};
    font-family: {FONT_PRIMARY};
    font-size: 14px;
    font-weight: 400;
    selection-background-color: {COLOR_SURFACE_ACTIVE};
    selection-color: {COLOR_TEXT_PRIMARY};
}}

QLabel {{
    background-color: transparent;
    color: {COLOR_TEXT_PRIMARY};
    padding: 0px;
}}

QMainWindow, QDialog {{
    background-color: {COLOR_BACKGROUND};
}}

/* Barra de Cabeçalho Oficial (Surface) */
#HeaderBar {{
    background-color: {COLOR_SURFACE};
    border-bottom: 1px solid {COLOR_BORDER_SUBTLE};
    padding: 8px 16px;
}}

#HeaderTitle {{
    font-size: 18px;
    font-weight: 600;
    color: {COLOR_TEXT_PRIMARY};
    letter-spacing: 0.5px;
}}

#HeaderBadge {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_ACCENT};
    font-family: {FONT_MONOSPACE};
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: {RADIUS_SECONDARY};
    border: 1px solid {COLOR_BORDER_SUBTLE};
}}

/* GroupBox Plano e Geométrico */
QGroupBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
    font-size: 13px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 4px;
    padding: 0 6px;
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
}}

/* Campos de Entrada (Inputs) */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLOR_BACKGROUND};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    padding: 6px 8px;
    font-size: 13px;
    selection-background-color: {COLOR_SURFACE_ACTIVE};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border: 1px solid {COLOR_BORDER_STRONG};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
    background-color: {COLOR_BACKGROUND};
}}

QLineEdit:disabled, QTextEdit:disabled {{
    background-color: {COLOR_SURFACE_DISABLED};
    color: {COLOR_TEXT_DISABLED};
    border: 1px solid {COLOR_SURFACE_DISABLED};
}}

/* ComboBox Geométrico */
QComboBox {{
    background-color: {COLOR_BACKGROUND};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    padding: 6px 10px;
    font-size: 13px;
    min-height: 20px;
}}

QComboBox:hover {{
    border: 1px solid {COLOR_BORDER_STRONG};
}}

QComboBox:focus {{
    border: 1px solid {COLOR_ACCENT};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {COLOR_BORDER_SUBTLE};
    background-color: {COLOR_SURFACE};
    border-top-right-radius: {RADIUS_DEFAULT};
    border-bottom-right-radius: {RADIUS_DEFAULT};
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    selection-background-color: {COLOR_SURFACE_ACTIVE};
    selection-color: {COLOR_TEXT_PRIMARY};
    padding: 4px;
    outline: none;
}}

/* Botões do Sistema (Flat, Retos, Altura 32px/36px) */
QPushButton {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {COLOR_SURFACE_ACTIVE};
    border: 1px solid {COLOR_BORDER_STRONG};
}}

QPushButton:pressed {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_ACCENT};
}}

QPushButton:focus {{
    border: 1px solid {COLOR_ACCENT};
    outline: none;
}}

QPushButton:disabled {{
    background-color: {COLOR_SURFACE_DISABLED};
    color: {COLOR_TEXT_DISABLED};
    border: 1px solid {COLOR_SURFACE_DISABLED};
}}

/* Botão Primário com Destaque #FFAC2B */
QPushButton#PrimaryBtn {{
    background-color: {COLOR_ACCENT};
    color: #1A1A1A;
    border: 1px solid {COLOR_ACCENT};
    font-weight: 600;
}}

QPushButton#PrimaryBtn:hover {{
    background-color: {COLOR_ACCENT_HOVER};
    border: 1px solid {COLOR_ACCENT_HOVER};
}}

QPushButton#PrimaryBtn:pressed {{
    background-color: {COLOR_ACCENT_PRESSED};
    border: 1px solid {COLOR_ACCENT_PRESSED};
}}

QPushButton#PrimaryBtn:disabled {{
    background-color: {COLOR_SURFACE_DISABLED};
    color: {COLOR_TEXT_DISABLED};
    border: 1px solid {COLOR_SURFACE_DISABLED};
}}

/* Botão Secundário / Ação Rápida */
QPushButton#SecondaryBtn {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER_SUBTLE};
}}

/* Botão Ícone Compacto (Toolbar e Header) */
QPushButton#IconBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_DEFAULT};
    padding: 4px;
    min-width: 28px;
    min-height: 28px;
}}

QPushButton#IconBtn:hover {{
    background-color: {COLOR_SURFACE_ACTIVE};
    border: 1px solid {COLOR_BORDER_SUBTLE};
}}

QPushButton#IconBtn:pressed {{
    background-color: {COLOR_SURFACE};
}}

/* CheckBoxes Geométricos */
QCheckBox {{
    spacing: 8px;
    font-size: 13px;
    color: {COLOR_TEXT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_SECONDARY};
    background-color: {COLOR_BACKGROUND};
}}

QCheckBox::indicator:hover {{
    border: 1px solid {COLOR_BORDER_STRONG};
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT};
    border: 1px solid {COLOR_ACCENT};
}}

QCheckBox::indicator:disabled {{
    background-color: {COLOR_SURFACE_DISABLED};
    border: 1px solid {COLOR_SURFACE_DISABLED};
}}

/* Tabela Minimalista e Técnica (Queue Table) */
QTableWidget {{
    background-color: {COLOR_BACKGROUND};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    gridline-color: {COLOR_BORDER_SUBTLE};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    outline: none;
}}

QTableWidget:focus {{
    border: 1px solid {COLOR_BORDER_STRONG};
}}

QTableWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {COLOR_BORDER_SUBTLE};
}}

QTableWidget::item:hover {{
    background-color: {COLOR_SURFACE};
}}

QTableWidget::item:selected {{
    background-color: {COLOR_SURFACE_ACTIVE};
    color: {COLOR_TEXT_PRIMARY};
}}

QHeaderView::section {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER_STRONG};
    border-right: 1px solid {COLOR_BORDER_SUBTLE};
}}

QTableCornerButton::section {{
    background-color: {COLOR_SURFACE};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER_STRONG};
}}

/* Barras de Progresso Retas */
QProgressBar {{
    background-color: {COLOR_BACKGROUND};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_SECONDARY};
    text-align: center;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 11px;
    font-weight: 600;
    font-family: {FONT_MONOSPACE};
    min-height: 16px;
}}

QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 1px;
}}

/* Dashboard de Estatísticas Técnicas */
#MetricFrame {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    padding: 6px 12px;
}}

#MetricLabel {{
    font-family: {FONT_MONOSPACE};
    font-size: 12px;
    font-weight: 500;
    color: {COLOR_TEXT_PRIMARY};
}}

#MetricAccent {{
    font-family: {FONT_MONOSPACE};
    font-size: 12px;
    font-weight: 600;
    color: {COLOR_ACCENT};
}}

/* Terminal de Logs com Aparência Técnica */
#LogConsole {{
    background-color: #242323;
    color: {COLOR_TEXT_SECONDARY};
    font-family: {FONT_MONOSPACE};
    font-size: 12px;
    line-height: 1.4;
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
    padding: 8px;
}}

/* Menus de Contexto */
QMenu {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_STRONG};
    border-radius: {RADIUS_DEFAULT};
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 20px 6px 12px;
    border-radius: {RADIUS_SECONDARY};
}}

QMenu::item:selected {{
    background-color: {COLOR_SURFACE_ACTIVE};
    color: {COLOR_ACCENT};
}}

QMenu::separator {{
    height: 1px;
    background-color: {COLOR_BORDER_SUBTLE};
    margin: 4px 6px;
}}

/* Tooltips */
QToolTip {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER_STRONG};
    border-radius: {RADIUS_DEFAULT};
    padding: 6px 10px;
    font-family: {FONT_PRIMARY};
    font-size: 12px;
}}

/* ======================================================================
   Barras de Rolagem com Design Inteligente e Cor Sólida de Alto Contraste
   ====================================================================== */
QScrollBar:vertical {{
    background-color: #161616;
    width: 12px;
    margin: 2px;
    border-radius: 6px;
    border: 1px solid #242424;
}}

QScrollBar::handle:vertical {{
    background-color: #3C3C3C;
    min-height: 28px;
    border-radius: 4px;
    border: none;
}}

QScrollBar::handle:vertical:hover {{
    background-color: #555555;
}}

QScrollBar::handle:vertical:pressed {{
    background-color: {COLOR_ACCENT};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: transparent;
    border: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background-color: #161616;
    height: 12px;
    margin: 2px;
    border-radius: 6px;
    border: 1px solid #242424;
}}

QScrollBar::handle:horizontal {{
    background-color: #3C3C3C;
    min-width: 28px;
    border-radius: 4px;
    border: none;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: #555555;
}}

QScrollBar::handle:horizontal:pressed {{
    background-color: {COLOR_ACCENT};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    background: transparent;
    border: none;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

QAbstractScrollArea::corner {{
    background-color: #161616;
    border: none;
}}

/* Card de Análise Prévia da Obra */
QFrame#AnalysisCard {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_DEFAULT};
}}

QLabel#AnalysisTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 700;
}}

QLabel#BadgeProvider {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_ACCENT};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-radius: {RADIUS_SECONDARY};
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#ChapsBadge {{
    color: {COLOR_ACCENT};
    font-weight: 600;
    font-size: 13px;
}}

/* Abas Principais (QTabWidget & QTabBar) */
QTabWidget::pane {{
    background-color: {COLOR_BACKGROUND};
    border-top: 1px solid {COLOR_BORDER_SUBTLE};
    border-left: none;
    border-right: none;
    border-bottom: none;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_SECONDARY};
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 500;
    border-top-left-radius: {RADIUS_DEFAULT};
    border-top-right-radius: {RADIUS_DEFAULT};
    border: 1px solid {COLOR_BORDER_SUBTLE};
    border-bottom: none;
    margin-right: 4px;
}}

QTabBar::tab:hover {{
    background-color: {COLOR_SURFACE_ACTIVE};
    color: {COLOR_TEXT_PRIMARY};
}}

QTabBar::tab:selected {{
    background-color: {COLOR_SURFACE_ELEVATED};
    color: {COLOR_ACCENT};
    font-weight: 600;
    border-top: 2px solid {COLOR_ACCENT};
    border-left: 1px solid {COLOR_BORDER_STRONG};
    border-right: 1px solid {COLOR_BORDER_STRONG};
}}

/* Divisores de Painel (QSplitter) */
QSplitter::handle {{
    background-color: {COLOR_BORDER_SUBTLE};
}}

QSplitter::handle:hover {{
    background-color: {COLOR_ACCENT};
}}
"""
