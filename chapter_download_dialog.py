#!/usr/bin/env python3
"""
chapter_download_dialog.py - Modal de seleção de capítulos para envio à fila de download.
Pergunta ao usuário quais capítulos deseja baixar (todos, intervalo, mais recente ou personalizado)
e confirma a adição com a mensagem oficial 'Mangás foram pra fila!'.
"""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QVBoxLayout
)

from manga_core import ChapterMode
from styles import (
    COLOR_ACCENT,
    COLOR_BORDER_SUBTLE,
    COLOR_SURFACE,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    DARK_THEME,
    RADIUS_DEFAULT
)


class ChapterDownloadDialog(QDialog):
    """Diálogo modal que questiona quais capítulos baixar antes de enfileirar."""
    result_config: Optional[dict] = None

    def __init__(self, manga_title: str, manga_url: str, source_name: str = "", default_outdir: str = "download", parent=None):
        super().__init__(parent)
        self.manga_title = manga_title
        self.manga_url = manga_url
        self.source_name = source_name
        self.default_outdir = default_outdir
        self.result_config: Optional[dict] = None

        self.setWindowTitle(f"Download — {manga_title}")
        self.setFixedSize(540, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(DARK_THEME)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. Card com Identificação da Obra
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER_SUBTLE};
                border-radius: {RADIUS_DEFAULT};
                padding: 10px;
            }}
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(4)

        lbl_header = QLabel("Obra Selecionada:")
        lbl_header.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: 500;")
        info_layout.addWidget(lbl_header)

        lbl_title = QLabel(self.manga_title)
        lbl_title.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 16px; font-weight: bold;")
        lbl_title.setWordWrap(True)
        info_layout.addWidget(lbl_title)

        if self.source_name:
            lbl_source = QLabel(f"Fonte: {self.source_name}")
            lbl_source.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px;")
            info_layout.addWidget(lbl_source)

        layout.addWidget(info_frame)

        # 2. Pergunta de Seleção de Capítulos
        lbl_question = QLabel("Quais capítulos você deseja baixar?")
        lbl_question.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_question)

        self.btn_group = QButtonGroup(self)

        # Opção 1: Todos os capítulos (Padrão)
        self.rb_all = QRadioButton("Baixar tudo (Todos os capítulos disponíveis)")
        self.rb_all.setChecked(True)
        self.btn_group.addButton(self.rb_all)
        layout.addWidget(self.rb_all)

        # Opção 2: Intervalo (ex: 1-10)
        row_range = QHBoxLayout()
        row_range.setSpacing(8)
        self.rb_range = QRadioButton("Intervalo de capítulos:")
        self.btn_group.addButton(self.rb_range)
        row_range.addWidget(self.rb_range)

        self.txt_range = QLineEdit()
        self.txt_range.setPlaceholderText("ex: 1-10 ou 5-25")
        self.txt_range.setEnabled(False)
        self.txt_range.setMaximumWidth(160)
        row_range.addWidget(self.txt_range)
        row_range.addStretch()
        layout.addLayout(row_range)

        # Opção 3: Apenas o mais recente
        self.rb_latest = QRadioButton("Apenas o capítulo mais recente")
        self.btn_group.addButton(self.rb_latest)
        layout.addWidget(self.rb_latest)

        # Opção 4: Personalizado
        row_custom = QHBoxLayout()
        row_custom.setSpacing(8)
        self.rb_custom = QRadioButton("Personalizado:")
        self.btn_group.addButton(self.rb_custom)
        row_custom.addWidget(self.rb_custom)

        self.txt_custom = QLineEdit()
        self.txt_custom.setPlaceholderText("ex: 1, 3, 5-10, oneshot")
        self.txt_custom.setEnabled(False)
        row_custom.addWidget(self.txt_custom)
        layout.addLayout(row_custom)

        # Conectar toggles para habilitar campos de texto
        self.rb_all.toggled.connect(self._on_radio_toggled)
        self.rb_range.toggled.connect(self._on_radio_toggled)
        self.rb_latest.toggled.connect(self._on_radio_toggled)
        self.rb_custom.toggled.connect(self._on_radio_toggled)

        # 3. Opções Complementares de Download
        opts_layout = QHBoxLayout()
        opts_layout.setSpacing(12)

        self.cb_cbz = QCheckBox("Empacotar em .CBZ")
        self.cb_cbz.setChecked(True)
        opts_layout.addWidget(self.cb_cbz)

        lbl_out = QLabel("Pasta:")
        lbl_out.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        opts_layout.addWidget(lbl_out)

        self.txt_outdir = QLineEdit(self.default_outdir)
        opts_layout.addWidget(self.txt_outdir)

        btn_browse = QPushButton("Procurar...")
        btn_browse.setObjectName("SecondaryBtn")
        btn_browse.clicked.connect(self._browse_outdir)
        opts_layout.addWidget(btn_browse)

        layout.addLayout(opts_layout)

        # 4. Botões de Confirmação e Cancelamento
        layout.addStretch()
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)
        btn_bar.addStretch()

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("SecondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("📥 Enviar para Fila")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setDefault(True)
        self.btn_confirm.clicked.connect(self._on_confirm)
        btn_bar.addWidget(self.btn_confirm)

        layout.addLayout(btn_bar)

    def _on_radio_toggled(self):
        self.txt_range.setEnabled(self.rb_range.isChecked())
        if self.rb_range.isChecked():
            self.txt_range.setFocus()

        self.txt_custom.setEnabled(self.rb_custom.isChecked())
        if self.rb_custom.isChecked():
            self.txt_custom.setFocus()

    def _browse_outdir(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Destino", self.txt_outdir.text().strip() or ".")
        if folder:
            self.txt_outdir.setText(folder)

    def _on_confirm(self):
        # Determinar modo
        if self.rb_all.isChecked():
            mode = ChapterMode.ALL
            val = ""
        elif self.rb_range.isChecked():
            mode = ChapterMode.RANGE
            val = self.txt_range.text().strip()
            if not val:
                QMessageBox.warning(self, "Aviso", "Por favor, digite o intervalo de capítulos desejado (ex: 1-10).")
                self.txt_range.setFocus()
                return
        elif self.rb_latest.isChecked():
            mode = ChapterMode.LATEST
            val = ""
        else:
            mode = ChapterMode.CUSTOM
            val = self.txt_custom.text().strip()
            if not val:
                QMessageBox.warning(self, "Aviso", "Por favor, digite os capítulos desejados (ex: 1, 3, 5-10).")
                self.txt_custom.setFocus()
                return

        outdir = self.txt_outdir.text().strip() or "download"
        cbz = self.cb_cbz.isChecked()

        self.result_config = {
            "manga_title": self.manga_title,
            "manga_url": self.manga_url,
            "chapter_mode": mode,
            "chapter_mode_value": val,
            "cbz": cbz,
            "outdir": outdir
        }
        self.accept()
