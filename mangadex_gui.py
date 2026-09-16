#!/usr/bin/env python3
"""
MangaDex_Downloader_CJrTools — Interface Gráfica Oficial
Design System: Dark, Minimal, Flat, Geometric, Technical.
Gerenciador de Fila de Tarefas com Estimativa de Tempo/Tamanho,
Pausar/Continuar/Parar, Retomada Automática e Seleção Avançada de Capítulos.
"""

import os
import sys

# Configura caminho de navegadores do Playwright para compatibilidade com executável congelado
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    if sys.platform == "win32":
        _local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_appdata, "ms-playwright")
    elif sys.platform == "darwin":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser("~/Library/Caches/ms-playwright")
    else:
        _cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_cache_home, "ms-playwright")

import time
import html
import subprocess
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QPoint, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QShortcut, QSizePolicy, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget
)

from manga_core import (
    AVG_PAGE_SIZE_MANGADEX_ORIGINAL_MB,
    AVG_PAGE_SIZE_MANGADEX_SAVER_MB,
    ChapterMode,
    DownloadEngine,
    ExecutionController,
    ProviderRegistry,
    QueueTask,
    StateManager,
    TaskStatus,
    calculate_task_estimates,
    create_session,
    format_size,
    format_time,
    get_language_display_name,
    parse_chapter_selection
)

from about_dialog import AboutDialog
from icons import get_icon
from styles import (
    COLOR_ACCENT,
    COLOR_BORDER_STRONG,
    COLOR_BORDER_SUBTLE,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_SURFACE,
    COLOR_SURFACE_ELEVATED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    DARK_THEME,
    RADIUS_DEFAULT
)

import requests
from keiyoushi_catalog import KeiyoushiSource, catalog
from source_catalog_fetcher import fetch_source_catalog
from chapter_download_dialog import ChapterDownloadDialog

APP_NAME = "MangaHubRip_CJrTools"
ORGANIZATION_NAME = "CJRDOOM"
__version__ = "2.0.0"


# ----------------------------------------------------------------------
# Workers de Análise e Consulta de Idiomas (QThread)
# ----------------------------------------------------------------------
class MangaAnalysisWorker(QThread):
    """Analisa uma URL em background, extrai metadados, capa e idiomas disponíveis."""
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, url: str, lang_code: str = "pt-br", parent=None):
        super().__init__(parent)
        self.url = url.strip()
        self.lang_code = lang_code

    def run(self):
        try:
            session = create_session()
            self.status_signal.emit("Identificando provedor do link...")
            provider = ProviderRegistry.get_provider_for_url(self.url, session=session)

            source_preview = getattr(provider, "get_source_info", lambda u: None)(self.url)
            prov_initial = f"{source_preview.name} ({source_preview.lang})" if source_preview else provider.display_name
            self.status_signal.emit(f"Consultando metadados em {prov_initial}...")

            info = provider.get_manga_info(self.url, session=session, lang_code=self.lang_code)
            prov_display = info.get("provider_display") or prov_initial

            cover_bytes = None
            cover_url = info.get("cover_url", "")
            if cover_url:
                try:
                    self.status_signal.emit("Carregando imagem de capa...")
                    c_res = session.get(cover_url, timeout=10)
                    if c_res.status_code == 200:
                        cover_bytes = c_res.content
                except Exception:
                    pass

            result = {
                "url": self.url,
                "provider": provider.name,
                "provider_display": prov_display,
                "title": info["title"],
                "cover_url": cover_url,
                "cover_bytes": cover_bytes,
                "available_langs": info.get("available_langs", [self.lang_code]),
                "current_lang": self.lang_code,
                "chapters": info.get("chapters", []),
            }
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class LanguageSwitchWorker(QThread):
    """Busca capítulos de uma obra específica em outro idioma em background."""
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, list)  # new_lang_code, new_chapters
    error_signal = pyqtSignal(str)

    def __init__(self, url: str, provider_name: str, new_lang_code: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.provider_name = provider_name
        self.new_lang_code = new_lang_code

    def run(self):
        try:
            session = create_session()
            provider = ProviderRegistry.get_provider(self.provider_name)
            self.status_signal.emit(f"Buscando capítulos no idioma '{self.new_lang_code}'...")
            chaps = provider.get_chapters_for_language(self.url, self.new_lang_code, session=session)
            self.finished_signal.emit(self.new_lang_code, chaps)
        except Exception as e:
            self.error_signal.emit(str(e))


# ----------------------------------------------------------------------
# Workers do Catálogo de Fontes e Miniaturas (QThread)
# ----------------------------------------------------------------------
class MangaCatalogWorker(QThread):
    """Carrega o catálogo de mangás de uma fonte específica em background sem travar a interface."""
    finished_signal = pyqtSignal(list, int)  # (mangas_list, page)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, source: KeiyoushiSource, page: int = 1, force_refresh: bool = False, parent=None):
        super().__init__(parent)
        self.source = source
        self.page = page
        self.force_refresh = force_refresh

    def run(self):
        try:
            self.status_signal.emit(f"Buscando obras em '{self.source.name}' (pág. {self.page})...")
            mangas = fetch_source_catalog(self.source, page=self.page, force_refresh=self.force_refresh)
            self.finished_signal.emit(mangas, self.page)
        except Exception as e:
            self.error_signal.emit(str(e))


class CoverThumbnailWorker(QThread):
    """Carrega miniaturas de capa assincronamente para a vitrine de mangás."""
    cover_loaded = pyqtSignal(int, bytes)  # (row_index, img_bytes)

    def __init__(self, items: list, headers: dict = None, parent=None):
        super().__init__(parent)
        self.items = items  # list of (row_index, cover_url)
        self.headers = headers or {}
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            **self.headers
        })
        for row_idx, cover_url in self.items:
            if self._is_cancelled:
                break
            if not cover_url:
                continue
            try:
                r = session.get(cover_url, timeout=6)
                if r.status_code == 200 and r.content:
                    self.cover_loaded.emit(row_idx, r.content)
            except Exception:
                pass
            time.sleep(0.04)


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

                    # Intervalo moderado para evitar WAF/rate-limits em fontes web dinâmicas
                    if task.provider in ("keiyoushi", "universal") and ch_idx < total_chaps and not self.controller.is_stopped() and not self.controller.is_task_cancelled():
                        time.sleep(1.0)

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
                    failed_unique = list(dict.fromkeys(failed_chapters))
                    failed_str = ", ".join(failed_unique[:5])
                    if len(failed_unique) > 5:
                        failed_str += f" (+{len(failed_unique)-5} outros)"
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

        try:
            for p in ProviderRegistry.get_providers():
                p.close_session()
        except Exception:
            pass

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
            task.all_chapters = info.get("chapters") or info.get("all_chapters", [])

            task.status = TaskStatus.READY
            if not task.selected_chapters:
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
# Pop-up Flutuante para Pré-visualização Ampliada de Capas
# ----------------------------------------------------------------------
class CoverPreviewPopup(QFrame):
    """
    Janela flutuante elegante que exibe a capa do mangá ampliada em alta
    definição com detalhes ao passar o cursor sobre a miniatura.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.setStyleSheet(f"""
            CoverPreviewPopup {{
                background-color: {COLOR_SURFACE_ELEVATED};
                border: 2px solid {COLOR_ACCENT};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Label da Capa Ampliada (260x370 em alta definição)
        self.lbl_image = QLabel(self)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setFixedSize(260, 370)
        self.lbl_image.setStyleSheet(f"""
            background-color: {COLOR_SURFACE};
            border: 1px solid {COLOR_BORDER_SUBTLE};
            border-radius: 6px;
        """)
        layout.addWidget(self.lbl_image)

        # Label do Título da Obra
        self.lbl_title = QLabel(self)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setFixedWidth(260)
        self.lbl_title.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: 12px;
            font-weight: 700;
            padding: 2px;
        """)
        layout.addWidget(self.lbl_title)

        # Label da Fonte
        self.lbl_source = QLabel(self)
        self.lbl_source.setAlignment(Qt.AlignCenter)
        self.lbl_source.setStyleSheet(f"""
            color: {COLOR_ACCENT};
            font-size: 10px;
            font-weight: 600;
        """)
        layout.addWidget(self.lbl_source)

        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(24)
            shadow.setColor(QColor(0, 0, 0, 200))
            shadow.setOffset(0, 6)
            self.setGraphicsEffect(shadow)
        except Exception:
            pass

    def show_preview(self, global_pos: QPoint, pixmap: Optional[QPixmap], title: str, source_name: str = ""):
        """Renderiza a capa em tamanho ampliado garantindo visibilidade total na tela."""
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(260, 370, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_image.setPixmap(scaled)
            self.lbl_image.setText("")
        else:
            self.lbl_image.setPixmap(QPixmap())
            self.lbl_image.setText("📖 Sem Capa")
            self.lbl_image.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 14px; background-color: {COLOR_SURFACE}; border-radius: 6px;")

        self.lbl_title.setText(title)
        if source_name:
            self.lbl_source.setText(f"FONTE: {source_name.upper()}")
            self.lbl_source.show()
        else:
            self.lbl_source.hide()

        self.adjustSize()

        # Posicionamento inteligente ao lado do item da tabela
        target_x = global_pos.x() + 15
        target_y = global_pos.y() - 30

        # Previne que o popup ultrapasse as bordas da tela
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if target_x + self.width() > geo.right() - 10:
                target_x = max(geo.left() + 10, global_pos.x() - self.width() - 85)
            if target_y + self.height() > geo.bottom() - 10:
                target_y = max(geo.top() + 10, geo.bottom() - self.height() - 10)
            if target_y < geo.top() + 10:
                target_y = geo.top() + 10

        self.move(target_x, target_y)
        self.show()
        self.raise_()

    def hide_preview(self):
        """Oculta o pop-up instantaneamente."""
        self.hide()


class HoverableCoverLabel(QLabel):
    """
    QLabel que exibe a miniatura na tabela e aciona o pop-up ampliado
    quando o usuário aproxima o cursor do mouse (hover).
    """
    def __init__(self, title: str, source_name: str, popup: CoverPreviewPopup, parent=None):
        super().__init__(parent)
        self.title = title
        self.source_name = source_name
        self.popup = popup
        self.cover_pixmap: Optional[QPixmap] = None
        self.setMouseTracking(True)

    def set_cover_pixmap(self, pix: QPixmap):
        self.cover_pixmap = pix
        # Exibe miniatura ampliada na tabela (65x90) com suavização
        self.setPixmap(pix.scaled(65, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def enterEvent(self, event):
        if self.popup:
            global_pos = self.mapToGlobal(QPoint(self.width(), 0))
            self.popup.show_preview(global_pos, self.cover_pixmap, self.title, self.source_name)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.popup:
            self.popup.hide_preview()
        super().leaveEvent(event)

    def hideEvent(self, event):
        if self.popup:
            self.popup.hide_preview()
        super().hideEvent(event)


# ----------------------------------------------------------------------
# Janela Principal com Design System Oficial (PyQt5)
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__} — Gerenciador de Fila")
        self.setMinimumSize(1080, 800)
        self.resize(1160, 840)

        # Ícone da aplicação
        self.base_asset_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
        logo_path = self.base_asset_dir / "assets" / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.tasks: List[QueueTask] = []
        self.controller = ExecutionController()
        self.worker: Optional[QueueWorker] = None
        self.analysis_worker: Optional[MangaAnalysisWorker] = None
        self.lang_worker: Optional[LanguageSwitchWorker] = None
        self.current_analysis: Optional[dict] = None

        # Atributos da Aba Explorar Fontes
        self.catalog_worker: Optional[MangaCatalogWorker] = None
        self.cover_worker: Optional[CoverThumbnailWorker] = None
        self.current_explore_source: Optional[KeiyoushiSource] = None
        self.current_explore_page: int = 1
        self.all_explore_sources: List[KeiyoushiSource] = []
        self.filtered_explore_sources: List[KeiyoushiSource] = []
        self.current_manga_items: List[dict] = []

        saved_tasks = StateManager.load_queue()
        if saved_tasks:
            for t in saved_tasks:
                if t.status in (TaskStatus.DOWNLOADING, TaskStatus.ANALYZING):
                    t.status = TaskStatus.STOPPED
            self.tasks = saved_tasks

        self._init_ui()
        self.apply_theme()
        self._refresh_table()
        self._populate_sources_list()

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
        logo_path = self.base_asset_dir / "assets" / "logo.png"
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
        # Abas Principais da Aplicação (Fila de Downloads e Explorar Fontes)
        # --------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.currentChanged.connect(lambda: getattr(self, 'cover_popup', None) and self.cover_popup.hide_preview())

        # Aba 1: Fila de Downloads
        self.tab_queue = QWidget()
        queue_layout = QVBoxLayout(self.tab_queue)
        queue_layout.setContentsMargins(0, 8, 0, 0)
        queue_layout.setSpacing(10)

        # --------------------------------------------------------------
        # 2. Painel de Entrada de Links e Análise Prévia
        # --------------------------------------------------------------
        self.top_group = QGroupBox("Adicionar Obras à Fila de Download")
        self.top_group.setMinimumHeight(175)
        self.top_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        top_layout = QVBoxLayout(self.top_group)
        top_layout.setSpacing(10)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.txt_urls = QTextEdit()
        self.txt_urls.setPlaceholderText(
            "Cole a URL do mangá para analisar (ex: https://mangadex.org/title/...):\n"
            "Ou cole múltiplas URLs (uma por linha) para adicionar direto em lote."
        )
        self.txt_urls.setMaximumHeight(54)
        input_row.addWidget(self.txt_urls, 4)

        btn_box = QVBoxLayout()
        btn_box.setSpacing(4)

        self.btn_analyze_link = QPushButton("🔍 Analisar Link")
        self.btn_analyze_link.setObjectName("PrimaryBtn")
        self.btn_analyze_link.setMinimumHeight(28)
        self.btn_analyze_link.setToolTip("Analisa o link, carrega capa, número de capítulos e idiomas disponíveis.")
        self.btn_analyze_link.clicked.connect(self.start_analysis)

        btn_sub_box = QHBoxLayout()
        btn_sub_box.setSpacing(6)

        self.btn_batch_add = QPushButton("+ Fila Direta")
        self.btn_batch_add.setObjectName("SecondaryBtn")
        self.btn_batch_add.setMinimumHeight(24)
        self.btn_batch_add.setToolTip("Adiciona a(s) URL(s) diretamente à fila de download.")
        self.btn_batch_add.clicked.connect(self.add_urls_to_queue)
        self.btn_add_urls = self.btn_batch_add  # Alias compatível com testes

        self.btn_load_txt = QPushButton("Importar .txt")
        self.btn_load_txt.setObjectName("SecondaryBtn")
        self.btn_load_txt.setIcon(get_icon("file-text", color=COLOR_TEXT_PRIMARY, size=16))
        self.btn_load_txt.setMinimumHeight(24)
        self.btn_load_txt.clicked.connect(self.import_txt_file)

        self.btn_catalog = QPushButton("📚 Catálogo (2200+)")
        self.btn_catalog.setObjectName("SecondaryBtn")
        self.btn_catalog.setMinimumHeight(24)
        self.btn_catalog.setToolTip("Navega e pesquisa nas mais de 2.200 fontes do catálogo Keiyoushi.")
        self.btn_catalog.clicked.connect(self.switch_to_explore_tab)

        btn_sub_box.addWidget(self.btn_batch_add)
        btn_sub_box.addWidget(self.btn_load_txt)
        btn_sub_box.addWidget(self.btn_catalog)

        btn_box.addWidget(self.btn_analyze_link)
        btn_box.addLayout(btn_sub_box)
        input_row.addLayout(btn_box, 1)
        top_layout.addLayout(input_row)

        # Configurações de Saída e Formato
        global_opts_row = QHBoxLayout()
        global_opts_row.setSpacing(12)

        lbl_out = QLabel("Pasta de Saída:")
        lbl_out.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-weight: 500;")
        global_opts_row.addWidget(lbl_out)

        self.txt_outdir = QLineEdit("download")
        self.txt_outdir.setMinimumWidth(180)
        global_opts_row.addWidget(self.txt_outdir)

        btn_browse = QPushButton("Procurar...")
        btn_browse.setObjectName("SecondaryBtn")
        btn_browse.setIcon(get_icon("folder-open", color=COLOR_TEXT_PRIMARY, size=16))
        btn_browse.clicked.connect(self.browse_outdir)
        global_opts_row.addWidget(btn_browse)

        self.cb_cbz = QCheckBox("Empacotar em .CBZ")
        self.cb_cbz.setChecked(True)
        self.cb_datasaver = QCheckBox("DataSaver (MangaDex)")
        self.cb_datasaver.stateChanged.connect(self._update_preview_calc)
        global_opts_row.addWidget(self.cb_cbz)
        global_opts_row.addWidget(self.cb_datasaver)
        global_opts_row.addStretch()
        top_layout.addLayout(global_opts_row)

        # Card de Análise da Obra
        self.card_analysis = QFrame()
        self.card_analysis.setObjectName("AnalysisCard")
        self.card_analysis.setMinimumHeight(40)
        card_layout = QVBoxLayout(self.card_analysis)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(6)

        self.lbl_card_status = QLabel("💡 Cole a URL de um mangá acima e clique em '🔍 Analisar Link' para visualizar capítulos e escolher o idioma.")
        self.lbl_card_status.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-style: italic;")
        card_layout.addWidget(self.lbl_card_status)

        # Painel com conteúdo detalhado da obra analisada
        self.panel_analyzed = QWidget()
        self.panel_analyzed.hide()
        self.panel_analyzed.setMinimumHeight(125)
        panel_layout = QHBoxLayout(self.panel_analyzed)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(12)

        # Capa do mangá
        self.lbl_preview_cover = QLabel()
        self.lbl_preview_cover.setFixedSize(80, 115)
        self.lbl_preview_cover.setStyleSheet(f"background-color: {COLOR_SURFACE_ELEVATED}; border: 1px solid {COLOR_BORDER_SUBTLE}; border-radius: 4px;")
        self.lbl_preview_cover.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self.lbl_preview_cover)

        # Layout direito com detalhes, idioma, seleção e estimativa
        details_layout = QVBoxLayout()
        details_layout.setSpacing(4)

        # Linha 1: Título e Badges
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.lbl_preview_title = QLabel("Título da Obra")
        self.lbl_preview_title.setObjectName("AnalysisTitle")
        self.lbl_preview_prov = QLabel("MangaDex")
        self.lbl_preview_prov.setObjectName("BadgeProvider")
        self.lbl_preview_chaps_badge = QLabel("0 caps")
        self.lbl_preview_chaps_badge.setObjectName("ChapsBadge")

        title_row.addWidget(self.lbl_preview_title)
        title_row.addWidget(self.lbl_preview_prov)
        title_row.addWidget(self.lbl_preview_chaps_badge)
        title_row.addStretch()
        details_layout.addLayout(title_row)

        # Linha 2: Idioma e Modo de Seleção de Capítulos
        row_sel = QHBoxLayout()
        row_sel.setSpacing(10)

        lbl_lang = QLabel("Idioma:")
        lbl_lang.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-weight: 500;")
        row_sel.addWidget(lbl_lang)

        self.combo_lang = QComboBox()
        self.combo_lang.setMinimumWidth(180)
        self.combo_lang.currentIndexChanged.connect(self.on_lang_changed)
        row_sel.addWidget(self.combo_lang)

        lbl_mode = QLabel("Capítulos:")
        lbl_mode.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-weight: 500;")
        row_sel.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Todos os Capítulos (ALL)", ChapterMode.ALL.value)
        self.combo_mode.addItem("Único Capítulo Específico", ChapterMode.SINGLE.value)
        self.combo_mode.addItem("Intervalo de Capítulos (X ~ Y)", ChapterMode.RANGE.value)
        self.combo_mode.addItem("Blocos de N (ex: 10 em 10)", ChapterMode.CHUNK.value)
        self.combo_mode.addItem("Apenas Mais Recente", ChapterMode.LATEST.value)
        self.combo_mode.addItem("Personalizado (ex: 1, 3, 5-10)", ChapterMode.CUSTOM.value)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        row_sel.addWidget(self.combo_mode)

        self.txt_mode_val = QLineEdit()
        self.txt_mode_val.setPlaceholderText("Valor (ex: 1-10)")
        self.txt_mode_val.setEnabled(False)
        self.txt_mode_val.setMaximumWidth(130)
        self.txt_mode_val.textChanged.connect(self._update_preview_calc)
        row_sel.addWidget(self.txt_mode_val)

        self.lbl_mode_example = QLabel("Ex: 1,10 / 1-10 / 1, 6, 10")
        self.lbl_mode_example.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic;")
        row_sel.addWidget(self.lbl_mode_example)
        row_sel.addStretch()

        details_layout.addLayout(row_sel)

        # Linha 3: Resumo da Estimativa e Botão de Adição à Fila
        row_action = QHBoxLayout()
        row_action.setSpacing(12)

        self.lbl_preview_calc = QLabel("Selecionados: 0 caps  |  Tamanho Est.: ~0 MB  |  Tempo Est.: ~0s")
        self.lbl_preview_calc.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: 600; font-size: 12px;")
        row_action.addWidget(self.lbl_preview_calc)
        row_action.addStretch()

        self.btn_add_analyzed = QPushButton(" + Adicionar à Fila")
        self.btn_add_analyzed.setObjectName("PrimaryBtn")
        self.btn_add_analyzed.setIcon(get_icon("plus", color="#1A1A1A", size=16, weight="bold"))
        self.btn_add_analyzed.setMinimumHeight(32)
        self.btn_add_analyzed.clicked.connect(self.add_analyzed_to_queue)
        row_action.addWidget(self.btn_add_analyzed)

        details_layout.addLayout(row_action)
        panel_layout.addLayout(details_layout)
        card_layout.addWidget(self.panel_analyzed)

        top_layout.addWidget(self.card_analysis)
        queue_layout.addWidget(self.top_group)

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

        queue_layout.addLayout(toolbar_layout)

        # --------------------------------------------------------------
        # 4. Tabela de Tarefas da Fila (Queue Table)
        # --------------------------------------------------------------
        table_group = QGroupBox("Fila de Obras")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(10, 14, 10, 10)

        self.table = QueueTableWidget()
        self.table.setColumnCount(9)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setHorizontalHeaderLabels([
            "#", "Obra / Título", "Provedor", "Idioma", "Capítulos",
            "Tamanho Est.", "Tempo Est.", "Progresso", "Status"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 115)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 160)
        self.table.setColumnWidth(8, 130)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setMinimumHeight(160)

        self.table.delete_pressed.connect(self.delete_selected_tasks)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.cellDoubleClicked.connect(self.on_table_cell_double_clicked)

        self.shortcut_del = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self.shortcut_del.activated.connect(self.delete_selected_tasks)

        table_layout.addWidget(self.table)
        queue_layout.addWidget(table_group, 4)

        # --------------------------------------------------------------
        # 5. Dashboard de Estatísticas Técnicas em Tempo Real
        # --------------------------------------------------------------
        dash_frame = QFrame()
        dash_frame.setObjectName("MetricFrame")
        dash_frame.setFixedHeight(44)
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

        queue_layout.addWidget(dash_frame)

        # Barra de Progresso Geral
        self.overall_progress = QProgressBar()
        self.overall_progress.setFixedHeight(22)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("Progresso da Fila: %p%")
        queue_layout.addWidget(self.overall_progress)

        # --------------------------------------------------------------
        # 6. Terminal Técnico de Logs
        # --------------------------------------------------------------
        log_group = QGroupBox("Logs de Execução")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 14, 10, 10)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("LogConsole")
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(80)
        log_layout.addWidget(self.log_box)
        queue_layout.addWidget(log_group, 1)

        # --------------------------------------------------------------
        # Aba 2: Explorar Fontes (2.200+ Sites)
        # --------------------------------------------------------------
        self.tab_explore = QWidget()
        self._init_explore_tab()

        self.tabs.addTab(self.tab_queue, "📥 Fila de Downloads")
        self.tabs.addTab(self.tab_explore, "🌐 Explorar Fontes")
        main_layout.addWidget(self.tabs)

    def switch_to_explore_tab(self):
        """Alterna a visualização diretamente para a aba 'Explorar Fontes'."""
        self.tabs.setCurrentIndex(1)

    def _init_explore_tab(self):
        """Inicializa a aba '🌐 Explorar Fontes' com divisão entre lista de fontes e vitrine de mangás."""
        explore_layout = QVBoxLayout(self.tab_explore)
        explore_layout.setContentsMargins(6, 8, 6, 6)
        explore_layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ==============================================================
        # 1. PAINEL ESQUERDO: Catálogo de 2.200+ Fontes
        # ==============================================================
        left_box = QGroupBox("1. Selecione uma Fonte (2.200+)")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 12, 8, 8)
        left_layout.setSpacing(8)

        # Filtro de Busca de Fonte por Texto
        self.txt_source_filter = QLineEdit()
        self.txt_source_filter.setPlaceholderText("🔍 Buscar fonte por nome ou domínio...")
        self.txt_source_filter.textChanged.connect(self._filter_sources)
        left_layout.addWidget(self.txt_source_filter)

        # Filtro por Idioma
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lbl_lang = QLabel("Idioma:")
        lbl_lang.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        self.combo_source_lang = QComboBox()
        self.combo_source_lang.addItem("🌐 Português (pt-br)", "pt-br")
        self.combo_source_lang.addItem("🌐 Todos os Idiomas (2200+)", "all")
        self.combo_source_lang.addItem("🇺🇸 English (en)", "en")
        self.combo_source_lang.addItem("🇪🇸 Español (es)", "es")
        self.combo_source_lang.addItem("🇯🇵 日本語 (ja)", "ja")
        self.combo_source_lang.addItem("🇫🇷 Français (fr)", "fr")
        self.combo_source_lang.addItem("🇩🇪 Deutsch (de)", "de")
        self.combo_source_lang.addItem("🇮🇹 Italiano (it)", "it")
        self.combo_source_lang.addItem("🇷🇺 Русский (ru)", "ru")
        self.combo_source_lang.currentIndexChanged.connect(self._filter_sources)

        lang_row.addWidget(lbl_lang)
        lang_row.addWidget(self.combo_source_lang, 1)
        left_layout.addLayout(lang_row)

        # Tabela de Fontes
        self.table_sources = QTableWidget()
        self.table_sources.setColumnCount(3)
        self.table_sources.setHorizontalHeaderLabels(["Fonte / Scan", "Lang", "Domínio"])
        self.table_sources.verticalHeader().setVisible(False)
        self.table_sources.verticalHeader().setDefaultSectionSize(28)
        self.table_sources.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_sources.setSelectionMode(QTableWidget.SingleSelection)
        self.table_sources.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_sources.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table_sources.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_sources.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_sources.setColumnWidth(0, 140)
        self.table_sources.setColumnWidth(1, 55)
        self.table_sources.itemSelectionChanged.connect(self._on_source_selection_changed)
        left_layout.addWidget(self.table_sources)

        # Rodapé do painel de fontes com contador
        self.lbl_sources_count = QLabel("Carregando fontes...")
        self.lbl_sources_count.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        left_layout.addWidget(self.lbl_sources_count)

        splitter.addWidget(left_box)

        # ==============================================================
        # 2. PAINEL DIREITO: Vitrine de Mangás do Site Selecionado
        # ==============================================================
        right_box = QGroupBox("2. Obras Disponíveis na Fonte")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 12, 8, 8)
        right_layout.setSpacing(8)

        # Barra Superior da Vitrine: Título da Fonte, Filtro Rápido e Botão Atualizar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.lbl_current_source_info = QLabel("Selecione uma fonte à esquerda para carregar as obras")
        self.lbl_current_source_info.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 13px; font-weight: bold;")
        top_bar.addWidget(self.lbl_current_source_info, 1)

        self.txt_manga_filter = QLineEdit()
        self.txt_manga_filter.setPlaceholderText("🔍 Filtrar obras exibidas...")
        self.txt_manga_filter.setMaximumWidth(200)
        self.txt_manga_filter.textChanged.connect(self._filter_mangas_in_view)
        top_bar.addWidget(self.txt_manga_filter)

        self.btn_refresh_catalog = QPushButton("🔄 Atualizar")
        self.btn_refresh_catalog.setObjectName("SecondaryBtn")
        self.btn_refresh_catalog.setToolTip("Recarrega a página atual ignorando o cache local")
        self.btn_refresh_catalog.clicked.connect(lambda: self._load_current_page(force_refresh=True))
        top_bar.addWidget(self.btn_refresh_catalog)

        right_layout.addLayout(top_bar)

        # Pop-up de capa ampliada ao passar o mouse
        self.cover_popup = CoverPreviewPopup(self)

        # Tabela de Mangás da Fonte
        self.table_mangas = QTableWidget()
        self.table_mangas.setColumnCount(5)
        self.table_mangas.setHorizontalHeaderLabels(["Capa", "Título da Obra", "Capítulos", "Disponibilidade", "Ação"])
        self.table_mangas.verticalHeader().setVisible(False)
        self.table_mangas.verticalHeader().setDefaultSectionSize(98)
        self.table_mangas.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_mangas.setSelectionMode(QTableWidget.SingleSelection)
        self.table_mangas.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_mangas.cellDoubleClicked.connect(self._on_manga_cell_double_clicked)
        self.table_mangas.verticalScrollBar().valueChanged.connect(self.cover_popup.hide_preview)

        header_m = self.table_mangas.horizontalHeader()
        header_m.setSectionResizeMode(0, QHeaderView.Fixed)
        header_m.setSectionResizeMode(1, QHeaderView.Stretch)
        header_m.setSectionResizeMode(2, QHeaderView.Fixed)
        header_m.setSectionResizeMode(3, QHeaderView.Fixed)
        header_m.setSectionResizeMode(4, QHeaderView.Fixed)

        self.table_mangas.setColumnWidth(0, 80)
        self.table_mangas.setColumnWidth(2, 120)
        self.table_mangas.setColumnWidth(3, 110)
        self.table_mangas.setColumnWidth(4, 110)

        right_layout.addWidget(self.table_mangas)

        # Barra Inferior: Paginação e Status
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)

        self.btn_prev_page = QPushButton("⬅️ Anterior")
        self.btn_prev_page.setObjectName("SecondaryBtn")
        self.btn_prev_page.setEnabled(False)
        self.btn_prev_page.clicked.connect(self._prev_page)
        bottom_bar.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("Página 1")
        self.lbl_page_info.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold; font-size: 12px;")
        bottom_bar.addWidget(self.lbl_page_info)

        self.btn_next_page = QPushButton("Próxima ➡️")
        self.btn_next_page.setObjectName("SecondaryBtn")
        self.btn_next_page.setEnabled(False)
        self.btn_next_page.clicked.connect(self._next_page)
        bottom_bar.addWidget(self.btn_next_page)

        bottom_bar.addStretch()

        self.lbl_catalog_status = QLabel("Nenhuma fonte carregada.")
        self.lbl_catalog_status.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic;")
        bottom_bar.addWidget(self.lbl_catalog_status)

        right_layout.addLayout(bottom_bar)

        splitter.addWidget(right_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([330, 770])

        explore_layout.addWidget(splitter)

    def _populate_sources_list(self):
        """Carrega e popula a lista de fontes do catálogo Keiyoushi."""
        if not catalog.is_loaded:
            catalog.load()

        self.all_explore_sources = list(catalog.sources)
        self._filter_sources()

    def _filter_sources(self):
        """Filtra as fontes exibidas por texto de busca e idioma."""
        query = self.txt_source_filter.text().strip().lower()
        selected_lang = self.combo_source_lang.currentData()

        filtered = []
        for s in self.all_explore_sources:
            if selected_lang != "all" and s.lang.lower() != selected_lang:
                continue
            if query:
                domain = catalog.extract_domain(s.base_url).lower()
                name = s.name.lower()
                if query not in name and query not in domain:
                    continue
            filtered.append(s)

        self.filtered_explore_sources = filtered
        self.table_sources.blockSignals(True)
        self.table_sources.setRowCount(len(filtered))

        for row, s in enumerate(filtered):
            item_name = QTableWidgetItem(s.name)
            item_name.setToolTip(f"{s.name}\n{s.base_url}")
            item_lang = QTableWidgetItem(s.lang.upper())
            item_lang.setTextAlignment(Qt.AlignCenter)
            domain = catalog.extract_domain(s.base_url)
            item_domain = QTableWidgetItem(domain)
            item_domain.setToolTip(s.base_url)

            self.table_sources.setItem(row, 0, item_name)
            self.table_sources.setItem(row, 1, item_lang)
            self.table_sources.setItem(row, 2, item_domain)

        self.table_sources.blockSignals(False)
        self.lbl_sources_count.setText(f"{len(filtered)} fonte(s) encontrada(s).")

    def _on_source_selection_changed(self):
        """Disparado quando o usuário clica em uma fonte na lista."""
        selected_rows = self.table_sources.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if 0 <= row < len(self.filtered_explore_sources):
            source = self.filtered_explore_sources[row]
            self.current_explore_source = source
            self.current_explore_page = 1
            domain = catalog.extract_domain(source.base_url)
            self.lbl_current_source_info.setText(f"📖 {source.name} [{source.lang.upper()}] — {domain}")
            self._load_current_page(force_refresh=False)

    def _load_current_page(self, force_refresh=False):
        """Inicia a busca assíncrona das obras da fonte selecionada na página indicada."""
        if hasattr(self, 'cover_popup'):
            self.cover_popup.hide_preview()

        if not self.current_explore_source:
            return

        if self.cover_worker and self.cover_worker.isRunning():
            self.cover_worker.cancel()
            self.cover_worker.wait(500)

        source = self.current_explore_source
        page = self.current_explore_page
        self.lbl_page_info.setText(f"Página {page}")
        self.btn_prev_page.setEnabled(page > 1)
        self.btn_next_page.setEnabled(False)
        self.btn_refresh_catalog.setEnabled(False)
        self.lbl_catalog_status.setText(f"🔍 Conectando a '{source.name}' e listando obras da página {page}...")
        self.lbl_catalog_status.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-style: italic;")

        self.table_mangas.setRowCount(0)

        self.catalog_worker = MangaCatalogWorker(source, page=page, force_refresh=force_refresh, parent=self)
        self.catalog_worker.finished_signal.connect(self._on_catalog_loaded)
        self.catalog_worker.error_signal.connect(self._on_catalog_error)
        self.catalog_worker.status_signal.connect(lambda msg: self.lbl_catalog_status.setText(msg))
        self.catalog_worker.start()

    def _on_catalog_loaded(self, items: list, page: int):
        """Atualiza a tabela de mangás com os dados obtidos da fonte."""
        self.btn_refresh_catalog.setEnabled(True)
        self.current_manga_items = items
        self.table_mangas.setRowCount(len(items))

        if not items:
            self.lbl_catalog_status.setText(f"Nenhum mangá encontrado na página {page} desta fonte.")
            self.lbl_catalog_status.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 11px;")
            self.btn_next_page.setEnabled(False)
            return

        self.btn_next_page.setEnabled(len(items) >= 15)
        self.lbl_catalog_status.setText(f"✓ {len(items)} obras carregadas com sucesso.")
        self.lbl_catalog_status.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 11px;")

        covers_to_fetch = []

        for row, item in enumerate(items):
            # Coluna 0: Miniatura de Capa (ampliada 65x90 e interativa com pop-up ampliado no hover)
            lbl_cover = HoverableCoverLabel(
                title=item["title"],
                source_name=item.get("source_name", ""),
                popup=self.cover_popup,
                parent=self.table_mangas
            )
            lbl_cover.setFixedSize(65, 90)
            lbl_cover.setAlignment(Qt.AlignCenter)
            lbl_cover.setStyleSheet(f"background-color: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER_SUBTLE}; border-radius: 4px;")
            lbl_cover.setText("📖")
            self.table_mangas.setCellWidget(row, 0, lbl_cover)

            # Coluna 1: Título da Obra
            item_title = QTableWidgetItem(item["title"])
            item_title.setToolTip(f"{item['title']}\n{item['url']}")
            self.table_mangas.setItem(row, 1, item_title)

            # Coluna 2: Total de Capítulos
            ch_info = item.get("chapter_info") or "Disponível"
            item_chaps = QTableWidgetItem(ch_info)
            item_chaps.setTextAlignment(Qt.AlignCenter)
            item_chaps.setToolTip(ch_info)
            self.table_mangas.setItem(row, 2, item_chaps)

            # Coluna 3: Disponibilidade
            lbl_status = QLabel("🟢 Online")
            lbl_status.setAlignment(Qt.AlignCenter)
            lbl_status.setStyleSheet("""
                color: #A3E635;
                background-color: rgba(163, 230, 53, 0.12);
                border: 1px solid rgba(163, 230, 53, 0.3);
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 11px;
                font-weight: 600;
            """)
            self.table_mangas.setCellWidget(row, 3, lbl_status)

            # Coluna 4: Botão de Download
            btn_download = QPushButton("⬇️ Baixar")
            btn_download.setObjectName("PrimaryBtn")
            btn_download.setFixedHeight(28)
            btn_download.setToolTip("Selecionar capítulos e enviar para a fila de downloads")
            btn_download.clicked.connect(lambda checked, m=item: self._on_download_manga_from_catalog(m))
            self.table_mangas.setCellWidget(row, 4, btn_download)

            if item.get("cover_url"):
                covers_to_fetch.append((row, item["cover_url"]))

        # Iniciar carregamento assíncrono das capas
        if covers_to_fetch and self.current_explore_source:
            headers = {"Referer": self.current_explore_source.base_url}
            self.cover_worker = CoverThumbnailWorker(covers_to_fetch, headers=headers, parent=self)
            self.cover_worker.cover_loaded.connect(self._on_cover_thumbnail_loaded)
            self.cover_worker.start()

    def _on_catalog_error(self, err_msg: str):
        """Trata erros no carregamento do catálogo."""
        self.btn_refresh_catalog.setEnabled(True)
        self.lbl_catalog_status.setText(f"❌ Falha ao carregar catálogo: {err_msg}")
        self.lbl_catalog_status.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 11px; font-weight: 500;")
        self.log(f"[CATÁLOGO] Erro ao carregar: {err_msg}")

    def _on_cover_thumbnail_loaded(self, row_idx: int, img_bytes: bytes):
        """Aplica a miniatura da capa na célula da tabela assim que o download terminar."""
        if row_idx < self.table_mangas.rowCount():
            pix = QPixmap()
            if pix.loadFromData(img_bytes):
                lbl = self.table_mangas.cellWidget(row_idx, 0)
                if isinstance(lbl, HoverableCoverLabel):
                    lbl.set_cover_pixmap(pix)
                elif isinstance(lbl, QLabel):
                    lbl.setPixmap(pix.scaled(65, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _prev_page(self):
        if hasattr(self, 'cover_popup'):
            self.cover_popup.hide_preview()
        if self.current_explore_page > 1:
            self.current_explore_page -= 1
            self._load_current_page(force_refresh=False)

    def _next_page(self):
        if hasattr(self, 'cover_popup'):
            self.cover_popup.hide_preview()
        self.current_explore_page += 1
        self._load_current_page(force_refresh=False)

    def _filter_mangas_in_view(self, text: str):
        """Filtra instantaneamente os mangás exibidos na tabela da fonte atual."""
        if hasattr(self, 'cover_popup'):
            self.cover_popup.hide_preview()
        filter_txt = text.strip().lower()
        for row in range(self.table_mangas.rowCount()):
            title_item = self.table_mangas.item(row, 1)
            if title_item:
                match = filter_txt in title_item.text().lower()
                self.table_mangas.setRowHidden(row, not match)

    def _on_manga_cell_double_clicked(self, row: int, col: int):
        """Permite dar duplo clique em um mangá para abrir o diálogo de download."""
        if 0 <= row < len(self.current_manga_items):
            self._on_download_manga_from_catalog(self.current_manga_items[row])

    def _on_download_manga_from_catalog(self, item: dict):
        """Abre o diálogo de escolha de capítulos e enfileira a obra com confirmação oficial."""
        title = item.get("title", "Obra")
        url = item.get("url", "")
        source_name = item.get("source_name", "")
        default_outdir = self.txt_outdir.text().strip() or "download"

        dlg = ChapterDownloadDialog(
            manga_title=title,
            manga_url=url,
            source_name=source_name,
            default_outdir=default_outdir,
            parent=self
        )
        if dlg.exec_() == QDialog.Accepted and dlg.result_config:
            cfg = dlg.result_config
            task_id = f"{time.time()}_{len(self.tasks)}"
            provider_obj = ProviderRegistry.get_provider_for_url(url)
            provider_name = provider_obj.name if provider_obj else "keiyoushi"
            lang_code = item.get("lang") or "pt-br"

            task = QueueTask(
                id=task_id,
                url=url,
                title=title,
                cover_url=item.get("cover_url", ""),
                provider=provider_name,
                lang_code=lang_code,
                available_langs=[lang_code],
                chapter_mode=cfg["chapter_mode"],
                chapter_mode_value=cfg["chapter_mode_value"],
                all_chapters=[],
                selected_chapters=[],
                outdir=cfg["outdir"],
                cbz=cfg["cbz"],
                datasaver=False,
                estimated_size_mb=0.0,
                estimated_seconds=0.0,
                status=TaskStatus.PENDING
            )
            self.tasks.append(task)
            StateManager.save_queue(self.tasks)
            self._refresh_table()

            self.log(f"[FILA] Mangás foram pra fila! Obra: '{title}' (Capítulos: {cfg['chapter_mode'].value}).")

            # Confirmação exata requerida pelo usuário!
            QMessageBox.information(
                self,
                "Sucesso",
                "Mangás foram pra fila!"
            )

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
                self.txt_mode_val.setPlaceholderText("Ex: 5")
                self.lbl_mode_example.setText("Ex: 5 ou 415.1  (apenas um capítulo)")
                self.lbl_mode_example.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-weight: 500;")
            elif mode_val == ChapterMode.RANGE.value:
                self.txt_mode_val.setPlaceholderText("Ex: 1-10 ou 1,10")
                self.lbl_mode_example.setText("Ex: 1-10 ou 1,10  (intervalo do cap 1 ao 10)")
                self.lbl_mode_example.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-weight: 500;")
            elif mode_val == ChapterMode.CHUNK.value:
                self.txt_mode_val.setPlaceholderText("Ex: 10")
                self.lbl_mode_example.setText("Ex: 10  (baixa em lotes de 10 em 10)")
                self.lbl_mode_example.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-weight: 500;")
            else:
                self.txt_mode_val.setPlaceholderText("Ex: 1, 6, 10 ou 1-10")
                self.lbl_mode_example.setText("Ex: 1, 6, 10 ou 1-10, 15  (lista personalizada)")
                self.lbl_mode_example.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-weight: 500;")
        else:
            self.txt_mode_val.setEnabled(False)
            self.txt_mode_val.clear()
            self.txt_mode_val.setPlaceholderText("Todos os caps")
            if mode_val == ChapterMode.LATEST.value:
                self.lbl_mode_example.setText("(Baixará apenas o capítulo mais recente)")
            else:
                self.lbl_mode_example.setText("Ex: 1,10 / 1-10 / 1, 6, 10")
            self.lbl_mode_example.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic;")
        self._update_preview_calc()

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
                self.log(f"[AVISO] O caminho especificado não é uma pasta válida: {norm_outdir}")
                return
            if sys.platform == "win32":
                os.startfile(norm_outdir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", norm_outdir])
            else:
                subprocess.Popen(["xdg-open", norm_outdir])
        except Exception as e:
            self.log(f"[ERRO] Falha ao abrir pasta de destino: {e}")

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

    def open_keiyoushi_catalog(self):
        """Abre a janela de pesquisa e exploração das 2.200+ fontes do index.pb."""
        try:
            from keiyoushi_dialog import KeiyoushiCatalogDialog
            dialog = KeiyoushiCatalogDialog(self)
            dialog.url_selected_signal.connect(self._on_catalog_url_selected)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao abrir catálogo: {e}")

    def _on_catalog_url_selected(self, base_url: str):
        self.txt_urls.setPlainText(base_url)
        self.log(f"[CATÁLOGO] Fonte selecionada: {base_url}")
        self.lbl_card_status.setVisible(True)
        self.lbl_card_status.setText(f"💡 Fonte carregada: {base_url}. Complete com a rota do mangá e clique em 'Analisar Link'.")

    def start_analysis(self):
        """Inicia a análise em background da URL informada."""
        raw_text = self.txt_urls.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Aviso", "Por favor, digite ou cole a URL do mangá a ser analisado.")
            return

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            return

        url = lines[0]
        self.btn_analyze_link.setEnabled(False)
        self.btn_analyze_link.setText("Analisando...")
        self.lbl_card_status.setVisible(True)
        self.lbl_card_status.setText("🔍 Analisando obra e capítulos... Aguarde.")
        self.lbl_card_status.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 12px; font-style: italic;")

        self.analysis_worker = MangaAnalysisWorker(url, lang_code="pt-br")
        self.analysis_worker.status_signal.connect(self.on_analysis_status)
        self.analysis_worker.finished_signal.connect(self.on_analysis_finished)
        self.analysis_worker.error_signal.connect(self.on_analysis_error)
        self.analysis_worker.start()

    def on_analysis_status(self, msg: str):
        self.lbl_card_status.setText(f"🔍 {msg}")
        self.log(f"[ANÁLISE] {msg}")

    def on_analysis_finished(self, data: dict):
        self.btn_analyze_link.setEnabled(True)
        self.btn_analyze_link.setText("🔍 Analisar Link")
        self.current_analysis = data

        self.lbl_card_status.setText("")
        self.lbl_card_status.setVisible(False)
        self.lbl_preview_title.setText(data["title"])
        self.lbl_preview_prov.setText(data.get("provider_display", "MangaDex"))
        chaps_count = len(data.get("chapters", []))
        self.lbl_preview_chaps_badge.setText(f"{chaps_count} cap(s)")

        # Carregar Capa
        cover_bytes = data.get("cover_bytes")
        if cover_bytes:
            pix = QPixmap()
            if pix.loadFromData(cover_bytes):
                self.lbl_preview_cover.setPixmap(pix.scaled(85, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.lbl_preview_cover.setText("Capa")
        else:
            self.lbl_preview_cover.setText("Sem Capa")

        # Idiomas disponíveis
        self.combo_lang.blockSignals(True)
        self.combo_lang.clear()
        available_langs = data.get("available_langs", ["pt-br"])
        default_idx = 0
        for idx, lcode in enumerate(available_langs):
            disp = get_language_display_name(lcode)
            self.combo_lang.addItem(disp, lcode)
            if lcode == data.get("current_lang", "pt-br"):
                default_idx = idx
        self.combo_lang.setCurrentIndex(default_idx)
        self.combo_lang.blockSignals(False)

        self.top_group.setMinimumHeight(325)
        self.card_analysis.setMinimumHeight(145)
        self.panel_analyzed.show()
        self._update_preview_calc()
        self.log(f"[ANÁLISE] Obra identificada: '{data['title']}' ({chaps_count} capítulos disponíveis).")

    def on_analysis_error(self, err_msg: str):
        self.btn_analyze_link.setEnabled(True)
        self.btn_analyze_link.setText("🔍 Analisar Link")
        self.panel_analyzed.hide()
        self.card_analysis.setMinimumHeight(40)
        self.top_group.setMinimumHeight(175)
        self.lbl_card_status.setVisible(True)
        self.lbl_card_status.setText(f"❌ Falha na análise: {err_msg}")
        self.lbl_card_status.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 12px; font-weight: 500;")
        self.log(f"[ERRO] Falha ao analisar obra: {err_msg}")
        QMessageBox.critical(self, "Erro de Análise", f"Não foi possível analisar o link informado:\n\n{err_msg}")

    def on_lang_changed(self, idx: int):
        if not hasattr(self, "current_analysis") or not self.current_analysis:
            return
        new_lang = self.combo_lang.currentData()
        if not new_lang or new_lang == self.current_analysis.get("current_lang"):
            return

        self.combo_lang.setEnabled(False)
        self.btn_add_analyzed.setEnabled(False)
        self.lbl_preview_chaps_badge.setText("Carregando...")

        self.lang_worker = LanguageSwitchWorker(
            self.current_analysis["url"],
            self.current_analysis["provider"],
            new_lang
        )
        self.lang_worker.status_signal.connect(self.on_analysis_status)
        self.lang_worker.finished_signal.connect(self.on_lang_switch_finished)
        self.lang_worker.error_signal.connect(self.on_lang_switch_error)
        self.lang_worker.start()

    def on_lang_switch_finished(self, new_lang_code: str, new_chapters: list):
        self.combo_lang.setEnabled(True)
        self.btn_add_analyzed.setEnabled(True)
        self.current_analysis["current_lang"] = new_lang_code
        self.current_analysis["chapters"] = new_chapters
        self.lbl_preview_chaps_badge.setText(f"{len(new_chapters)} cap(s)")
        self._update_preview_calc()
        lang_name = get_language_display_name(new_lang_code)
        self.log(f"[IDIOMA] Capítulos atualizados para {lang_name}: {len(new_chapters)} capítulos.")

    def on_lang_switch_error(self, err_msg: str):
        self.combo_lang.setEnabled(True)
        self.btn_add_analyzed.setEnabled(True)
        self.lbl_preview_chaps_badge.setText("Erro ao carregar")
        self.log(f"[ERRO] Falha ao alternar idioma: {err_msg}")
        QMessageBox.warning(self, "Erro de Idioma", f"Não foi possível carregar os capítulos no idioma selecionado:\n{err_msg}")

    def _update_preview_calc(self):
        if not hasattr(self, "current_analysis") or not self.current_analysis:
            return
        chapters = self.current_analysis.get("chapters", [])
        if not chapters:
            self.lbl_preview_calc.setText("Selecionados: 0 caps  |  Tamanho Est.: ~0 MB  |  Tempo Est.: ~0s")
            return

        mode_val = self.combo_mode.currentData()
        try:
            mode_enum = ChapterMode(mode_val)
        except Exception:
            mode_enum = ChapterMode.ALL

        mode_custom = self.txt_mode_val.text().strip()
        try:
            selected = parse_chapter_selection(chapters, mode_enum, mode_custom)
        except Exception:
            selected = chapters

        datasaver = self.cb_datasaver.isChecked()
        avg_size = AVG_PAGE_SIZE_MANGADEX_SAVER_MB if datasaver else AVG_PAGE_SIZE_MANGADEX_ORIGINAL_MB
        total_pages = sum(ch.get("pages_count", 25) for ch in selected)
        est_mb = total_pages * avg_size
        est_sec = max(5.0, est_mb / 2.5) if est_mb > 0 else 0

        self.lbl_preview_calc.setText(
            f"Selecionados: {len(selected)}/{len(chapters)} caps  |  "
            f"Tamanho Est.: ~{format_size(est_mb)}  |  "
            f"Tempo Est.: ~{format_time(est_sec)}"
        )

    def add_analyzed_to_queue(self):
        """Adiciona a obra atualmente analisada à fila com todas as configurações."""
        if not hasattr(self, "current_analysis") or not self.current_analysis:
            QMessageBox.warning(self, "Aviso", "Nenhuma obra analisada. Clique em '🔍 Analisar Link' primeiro.")
            return

        url = self.current_analysis["url"]
        if any(t.url == url for t in self.tasks):
            reply = QMessageBox.question(
                self,
                "Obra Já Existente",
                "Esta obra já está na fila. Deseja adicioná-la novamente?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        chapters = self.current_analysis.get("chapters", [])
        if not chapters:
            QMessageBox.warning(self, "Sem Capítulos", "Nenhum capítulo disponível para o idioma selecionado.")
            return

        mode_val = self.combo_mode.currentData()
        try:
            mode_enum = ChapterMode(mode_val)
        except Exception:
            mode_enum = ChapterMode.ALL

        mode_custom = self.txt_mode_val.text().strip()
        selected = parse_chapter_selection(chapters, mode_enum, mode_custom)
        if not selected:
            QMessageBox.warning(self, "Seleção Vazia", "Nenhum capítulo corresponde ao filtro selecionado.")
            return

        datasaver = self.cb_datasaver.isChecked()
        cbz = self.cb_cbz.isChecked()
        outdir = self.txt_outdir.text().strip() or "download"
        lang_code = self.current_analysis.get("current_lang", "pt-br")

        avg_size = AVG_PAGE_SIZE_MANGADEX_SAVER_MB if datasaver else AVG_PAGE_SIZE_MANGADEX_ORIGINAL_MB
        total_pages = sum(ch.get("pages_count", 25) for ch in selected)
        est_mb = total_pages * avg_size
        est_sec = max(5.0, est_mb / 2.5) if est_mb > 0 else 0

        task_id = str(time.time()) + f"_{len(self.tasks)}"
        new_task = QueueTask(
            id=task_id,
            url=url,
            title=self.current_analysis["title"],
            cover_url=self.current_analysis.get("cover_url", ""),
            provider=self.current_analysis["provider"],
            lang_code=lang_code,
            available_langs=self.current_analysis.get("available_langs", [lang_code]),
            chapter_mode=mode_enum,
            chapter_mode_value=mode_custom,
            all_chapters=chapters,
            selected_chapters=selected,
            outdir=outdir,
            cbz=cbz,
            datasaver=datasaver,
            estimated_size_mb=est_mb,
            estimated_seconds=est_sec,
            status=TaskStatus.READY
        )
        self.tasks.append(new_task)
        StateManager.save_queue(self.tasks)
        self._refresh_table()

        lang_name = get_language_display_name(lang_code)
        self.log(f"[FILA] '{new_task.title}' adicionada à fila: {len(selected)} cap(s) em {lang_name} (~{format_size(est_mb)}).")
        self.lbl_card_status.setVisible(True)
        self.lbl_card_status.setText(f"✓ '{new_task.title}' adicionada com sucesso à fila!")
        self.lbl_card_status.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 12px; font-weight: 600;")

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
        # Limpar widgets de células existentes para evitar widgets fantasmas no viewport
        for r in range(self.table.rowCount()):
            old_w = self.table.cellWidget(r, 7)
            if old_w:
                self.table.removeCellWidget(r, 7)
                old_w.setParent(None)
                old_w.deleteLater()

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
            if task.provider == "keiyoushi":
                from keiyoushi_catalog import catalog
                src = catalog.find_source_by_url(task.url)
                prov_name = f"{src.name} ({src.lang})" if src else "Keiyoushi"
            else:
                prov_name = ProviderRegistry.get_provider(task.provider).display_name
            item_prov = QTableWidgetItem(prov_name)
            item_prov.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_prov)

            # 3: Idioma
            lang_display = (task.lang_code or "pt-br").upper()
            item_lang = QTableWidgetItem(lang_display)
            item_lang.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, item_lang)

            # 4: Capítulos
            chaps_desc = f"{len(task.selected_chapters)} caps" if task.selected_chapters else "Pendente"
            item_chaps = QTableWidgetItem(chaps_desc)
            item_chaps.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_chaps)

            # 5: Tamanho Est.
            if task.status == TaskStatus.COMPLETED and task.real_size_bytes > 0:
                size_str = format_size(task.real_size_bytes, is_bytes=True)
            else:
                size_str = f"~{format_size(task.estimated_size_mb)}" if task.estimated_size_mb > 0 else "-"
            item_size = QTableWidgetItem(size_str)
            item_size.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, item_size)

            # 6: Tempo Est.
            time_str = f"~{format_time(task.estimated_seconds)}" if task.estimated_seconds > 0 else "-"
            item_time = QTableWidgetItem(time_str)
            item_time.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 6, item_time)

            # 7: Barra de Progresso
            pbar = QProgressBar()
            pbar.setValue(task.progress_percent)
            pbar.setAlignment(Qt.AlignCenter)
            if task.status == TaskStatus.COMPLETED:
                pbar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_SUCCESS}; }}")
            elif task.status == TaskStatus.ERROR:
                pbar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_ERROR}; }}")
            self.table.setCellWidget(row, 7, pbar)

            # 8: Status
            item_status = QTableWidgetItem(task.status.value)
            item_status.setTextAlignment(Qt.AlignCenter)

            if task.status == TaskStatus.COMPLETED:
                item_status.setForeground(QColor(COLOR_SUCCESS))
                item_status.setIcon(get_icon("check-circle", color=COLOR_SUCCESS, size=16, weight="fill"))
                item_status.setToolTip("Obra concluída com sucesso!")
            elif task.status == TaskStatus.READY:
                item_status.setForeground(QColor(COLOR_ACCENT))
                item_status.setIcon(get_icon("check-circle", color=COLOR_ACCENT, size=16))
                item_status.setToolTip("Obra analisada e pronta para download.")
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

            self.table.setItem(row, 8, item_status)

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

        pending_exists = any(t.status in [TaskStatus.PENDING, TaskStatus.READY, TaskStatus.STOPPED, TaskStatus.ERROR] for t in self.tasks)
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
        if col == 8 and 0 <= row < len(self.tasks):
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
        if self.cover_worker and self.cover_worker.isRunning():
            self.cover_worker.cancel()
            self.cover_worker.wait(500)
        if self.catalog_worker and self.catalog_worker.isRunning():
            self.catalog_worker.wait(500)

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
                try:
                    for p in ProviderRegistry.get_providers():
                        p.close_session()
                except Exception:
                    pass
                event.accept()
            else:
                event.ignore()
        else:
            StateManager.save_queue(self.tasks)
            try:
                for p in ProviderRegistry.get_providers():
                    p.close_session()
            except Exception:
                pass
            event.accept()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
