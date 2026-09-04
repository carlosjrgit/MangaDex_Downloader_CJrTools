#!/usr/bin/env python3
"""
MangaDex_Downloader_CJrTools — Interface Gráfica Oficial
Design System: Dark, Minimal, Flat, Geometric, Technical.
Gerenciador de Fila de Tarefas com Estimativa de Tempo/Tamanho,
Pausar/Continuar/Parar, Retomada Automática e Seleção Avançada de Capítulos.
"""

import os
import sys
import time
import html
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QShortcut, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget
)

from manga_core import (
    AVG_PAGES_PER_CHAPTER,
    ChapterMode,
    DownloadEngine,
    ExecutionController,
    ProviderRegistry,
    QueueTask,
    StateManager,
    TaskStatus,
    calculate_task_estimates,
    clean_filename,
    create_session,
    find_id_in_url,
    format_size,
    format_time,
    get_mangadex_chapters,
    get_mangadex_info,
    get_mangadex_uuid,
    choose_mangadex_title,
    parse_chapter_selection,
    safe_path_join
)
import mangalivre

from about_dialog import AboutDialog
from icons import get_icon, get_pixmap
from styles import (
    COLOR_ACCENT,
    COLOR_BACKGROUND,
    COLOR_BORDER_STRONG,
    COLOR_BORDER_SUBTLE,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_SURFACE,
    COLOR_SURFACE_ACTIVE,
    COLOR_SURFACE_DISABLED,
    COLOR_SURFACE_ELEVATED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    DARK_THEME,
    FONT_MONOSPACE,
    FONT_PRIMARY,
    RADIUS_DEFAULT,
    RADIUS_SECONDARY
)

APP_NAME = "MangaDex_Downloader_CJrTools"
ORGANIZATION_NAME = "CJRDOOM"
__version__ = "1.0.0"


# ----------------------------------------------------------------------
# Worker de Execução Sequencial da Fila (QThread)
# ----------------------------------------------------------------------
class QueueWorker(QThread):
    """Processa tarefas da fila sequencialmente com suporte a pausa/parada e métricas em tempo real."""
    log_signal = pyqtSignal(str)
    task_updated = pyqtSignal(dict)
    queue_progress = pyqtSignal(int, int)  # (concluidos, total)
    live_metrics = pyqtSignal(float, float, int, str, str)  # speed_mb_s, eta_sec, total_bytes, task_title, chap_num
    finished_queue = pyqtSignal()

    def __init__(
        self,
        tasks: List[QueueTask],
        controller: ExecutionController,
        workers: int = 4,
        parent=None
    ):
        super().__init__(parent)
        self.tasks = tasks
        self.controller = controller
        self.workers = workers
        self.engine = DownloadEngine(controller=self.controller)
        self.total_downloaded_bytes = sum(t.real_size_bytes for t in tasks)

    def run(self):
        total_tasks = len(self.tasks)
        self.log_signal.emit(f"Iniciando processamento da fila com {total_tasks} obra(s)...")

        for idx, task in enumerate(self.tasks):
            if self.controller.is_stopped():
                self.log_signal.emit("[PARADA] Fila de downloads interrompida pelo usuario.")
                break

            if task.status == TaskStatus.COMPLETED:
                continue

            if task not in self.tasks:
                continue

            try:
                # 1. Analise da Obra se ainda nao foi analisada
                if not task.all_chapters or task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.ANALYZING
                    self.task_updated.emit(task.to_dict())
                    self.log_signal.emit(f"[ANALISE] [{idx+1}/{len(self.tasks)}] Analisando: {task.url}")
                    success = self._analyze_task(task)
                    if not success:
                        task.status = TaskStatus.ERROR
                        self.task_updated.emit(task.to_dict())
                        StateManager.save_queue(self.tasks)
                        continue

                # 2. Execucao dos Downloads de Capitulos
                task.status = TaskStatus.DOWNLOADING
                self.task_updated.emit(task.to_dict())
                StateManager.save_queue(self.tasks)

                total_chaps = len(task.selected_chapters)
                self.log_signal.emit(f"[DOWNLOAD] '{task.title}' | {total_chaps} capitulo(s) selecionado(s)")

                task_has_error = False
                failed_chapters = []

                for ch_idx, ch in enumerate(task.selected_chapters, start=1):
                    if self.controller.is_stopped() or self.controller.is_task_cancelled():
                        break

                    # Pausa ativa
                    while self.controller.is_paused() and not self.controller.is_stopped() and not self.controller.is_task_cancelled():
                        task.status = TaskStatus.PAUSED
                        self.task_updated.emit(task.to_dict())
                        time.sleep(0.5)

                    if self.controller.is_stopped() or self.controller.is_task_cancelled():
                        break

                    task.status = TaskStatus.DOWNLOADING

                    # Se o capitulo ja foi baixado anteriormente (retomada)
                    if ch.get("id") in task.downloaded_chapter_ids:
                        pct = int((ch_idx / total_chaps) * 100)
                        task.progress_percent = pct
                        self.task_updated.emit(task.to_dict())
                        continue

                    chap_num = ch.get("chapter") or ch.get("attributes", {}).get("chapter") or "Oneshot"
                    task.current_chapter_num = str(chap_num)
                    self.log_signal.emit(f"  [{ch_idx}/{total_chaps}] Baixando Cap. {chap_num}...")

                    # Callback de progresso por pagina
                    def page_progress_cb(current_page: int, total_pages: int):
                        remaining_mb = max(0.0, task.estimated_size_mb - (task.real_size_bytes / (1024 * 1024)))
                        current_speed = max(0.5, self.engine.current_speed_mb_s)
                        eta_sec = remaining_mb / current_speed if remaining_mb > 0 else 0
                        self.live_metrics.emit(
                            current_speed,
                            eta_sec,
                            self.total_downloaded_bytes + task.real_size_bytes,
                            task.title,
                            str(chap_num)
                        )

                    ok, bytes_count = self.engine.download_chapter(
                        task=task,
                        chapter=ch,
                        workers=self.workers,
                        progress_cb=page_progress_cb
                    )

                    if ok:
                        task.downloaded_chapter_ids.append(ch.get("id"))
                        task.real_size_bytes += bytes_count
                        self.total_downloaded_bytes += bytes_count
                    else:
                        if not self.controller.is_stopped() and not self.controller.is_paused() and not self.controller.is_task_cancelled():
                            err_reason = f": {task.error_message}" if task.error_message else ""
                            self.log_signal.emit(f"  [AVISO] Falha no capitulo {chap_num}{err_reason}")
                            task_has_error = True
                            failed_chapters.append(str(chap_num))

                    pct = int((ch_idx / total_chaps) * 100)
                    task.progress_percent = pct
                    self.task_updated.emit(task.to_dict())
                    StateManager.save_queue(self.tasks)

                # Finalizacao da Tarefa
                if self.controller.is_task_cancelled():
                    self.log_signal.emit(f"[CANCELADO] Tarefa '{task.title}' cancelada pelo usuario.")
                    self.controller.reset_task_cancelled()
                    continue

                if self.controller.is_stopped():
                    task.status = TaskStatus.STOPPED
                    self.log_signal.emit(f"[INTERROMPIDO] Tarefa '{task.title}' interrompida.")
                elif task_has_error and len(task.downloaded_chapter_ids) < len(task.selected_chapters):
                    task.status = TaskStatus.ERROR
                    failed_str = ", ".join(failed_chapters[:5])
                    if len(failed_chapters) > 5:
                        failed_str += f" (+{len(failed_chapters)-5} outros)"
                    chap_detail = f"Falha no download dos capitulos: {failed_str}."
                    if task.error_message:
                        task.error_message = f"{task.error_message} | {chap_detail}"
                    else:
                        task.error_message = chap_detail
                    self.log_signal.emit(f"[ERRO] '{task.title}' concluido com erros: {task.error_message}")
                else:
                    task.status = TaskStatus.COMPLETED
                    task.progress_percent = 100
                    task.error_message = ""
                    self.log_signal.emit(f"[SUCESSO] '{task.title}' finalizado com sucesso! ({format_size(task.real_size_bytes, is_bytes=True)})")

                self.task_updated.emit(task.to_dict())
                StateManager.save_queue(self.tasks)

            except Exception as e:
                task.status = TaskStatus.ERROR
                task.error_message = f"Erro inesperado no download: {e}"
                self.log_signal.emit(f"[ERRO] Excecao em '{task.title}': {e}")
                self.task_updated.emit(task.to_dict())
                StateManager.save_queue(self.tasks)

            completed_count = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
            self.queue_progress.emit(completed_count, len(self.tasks))

        self.log_signal.emit("\nProcessamento da fila finalizado.")
        self.finished_queue.emit()

    def _analyze_task(self, task: QueueTask) -> bool:
        """Analisa a URL para identificar metadados, titulos e capitulos."""
        try:
            session = create_session()
            provider = ProviderRegistry.get_provider_for_url(task.url, session=session)
            task.provider = provider.name
            self.log_signal.emit(f"Identificando fonte: {provider.display_name}...")
            info = provider.get_manga_info(task.url, session, task.lang_code)
            task.title = info["title"]
            task.cover_url = info.get("cover_url", "")
            task.available_langs = info.get("available_langs", ["pt-br"])
            task.all_chapters = info["chapters"]

            task.status = TaskStatus.READY
            task.selected_chapters = parse_chapter_selection(
                task.all_chapters, task.chapter_mode, task.chapter_mode_value
            )
            task.estimated_size_mb, task.estimated_seconds = calculate_task_estimates(task)
            self.task_updated.emit(task.to_dict())
            return True
        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error_message = str(e)
            self.log_signal.emit(f"[FALHA] Erro ao analisar {task.url}: {e}")
            return False


# ----------------------------------------------------------------------
# Tabela Especializada com Suporte a Tecla Delete
# ----------------------------------------------------------------------
class QueueTableWidget(QTableWidget):
    """QTableWidget com aparencia geometrica e sinal de Delete/Backspace."""
    delete_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


# ----------------------------------------------------------------------
# Janela Principal com Design System Oficial (PyQt5)
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__} — Gerenciador de Fila")
        self.setMinimumSize(1024, 740)

        # Ícone da aplicação
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.tasks: List[QueueTask] = []
        self.controller = ExecutionController()
        self.worker: Optional[QueueWorker] = None

        saved_tasks = StateManager.load_queue()
        if saved_tasks:
            for t in saved_tasks:
                if t.status in (TaskStatus.DOWNLOADING, TaskStatus.ANALYZING):
                    t.status = TaskStatus.STOPPED
            self.tasks = saved_tasks

        self._init_ui()
        self.apply_theme()
        self._refresh_table()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 12, 16, 16)

        # --------------------------------------------------------------
        # 1. Barra de Cabeçalho Oficial (HeaderBar)
        # --------------------------------------------------------------
        header_frame = QFrame()
        header_frame.setObjectName("HeaderBar")
        header_frame.setFixedHeight(52)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(12)

        lbl_logo_icon = QLabel()
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.png"
        if logo_path.is_file():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                lbl_logo_icon.setPixmap(pix.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header_layout.addWidget(lbl_logo_icon)

        lbl_header_title = QLabel(APP_NAME.upper())
        lbl_header_title.setObjectName("HeaderTitle")
        header_layout.addWidget(lbl_header_title)

        lbl_badge = QLabel(f"v{__version__}")
        lbl_badge.setObjectName("HeaderBadge")
        header_layout.addWidget(lbl_badge)

        header_layout.addStretch()

        # Botão Sobre (Info) e Abrir Pasta no Header
        self.btn_header_about = QPushButton("Sobre")
        self.btn_header_about.setObjectName("IconBtn")
        self.btn_header_about.setIcon(get_icon("info", color=COLOR_ACCENT, size=20))
        self.btn_header_about.setToolTip("Sobre o software, autor e versão (F1)")
        self.btn_header_about.clicked.connect(self.open_about_dialog)
        header_layout.addWidget(self.btn_header_about)

        # Atalho F1 para a tela Sobre
        self.shortcut_f1 = QShortcut(QKeySequence(Qt.Key_F1), self)
        self.shortcut_f1.activated.connect(self.open_about_dialog)

        main_layout.addWidget(header_frame)

        # --------------------------------------------------------------
        # 2. Painel de Entrada de Links em Lote e Configurações
        # --------------------------------------------------------------
        top_group = QGroupBox("Adicionar Obras à Fila de Download")
        top_layout = QVBoxLayout(top_group)
        top_layout.setSpacing(10)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.txt_urls = QTextEdit()
        self.txt_urls.setPlaceholderText(
            "Cole uma ou várias URLs/IDs (uma por linha):\n"
            "Ex: https://mangadex.org/title/...\n"
            "    https://mangalivre.blog/manga/...\n"
            "    https://mangalivre.blog/capitulo/..."
        )
        self.txt_urls.setMaximumHeight(85)
        input_row.addWidget(self.txt_urls, 4)

        btn_box = QVBoxLayout()
        btn_box.setSpacing(8)

        self.btn_add_urls = QPushButton("Adicionar à Fila")
        self.btn_add_urls.setObjectName("PrimaryBtn")
        self.btn_add_urls.setIcon(get_icon("plus", color="#1A1A1A", size=18, weight="bold"))
        self.btn_add_urls.setMinimumHeight(36)
        self.btn_add_urls.clicked.connect(self.add_urls_to_queue)

        self.btn_load_txt = QPushButton("Importar .txt")
        self.btn_load_txt.setObjectName("SecondaryBtn")
        self.btn_load_txt.setIcon(get_icon("file-text", color=COLOR_TEXT_PRIMARY, size=18))
        self.btn_load_txt.setMinimumHeight(32)
        self.btn_load_txt.clicked.connect(self.import_txt_file)

        btn_box.addWidget(self.btn_add_urls)
        btn_box.addWidget(self.btn_load_txt)
        input_row.addLayout(btn_box, 1)
        top_layout.addLayout(input_row)

        # Linha de Opções de Seleção de Capítulos e Diretório
        options_row = QHBoxLayout()
        options_row.setSpacing(12)

        lbl_mode = QLabel("Modo:")
        lbl_mode.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-weight: 500;")
        options_row.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Todos os Capítulos (ALL)", ChapterMode.ALL.value)
        self.combo_mode.addItem("Único Capítulo Específico", ChapterMode.SINGLE.value)
        self.combo_mode.addItem("Intervalo de Capítulos (X ~ Y)", ChapterMode.RANGE.value)
        self.combo_mode.addItem("Blocos de N (ex: 10 em 10)", ChapterMode.CHUNK.value)
        self.combo_mode.addItem("Apenas Mais Recente", ChapterMode.LATEST.value)
        self.combo_mode.addItem("Personalizado (ex: 1, 3, 5-10)", ChapterMode.CUSTOM.value)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        options_row.addWidget(self.combo_mode)

        self.txt_mode_val = QLineEdit()
        self.txt_mode_val.setPlaceholderText("Valor (ex: 1-10)")
        self.txt_mode_val.setEnabled(False)
        self.txt_mode_val.setMaximumWidth(150)
        options_row.addWidget(self.txt_mode_val)

        lbl_out = QLabel("Pasta de Saída:")
        lbl_out.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-weight: 500;")
        options_row.addWidget(lbl_out)

        self.txt_outdir = QLineEdit("download")
        self.txt_outdir.setMinimumWidth(180)
        options_row.addWidget(self.txt_outdir)

        btn_browse = QPushButton("Procurar...")
        btn_browse.setObjectName("SecondaryBtn")
        btn_browse.setIcon(get_icon("folder-open", color=COLOR_TEXT_PRIMARY, size=16))
        btn_browse.clicked.connect(self.browse_outdir)
        options_row.addWidget(btn_browse)

        self.cb_cbz = QCheckBox("Empacotar em .CBZ")
        self.cb_cbz.setChecked(True)
        self.cb_datasaver = QCheckBox("DataSaver (MangaDex)")
        options_row.addWidget(self.cb_cbz)
        options_row.addWidget(self.cb_datasaver)

        top_layout.addLayout(options_row)
        main_layout.addWidget(top_group)

        # --------------------------------------------------------------
        # 3. Barra de Controle da Fila de Downloads
        # --------------------------------------------------------------
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)

        self.btn_start = QPushButton(" Iniciar Fila")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setIcon(get_icon("play", color="#1A1A1A", size=18, weight="fill"))
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self.start_queue)
        toolbar_layout.addWidget(self.btn_start, 2)

        self.btn_pause = QPushButton(" Pausar")
        self.btn_pause.setObjectName("SecondaryBtn")
        self.btn_pause.setIcon(get_icon("pause", color=COLOR_TEXT_PRIMARY, size=18))
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumHeight(36)
        self.btn_pause.clicked.connect(self.toggle_pause)
        toolbar_layout.addWidget(self.btn_pause, 1)

        self.btn_stop = QPushButton(" Parar Fila")
        self.btn_stop.setObjectName("SecondaryBtn")
        self.btn_stop.setIcon(get_icon("stop", color=COLOR_ERROR, size=18, weight="fill"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(36)
        self.btn_stop.clicked.connect(self.stop_queue)
        toolbar_layout.addWidget(self.btn_stop, 1)

        self.btn_clear_completed = QPushButton(" Limpar Fila")
        self.btn_clear_completed.setObjectName("SecondaryBtn")
        self.btn_clear_completed.setIcon(get_icon("broom", color=COLOR_TEXT_PRIMARY, size=18))
        self.btn_clear_completed.setToolTip("Remove da fila as obras concluídas, com erros ou interrompidas")
        self.btn_clear_completed.setMinimumHeight(36)
        self.btn_clear_completed.clicked.connect(self.clear_completed)
        toolbar_layout.addWidget(self.btn_clear_completed, 1)

        self.btn_open_folder = QPushButton(" Abrir Pasta")
        self.btn_open_folder.setObjectName("SecondaryBtn")
        self.btn_open_folder.setIcon(get_icon("folder-open", color=COLOR_TEXT_PRIMARY, size=18))
        self.btn_open_folder.setMinimumHeight(36)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        toolbar_layout.addWidget(self.btn_open_folder, 1)

        main_layout.addLayout(toolbar_layout)

        # --------------------------------------------------------------
        # 4. Tabela de Tarefas da Fila (Queue Table)
        # --------------------------------------------------------------
        table_group = QGroupBox("Fila de Obras")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(10, 14, 10, 10)

        self.table = QueueTableWidget()
        self.table.setColumnCount(8)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels([
            "#", "Obra / Título", "Provedor", "Capítulos",
            "Tamanho Est.", "Tempo Est.", "Progresso", "Status"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(2, 105)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 95)
        self.table.setColumnWidth(6, 140)
        self.table.setColumnWidth(7, 130)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)

        self.table.delete_pressed.connect(self.delete_selected_tasks)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.cellDoubleClicked.connect(self.on_table_cell_double_clicked)

        self.shortcut_del = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self.shortcut_del.activated.connect(self.delete_selected_tasks)

        table_layout.addWidget(self.table)
        main_layout.addWidget(table_group, 3)

        # --------------------------------------------------------------
        # 5. Dashboard de Estatísticas Técnicas em Tempo Real
        # --------------------------------------------------------------
        dash_frame = QFrame()
        dash_frame.setObjectName("MetricFrame")
        dash_layout = QHBoxLayout(dash_frame)
        dash_layout.setContentsMargins(12, 6, 12, 6)
        dash_layout.setSpacing(16)

        self.lbl_queue_stat = QLabel("Fila: 0 obras")
        self.lbl_queue_stat.setObjectName("MetricAccent")

        self.lbl_speed = QLabel("Velocidade: 0.0 MB/s")
        self.lbl_speed.setObjectName("MetricLabel")

        self.lbl_eta = QLabel("Tempo Restante: --:--")
        self.lbl_eta.setObjectName("MetricLabel")

        self.lbl_downloaded_size = QLabel("Baixado: 0.0 MB")
        self.lbl_downloaded_size.setObjectName("MetricLabel")

        self.lbl_current_action = QLabel("Aguardando início...")
        self.lbl_current_action.setObjectName("MetricLabel")
        self.lbl_current_action.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")

        dash_layout.addWidget(self.lbl_queue_stat)
        dash_layout.addWidget(self.lbl_speed)
        dash_layout.addWidget(self.lbl_eta)
        dash_layout.addWidget(self.lbl_downloaded_size)
        dash_layout.addStretch()
        dash_layout.addWidget(self.lbl_current_action)

        main_layout.addWidget(dash_frame)

        # Barra de Progresso Geral
        self.overall_progress = QProgressBar()
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("Progresso da Fila: %p%")
        main_layout.addWidget(self.overall_progress)

        # --------------------------------------------------------------
        # 6. Terminal Técnico de Logs
        # --------------------------------------------------------------
        log_group = QGroupBox("Logs de Execução")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 14, 10, 10)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("LogConsole")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(130)
        log_layout.addWidget(self.log_box)
        main_layout.addWidget(log_group, 2)

    def apply_theme(self):
        """Aplica a folha de estilos do Design System oficial."""
        self.setStyleSheet(DARK_THEME)

    def open_about_dialog(self):
        """Abre o diálogo oficial 'Sobre' com a logomarca CJR DOOM."""
        dlg = AboutDialog(self)
        dlg.exec_()

    def log(self, message: str):
        self.log_box.append(message)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_mode_changed(self, idx: int):
        mode_val = self.combo_mode.currentData()
        if mode_val in [ChapterMode.SINGLE.value, ChapterMode.RANGE.value, ChapterMode.CHUNK.value, ChapterMode.CUSTOM.value]:
            self.txt_mode_val.setEnabled(True)
            if mode_val == ChapterMode.SINGLE.value:
                self.txt_mode_val.setPlaceholderText("Ex: 5 ou 415.1")
            elif mode_val == ChapterMode.RANGE.value:
                self.txt_mode_val.setPlaceholderText("Ex: 1-10 ou 20-50")
            elif mode_val == ChapterMode.CHUNK.value:
                self.txt_mode_val.setPlaceholderText("Ex: 10")
            else:
                self.txt_mode_val.setPlaceholderText("Ex: 1, 3, 5-10")
        else:
            self.txt_mode_val.setEnabled(False)
            self.txt_mode_val.clear()

    def browse_outdir(self):
        folder = QFileDialog.getExistingDirectory(self, "Escolher pasta de saída")
        if folder:
            self.txt_outdir.setText(folder)

    def open_output_folder(self):
        outdir = self.txt_outdir.text().strip() or "download"
        try:
            os.makedirs(outdir, exist_ok=True)
            norm_outdir = os.path.realpath(os.path.abspath(outdir))
            if not os.path.isdir(norm_outdir):
                self.log_message(f"[AVISO] O caminho especificado não é uma pasta válida: {norm_outdir}")
                return
            if sys.platform == "win32":
                os.startfile(norm_outdir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", norm_outdir])
            else:
                subprocess.Popen(["xdg-open", norm_outdir])
        except Exception as e:
            self.log_message(f"[ERRO] Falha ao abrir pasta de destino: {e}")

    def import_txt_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Arquivo com Links", "", "Arquivos de Texto (*.txt);;Todos (*.*)"
        )
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                self.txt_urls.setPlainText(content)
                self.log(f"[IMPORT] Arquivo carregado: {filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Falha ao ler arquivo: {e}")

    def add_urls_to_queue(self):
        raw_text = self.txt_urls.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Aviso", "Por favor, digite ou cole pelo menos uma URL.")
            return

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            return

        mode_str = self.combo_mode.currentData()
        mode_enum = ChapterMode(mode_str)
        mode_val = self.txt_mode_val.text().strip()
        outdir = self.txt_outdir.text().strip() or "download"
        cbz = self.cb_cbz.isChecked()
        datasaver = self.cb_datasaver.isChecked()

        added_count = 0
        for line in lines:
            if any(t.url == line for t in self.tasks):
                continue

            prov_obj = ProviderRegistry.get_provider_for_url(line)
            provider = prov_obj.name
            task_id = str(time.time()) + f"_{len(self.tasks)}"
            new_task = QueueTask(
                id=task_id,
                url=line,
                provider=provider,
                chapter_mode=mode_enum,
                chapter_mode_value=mode_val,
                outdir=outdir,
                cbz=cbz,
                datasaver=datasaver,
                status=TaskStatus.PENDING
            )
            self.tasks.append(new_task)
            added_count += 1

        self.txt_urls.clear()
        StateManager.save_queue(self.tasks)
        self._refresh_table()
        self.log(f"[FILA] {added_count} obra(s) adicionada(s) à fila.")

    def _refresh_table(self):
        self.table.setRowCount(len(self.tasks))
        for row, task in enumerate(self.tasks):
            # 0: #
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, item_num)

            # 1: Título
            item_title = QTableWidgetItem(task.title)
            self.table.setItem(row, 1, item_title)

            # 2: Provedor
            prov_name = ProviderRegistry.get_provider(task.provider).display_name
            item_prov = QTableWidgetItem(prov_name)
            item_prov.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_prov)

            # 3: Capítulos
            chaps_desc = f"{len(task.selected_chapters)} caps" if task.selected_chapters else "Pendente"
            item_chaps = QTableWidgetItem(chaps_desc)
            item_chaps.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, item_chaps)

            # 4: Tamanho Est.
            if task.status == TaskStatus.COMPLETED and task.real_size_bytes > 0:
                size_str = format_size(task.real_size_bytes, is_bytes=True)
            else:
                size_str = f"~{format_size(task.estimated_size_mb)}" if task.estimated_size_mb > 0 else "-"
            item_size = QTableWidgetItem(size_str)
            item_size.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_size)

            # 5: Tempo Est.
            time_str = f"~{format_time(task.estimated_seconds)}" if task.estimated_seconds > 0 else "-"
            item_time = QTableWidgetItem(time_str)
            item_time.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, item_time)

            # 6: Barra de Progresso
            pbar = QProgressBar()
            pbar.setValue(task.progress_percent)
            pbar.setAlignment(Qt.AlignCenter)
            if task.status == TaskStatus.COMPLETED:
                pbar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_SUCCESS}; }}")
            elif task.status == TaskStatus.ERROR:
                pbar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_ERROR}; }}")
            self.table.setCellWidget(row, 6, pbar)

            # 7: Status
            item_status = QTableWidgetItem(task.status.value)
            item_status.setTextAlignment(Qt.AlignCenter)

            if task.status == TaskStatus.COMPLETED:
                item_status.setForeground(QColor(COLOR_SUCCESS))
                item_status.setIcon(get_icon("check-circle", color=COLOR_SUCCESS, size=16, weight="fill"))
                item_status.setToolTip("Obra concluída com sucesso!")
            elif task.status == TaskStatus.DOWNLOADING:
                item_status.setForeground(QColor(COLOR_ACCENT))
                item_status.setIcon(get_icon("download", color=COLOR_ACCENT, size=16))
                item_status.setToolTip(f"Baixando capítulo {task.current_chapter_num}...")
            elif task.status == TaskStatus.PAUSED:
                item_status.setForeground(QColor(COLOR_WARNING))
                item_status.setIcon(get_icon("pause", color=COLOR_WARNING, size=16, weight="fill"))
                item_status.setToolTip("Fila pausada.")
            elif task.status == TaskStatus.ERROR:
                item_status.setForeground(QColor(COLOR_ERROR))
                item_status.setIcon(get_icon("x-circle", color=COLOR_ERROR, size=16, weight="fill"))
                err_text = task.error_message.strip() if task.error_message else "Falha no download dos capítulos."
                safe_err = html.escape(err_text)
                item_status.setToolTip(
                    f"<div style='background-color: {COLOR_SURFACE_ELEVATED}; color: {COLOR_TEXT_PRIMARY}; padding: 6px; border: 1px solid {COLOR_BORDER_STRONG}; border-radius: {RADIUS_DEFAULT};'>"
                    f"<b style='color: {COLOR_ERROR};'>Motivo do Erro:</b><br/>"
                    f"<div style='margin-top: 4px; color: #FFCDD2; font-size: 12px;'>{safe_err}</div>"
                    f"<div style='margin-top: 6px; font-size: 11px; color: {COLOR_ACCENT};'>Duplo clique para abrir detalhes.</div>"
                    f"</div>"
                )
            elif task.status == TaskStatus.STOPPED:
                item_status.setForeground(QColor(COLOR_TEXT_DISABLED))
                item_status.setIcon(get_icon("stop", color=COLOR_TEXT_DISABLED, size=16, weight="fill"))
                item_status.setToolTip("Download interrompido pelo usuário.")
            elif task.status == TaskStatus.PENDING:
                item_status.setForeground(QColor(COLOR_TEXT_SECONDARY))
                item_status.setIcon(get_icon("clock", color=COLOR_TEXT_SECONDARY, size=16))
                item_status.setToolTip("Aguardando na fila.")
            elif task.status == TaskStatus.ANALYZING:
                item_status.setForeground(QColor(COLOR_INFO))
                item_status.setIcon(get_icon("magnifying-glass", color=COLOR_INFO, size=16))
                item_status.setToolTip("Analisando metadados e capítulos...")

            self.table.setItem(row, 7, item_status)

        self._update_dashboard_summary()

    def _update_dashboard_summary(self):
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        total_size = sum(t.real_size_bytes for t in self.tasks)
        self.lbl_queue_stat.setText(f"Fila: {completed}/{total} concluídas")
        self.lbl_downloaded_size.setText(f"Baixado: {format_size(total_size, is_bytes=True)}")

    def on_task_updated(self, task_dict: dict):
        for idx, t in enumerate(self.tasks):
            if t.id == task_dict["id"]:
                self.tasks[idx] = QueueTask.from_dict(task_dict)
                break
        self._refresh_table()

    def on_live_metrics(self, speed_mb_s: float, eta_sec: float, total_bytes: int, task_title: str, chap_num: str):
        self.lbl_speed.setText(f"Velocidade: {speed_mb_s:.1f} MB/s")
        self.lbl_eta.setText(f"Tempo Restante: {format_time(eta_sec)}")
        self.lbl_downloaded_size.setText(f"Baixado: {format_size(total_bytes, is_bytes=True)}")
        self.lbl_current_action.setText(f"{task_title} (Cap. {chap_num})")

    def on_queue_progress(self, completed: int, total: int):
        pct = int((completed / total) * 100) if total > 0 else 0
        self.overall_progress.setValue(pct)
        self.lbl_queue_stat.setText(f"Fila: {completed}/{total} concluídas")

    def start_queue(self):
        if not self.tasks:
            QMessageBox.information(self, "Fila Vazia", "Adicione obras à fila antes de iniciar.")
            return

        pending_exists = any(t.status in [TaskStatus.PENDING, TaskStatus.STOPPED, TaskStatus.ERROR] for t in self.tasks)
        if not pending_exists and all(t.status == TaskStatus.COMPLETED for t in self.tasks):
            QMessageBox.information(self, "Concluído", "Todas as obras da fila já foram baixadas!")
            return

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setText(" Pausar")
        self.btn_pause.setIcon(get_icon("pause", color=COLOR_TEXT_PRIMARY, size=18))
        self.controller.reset()

        self.worker = QueueWorker(self.tasks, self.controller)
        self.worker.log_signal.connect(self.log)
        self.worker.task_updated.connect(self.on_task_updated)
        self.worker.queue_progress.connect(self.on_queue_progress)
        self.worker.live_metrics.connect(self.on_live_metrics)
        self.worker.finished_queue.connect(self.on_queue_finished)
        self.worker.start()

    def toggle_pause(self):
        if self.controller.is_paused():
            self.controller.resume()
            self.btn_pause.setText(" Pausar")
            self.btn_pause.setIcon(get_icon("pause", color=COLOR_TEXT_PRIMARY, size=18))
            self.log("[RETOMADA] Fila retomada.")
        else:
            self.controller.pause()
            self.btn_pause.setText(" Continuar")
            self.btn_pause.setIcon(get_icon("play", color=COLOR_ACCENT, size=18, weight="fill"))
            self.log("[PAUSA] Fila pausada.")

    def stop_queue(self):
        if self.worker:
            self.controller.stop()
            self.log("[PARADA] Solicitando parada da fila...")
            self.btn_stop.setEnabled(False)
            self.btn_pause.setEnabled(False)

    def on_queue_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText(" Pausar")
        self.btn_pause.setIcon(get_icon("pause", color=COLOR_TEXT_PRIMARY, size=18))
        self.lbl_speed.setText("Velocidade: 0.0 MB/s")
        self.lbl_eta.setText("Tempo Restante: Concluído")
        self.lbl_current_action.setText("Pronto!")
        self.worker = None
        self._refresh_table()

    def delete_selected_tasks(self):
        selected_rows = sorted(set(index.row() for index in self.table.selectedIndexes()), reverse=True)
        if not selected_rows:
            return

        tasks_to_remove = [self.tasks[r] for r in selected_rows if 0 <= r < len(self.tasks)]
        if not tasks_to_remove:
            return

        for task in tasks_to_remove:
            if task.status in (TaskStatus.DOWNLOADING, TaskStatus.ANALYZING) and self.worker and self.worker.isRunning():
                self.log(f"[CANCELAMENTO] Cancelando processo ativo de: {task.title}...")
                self.controller.cancel_current_task()

        for task in tasks_to_remove:
            if task in self.tasks:
                self.tasks.remove(task)

        StateManager.save_queue(self.tasks)
        self._refresh_table()

        count = len(tasks_to_remove)
        if count == 1:
            self.log(f"[EXCLUSAO] Obra '{tasks_to_remove[0].title}' removida da fila.")
        else:
            self.log(f"[EXCLUSAO] {count} obras removidas da fila.")

    def show_table_context_menu(self, pos):
        selected_indexes = self.table.selectedIndexes()
        menu = QMenu(self)

        if selected_indexes:
            act_delete = QAction("Excluir Selecionada(s) (Delete)", self)
            act_delete.setIcon(get_icon("trash", color=COLOR_ERROR, size=16))
            act_delete.triggered.connect(self.delete_selected_tasks)
            menu.addAction(act_delete)
            menu.addSeparator()

        act_clear_done = QAction("Limpar Concluídos e Erros", self)
        act_clear_done.setIcon(get_icon("broom", color=COLOR_TEXT_PRIMARY, size=16))
        act_clear_done.triggered.connect(self.clear_completed)
        menu.addAction(act_clear_done)

        act_clear_all = QAction("Limpar Toda a Fila", self)
        act_clear_all.setIcon(get_icon("trash", color=COLOR_WARNING, size=16))
        act_clear_all.triggered.connect(self.clear_entire_queue)
        menu.addAction(act_clear_all)

        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def on_table_cell_double_clicked(self, row: int, col: int):
        if col == 7 and 0 <= row < len(self.tasks):
            task = self.tasks[row]
            if task.status == TaskStatus.ERROR:
                msg = task.error_message.strip() if task.error_message else "Ocorreu uma falha no download dos capítulos."
                detail_box = QMessageBox(self)
                detail_box.setWindowTitle(f"Motivo do Erro — {task.title}")
                detail_box.setIcon(QMessageBox.Warning)
                detail_box.setText(f"<b>Obra:</b> {html.escape(task.title)}<br/><b>URL:</b> {html.escape(task.url)}")
                detail_box.setInformativeText(f"<b>Motivo do Erro:</b><br/>{html.escape(msg)}")
                detail_box.setStandardButtons(QMessageBox.Ok)
                detail_box.exec_()

    def clear_completed(self):
        worker_running = bool(self.worker and self.worker.isRunning())
        to_remove = []
        for t in self.tasks:
            if t.status in (TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.STOPPED):
                to_remove.append(t)
            elif t.status in (TaskStatus.DOWNLOADING, TaskStatus.ANALYZING):
                if not worker_running:
                    to_remove.append(t)

        if not to_remove:
            if self.tasks:
                reply = QMessageBox.question(
                    self,
                    "Limpar Fila",
                    "Não há obras concluídas ou com erro na fila.\nDeseja limpar todas as obras pendentes da fila?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.clear_entire_queue()
            else:
                self.log("[FILA] A fila já está vazia.")
            return

        for t in to_remove:
            if t in self.tasks:
                self.tasks.remove(t)

        StateManager.save_queue(self.tasks)
        self._refresh_table()
        self.log(f"[LIMPEZA] {len(to_remove)} obra(s) removidas da fila.")

    def clear_entire_queue(self):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Parar e Limpar",
                "A fila está baixando no momento. Deseja parar o download e limpar toda a fila?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.stop_queue()
            else:
                return

        count = len(self.tasks)
        self.tasks.clear()
        StateManager.save_queue(self.tasks)
        self._refresh_table()
        self.log(f"[LIMPEZA] Fila completamente esvaziada ({count} obras removidas).")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Confirmar Saída",
                "Downloads estão em andamento. Deseja parar e sair?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.stop()
                self.worker.wait(2000)
                for t in self.tasks:
                    if t.status in (TaskStatus.DOWNLOADING, TaskStatus.ANALYZING):
                        t.status = TaskStatus.STOPPED
                StateManager.save_queue(self.tasks)
                event.accept()
            else:
                event.ignore()
        else:
            StateManager.save_queue(self.tasks)
            event.accept()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())