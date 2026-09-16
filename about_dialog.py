"""
about_dialog.py - Diálogo "Sobre" oficial do MangaHubRip_CJrTools.
Segue rigorosamente o Design System:
- Estética: Dark, Minimal, Flat, Geometric, Technical.
- Exibe o card vitrine em fundo branco (#FFFFFF) para a logo CJR DOOM garantindo nitidez e contraste perfeitos.
- Textos oficiais:
    MangaHubRip_CJrTools
    Version 2.0.0

    Descrição completa da suíte desktop

    Designed and developed by
    CJRDOOM

    © 2026 Carlos Junior
"""

import sys
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from icons import get_icon
from styles import (
    COLOR_ACCENT,
    COLOR_BORDER_STRONG,
    COLOR_BORDER_SUBTLE,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    DARK_THEME,
    FONT_MONOSPACE,
    RADIUS_DEFAULT
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre — MangaHubRip_CJrTools")
        self.setMinimumSize(480, 560)
        self.resize(520, 640)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(DARK_THEME)

        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # ScrollArea responsiva para garantir que nunca haja sobreposição em telas pequenas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 8, 16, 8)
        container_layout.setSpacing(14)
        container_layout.setAlignment(Qt.AlignCenter)

        # --------------------------------------------------------------
        # 1. Card Vitrine da Logomarca (Alto Contraste: Fundo Branco)
        # --------------------------------------------------------------
        logo_card = QFrame()
        logo_card.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border: 1px solid {COLOR_BORDER_STRONG};
                border-radius: {RADIUS_DEFAULT};
                padding: 6px;
            }}
        """)
        logo_card_layout = QVBoxLayout(logo_card)
        logo_card_layout.setContentsMargins(6, 6, 6, 6)
        logo_card_layout.setAlignment(Qt.AlignCenter)

        lbl_logo = QLabel()
        lbl_logo.setAlignment(Qt.AlignCenter)
        base_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
        
        # Procura logo.png ou logo.jpg
        logo_path = base_dir / "assets" / "logo.png"
        if not logo_path.is_file():
            logo_path = base_dir / "assets" / "logo.jpg"

        if logo_path.is_file():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                lbl_logo.setPixmap(
                    pix.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        if not lbl_logo.pixmap():
            lbl_logo.setText("CJR DOOM")
            lbl_logo.setStyleSheet("color: #1A1A1A; font-weight: bold; font-size: 20px;")

        logo_card_layout.addWidget(lbl_logo)
        container_layout.addWidget(logo_card, 0, Qt.AlignCenter)

        # --------------------------------------------------------------
        # 2. Informações e Textos Oficiais
        # --------------------------------------------------------------
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)
        info_layout.setAlignment(Qt.AlignCenter)

        lbl_title = QLabel("MangaHubRip_CJrTools")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 600;
            color: {COLOR_TEXT_PRIMARY};
            letter-spacing: 0.5px;
        """)

        lbl_version = QLabel("Version 2.0.0")
        lbl_version.setAlignment(Qt.AlignCenter)
        lbl_version.setStyleSheet(f"""
            font-family: {FONT_MONOSPACE};
            font-size: 13px;
            font-weight: 500;
            color: {COLOR_ACCENT};
        """)

        # Descrição Oficial
        lbl_desc = QLabel(
            "MangaHubRip_CJrTools é uma poderosa suíte desktop para arquivamento e download de mangás, "
            "manhwas e manhuas. Integrando a robusta base de fontes Keiyoushi, suporte nativo a grandes plataformas "
            "(MangaDex, MangaFire, MangaLivre, sites WordPress/Madara) e um motor universal com bypass stealth "
            "anti-bot, o programa permite explorar catálogos por idioma, enfileirar capítulos com download "
            "paralelo de alta velocidade e empacotar automaticamente suas leituras em arquivos digitais .CBZ organizados."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setAlignment(Qt.AlignCenter)
        lbl_desc.setStyleSheet(f"""
            font-size: 12px;
            line-height: 1.4;
            color: {COLOR_TEXT_SECONDARY};
            padding: 8px 12px;
            background-color: #363535;
            border: 1px solid {COLOR_BORDER_SUBTLE};
            border-radius: {RADIUS_DEFAULT};
        """)

        # Divisor sutil de 1px
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {COLOR_BORDER_SUBTLE}; margin: 4px 0;")

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
        """)

        info_layout.addWidget(lbl_title)
        info_layout.addWidget(lbl_version)
        info_layout.addWidget(lbl_desc)
        info_layout.addWidget(divider)
        info_layout.addWidget(lbl_designed_by)
        info_layout.addWidget(lbl_author)
        info_layout.addWidget(lbl_copyright)

        container_layout.addWidget(info_widget)
        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # --------------------------------------------------------------
        # 3. Botão de Fechamento Plano e Geométrico
        # --------------------------------------------------------------
        btn_close = QPushButton("Fechar")
        btn_close.setIcon(get_icon("x", color=COLOR_TEXT_PRIMARY, size=16))
        btn_close.setMinimumWidth(120)
        btn_close.setMinimumHeight(34)
        btn_close.clicked.connect(self.accept)

        btn_box = QHBoxLayout()
        btn_box.setAlignment(Qt.AlignCenter)
        btn_box.addWidget(btn_close)
        root_layout.addLayout(btn_box)
