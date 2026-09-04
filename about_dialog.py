"""
Diálogo "Sobre" oficial do CJ Manga Downloader.
Segue rigorosamente o Design System:
- Exibe o card vitrine em fundo branco (#FFFFFF) para a logo CJR DOOM garantindo nitidez e contraste perfeitos.
- Textos oficiais:
    CJ Manga Downloader
    Version 1.0.0

    Designed and developed by
    CJRDOOM

    © 2026 Carlos Junior
"""

import sys
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from icons import get_icon
from styles import (
    COLOR_ACCENT,
    COLOR_BACKGROUND,
    COLOR_BORDER_STRONG,
    COLOR_BORDER_SUBTLE,
    COLOR_SURFACE,
    COLOR_SURFACE_ELEVATED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    DARK_THEME,
    FONT_MONOSPACE,
    FONT_PRIMARY,
    RADIUS_DEFAULT
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre — CJ Manga Downloader")
        self.setFixedSize(460, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(DARK_THEME)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)
        main_layout.setAlignment(Qt.AlignCenter)

        # --------------------------------------------------------------
        # 1. Card Vitrine da Logomarca (Alto Contraste: Fundo Branco)
        # --------------------------------------------------------------
        logo_card = QFrame()
        logo_card.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border: 1px solid {COLOR_BORDER_STRONG};
                border-radius: {RADIUS_DEFAULT};
                padding: 10px;
            }}
        """)
        logo_card_layout = QVBoxLayout(logo_card)
        logo_card_layout.setContentsMargins(8, 8, 8, 8)
        logo_card_layout.setAlignment(Qt.AlignCenter)

        lbl_logo = QLabel()
        lbl_logo.setAlignment(Qt.AlignCenter)
        base_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
        logo_path = base_dir / "assets" / "logo.png"

        if logo_path.is_file():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                lbl_logo.setPixmap(
                    pix.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        if not lbl_logo.pixmap():
            lbl_logo.setText("CJR DOOM")
            lbl_logo.setStyleSheet("color: #1A1A1A; font-weight: bold; font-size: 20px;")

        logo_card_layout.addWidget(lbl_logo)
        main_layout.addWidget(logo_card, 0, Qt.AlignCenter)

        # --------------------------------------------------------------
        # 2. Informações e Textos Oficiais
        # --------------------------------------------------------------
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 4, 0, 4)
        info_layout.setSpacing(6)
        info_layout.setAlignment(Qt.AlignCenter)

        lbl_title = QLabel("CJ Manga Downloader")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 600;
            color: {COLOR_TEXT_PRIMARY};
            letter-spacing: 0.5px;
        """)

        lbl_version = QLabel("Version 1.0.0")
        lbl_version.setAlignment(Qt.AlignCenter)
        lbl_version.setStyleSheet(f"""
            font-family: {FONT_MONOSPACE};
            font-size: 13px;
            font-weight: 500;
            color: {COLOR_ACCENT};
        """)

        # Divisor sutil de 1px
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {COLOR_BORDER_SUBTLE}; margin: 8px 0;")

        lbl_designed_by = QLabel("Designed and developed by")
        lbl_designed_by.setAlignment(Qt.AlignCenter)
        lbl_designed_by.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 400;
            color: {COLOR_TEXT_SECONDARY};
        """)

        lbl_author = QLabel("CJRDOOM")
        lbl_author.setAlignment(Qt.AlignCenter)
        lbl_author.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 600;
            color: {COLOR_TEXT_PRIMARY};
            letter-spacing: 1px;
        """)

        lbl_copyright = QLabel("© 2026 Carlos Junior")
        lbl_copyright.setAlignment(Qt.AlignCenter)
        lbl_copyright.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 400;
            color: {COLOR_TEXT_DISABLED};
            margin-top: 4px;
        """)

        info_layout.addWidget(lbl_title)
        info_layout.addWidget(lbl_version)
        info_layout.addWidget(divider)
        info_layout.addWidget(lbl_designed_by)
        info_layout.addWidget(lbl_author)
        info_layout.addWidget(lbl_copyright)

        main_layout.addWidget(info_widget)

        # --------------------------------------------------------------
        # 3. Botão de Fechamento Plano e Geométrico
        # --------------------------------------------------------------
        btn_close = QPushButton("Fechar")
        btn_close.setIcon(get_icon("x", color=COLOR_TEXT_PRIMARY, size=16))
        btn_close.setMinimumWidth(110)
        btn_close.setMinimumHeight(32)
        btn_close.clicked.connect(self.accept)

        btn_box = QHBoxLayout()
        btn_box.setAlignment(Qt.AlignCenter)
        btn_box.addWidget(btn_close)
        main_layout.addLayout(btn_box)
