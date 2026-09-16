#!/usr/bin/env python3
"""
keiyoushi_dialog.py - Janela de exploração do catálogo de fontes do index.pb (Keiyoushi).
Permite ao usuário pesquisar, filtrar por idioma e copiar/usar URLs das mais de 2.200
fontes e extensões mapeadas.
"""


from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout
)

from keiyoushi_catalog import catalog
from styles import (
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    DARK_THEME
)


class KeiyoushiCatalogDialog(QDialog):
    """Diálogo modal para navegação e busca rápida nas fontes do index.pb."""

    url_selected_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Catálogo de Fontes — Keiyoushi (index.pb)")
        self.resize(780, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(DARK_THEME)

        self._all_sources = []
        self._filtered_sources = []

        self._init_ui()
        self._load_sources()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Cabeçalho Informativo
        header_layout = QHBoxLayout()
        lbl_title = QLabel("📚 Catálogo Oficial Keiyoushi")
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        self.lbl_stats = QLabel("Carregando fontes...")
        self.lbl_stats.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px;")

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_stats)
        layout.addLayout(header_layout)

        # Barra de Filtros e Busca
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Digite para filtrar por nome, domínio ou extensão...")
        self.txt_search.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.txt_search, 3)

        self.combo_lang = QComboBox()
        self.combo_lang.setMinimumWidth(160)
        self.combo_lang.addItem("🌐 Todos os Idiomas", "")
        self.combo_lang.addItem("🇧🇷 Português (pt-BR / pt)", "pt")
        self.combo_lang.addItem("🇺🇸 Inglês (en)", "en")
        self.combo_lang.addItem("🇪🇸 Espanhol (es)", "es")
        self.combo_lang.addItem("🇯🇵 Japonês (ja)", "ja")
        self.combo_lang.addItem("🇰🇷 Coreano (ko)", "ko")
        self.combo_lang.addItem("🇨🇳 Chinês (zh)", "zh")
        self.combo_lang.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.combo_lang, 1)

        layout.addLayout(filter_layout)

        # Tabela de Fontes
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Nome da Fonte", "Idioma", "URL Base / Site", "Pacote da Extensão"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_use_selected)
        layout.addWidget(self.table)

        # Botões Inferiores
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        lbl_hint = QLabel("💡 Dica: Dê dois cliques na fonte ou clique em 'Usar URL' para preencher no downloader.")
        lbl_hint.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic;")
        btn_layout.addWidget(lbl_hint)
        btn_layout.addStretch()

        self.btn_copy = QPushButton("Copiar URL")
        self.btn_copy.setObjectName("SecondaryBtn")
        self.btn_copy.clicked.connect(self._on_copy_url)
        btn_layout.addWidget(self.btn_copy)

        self.btn_use = QPushButton("Usar URL")
        self.btn_use.setObjectName("PrimaryBtn")
        self.btn_use.clicked.connect(self._on_use_selected)
        btn_layout.addWidget(self.btn_use)

        self.btn_close = QPushButton("Fechar")
        self.btn_close.setObjectName("SecondaryBtn")
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def _load_sources(self):
        catalog.load()
        self._all_sources = list(catalog.sources)
        self._apply_filter()

    def _apply_filter(self):
        q = self.txt_search.text().strip().lower()
        selected_lang = self.combo_lang.currentData()

        filtered = []
        for s in self._all_sources:
            if selected_lang:
                s_lang = s.lang.lower()
                if selected_lang == "pt":
                    if s_lang not in ("pt", "pt-br"):
                        continue
                elif not s_lang.startswith(selected_lang):
                    continue

            if q:
                if (q not in s.name.lower() and
                    q not in s.base_url.lower() and
                    q not in s.pkg.lower() and
                    q not in s.lang.lower()):
                    continue

            filtered.append(s)

        self._filtered_sources = filtered
        self.lbl_stats.setText(f"{len(filtered)} de {len(self._all_sources)} fontes exibidas")
        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(len(self._filtered_sources))
        for row, s in enumerate(self._filtered_sources):
            item_name = QTableWidgetItem(s.name)
            item_lang = QTableWidgetItem(s.lang)
            item_lang.setTextAlignment(Qt.AlignCenter)
            item_url = QTableWidgetItem(s.base_url)
            item_pkg = QTableWidgetItem(s.pkg.replace("eu.kanade.tachiyomi.extension.", ""))

            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_lang)
            self.table.setItem(row, 2, item_url)
            self.table.setItem(row, 3, item_pkg)

    def _get_selected_source(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._filtered_sources):
            return self._filtered_sources[row]
        return None

    def _on_copy_url(self):
        s = self._get_selected_source()
        if not s:
            QMessageBox.information(self, "Aviso", "Selecione uma fonte na tabela para copiar a URL.")
            return

        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(s.base_url)
        QMessageBox.information(self, "URL Copiada", f"URL copiada para a área de transferência:\n{s.base_url}")

    def _on_use_selected(self):
        s = self._get_selected_source()
        if not s:
            QMessageBox.information(self, "Aviso", "Selecione uma fonte na tabela.")
            return

        self.url_selected_signal.emit(s.base_url)
        self.accept()
