#!/usr/bin/env python3
"""
manga_core.py - Núcleo de gerenciamento de downloads, fila de tarefas,
estimativas de tempo/tamanho, persistência e controle de execução (Pause/Resume/Stop).
"""

import html
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib.parse import urlparse
from urllib3.util.retry import Retry

logger = logging.getLogger("manga_core")

# ----------------------------------------------------------------------
# Constantes globais
# ----------------------------------------------------------------------
DEFAULT_WORKERS = 4
STATE_FILE = "queue_state.json"
MANGADEX_RATINGS = "&".join([
    "contentRating[]=safe", "contentRating[]=suggestive",
    "contentRating[]=erotica", "contentRating[]=pornographic"
])

# Médias estimadas de tamanho por página em MB
AVG_PAGE_SIZE_MANGADEX_ORIGINAL_MB = 1.20  # ~25-35 MB / cap (25 págs)
AVG_PAGE_SIZE_MANGADEX_SAVER_MB = 0.30     # ~7.5 MB / cap
AVG_PAGE_SIZE_MANGALIVRE_MB = 0.40         # ~10 MB / cap
AVG_PAGE_SIZE_GENERIC_MB = 0.50            # ~12.5 MB / cap para Madara/Universal
AVG_PAGES_PER_CHAPTER = 25                 # estimativa padrão se não enumerado
BASELINE_DOWNLOAD_SPEED_MB_S = 2.5         # estimativa inicial de velocidade


class TaskStatus(str, Enum):
    PENDING = "Na Fila"
    ANALYZING = "Analisando..."
    READY = "Pronto"
    DOWNLOADING = "Baixando"
    PAUSED = "Pausado"
    COMPLETED = "Concluído"
    ERROR = "Erro"
    STOPPED = "Interrompido"


class ChapterMode(str, Enum):
    ALL = "all"            # Todos os capítulos
    SINGLE = "single"      # Único capítulo específico (ex: 5)
    RANGE = "range"        # Intervalo X a Y (ex: 1 a 10)
    CHUNK = "chunk"        # Blocos de N em N (ex: 10 em 10)
    LATEST = "latest"      # Apenas o mais recente
    CUSTOM = "custom"      # Expressão personalizada (ex: 1, 3, 5-10)


@dataclass
class QueueTask:
    id: str
    url: str
    provider: str = "mangadex"  # 'mangadex' ou 'mangalivre'
    title: str = "Carregando..."
    cover_url: str = ""
    lang_code: str = "pt-br"
    available_langs: List[str] = field(default_factory=list)
    chapter_mode: ChapterMode = ChapterMode.ALL
    chapter_mode_value: str = ""  # valor associado (ex: '5', '1-10', '10')
    all_chapters: List[Dict[str, Any]] = field(default_factory=list)
    selected_chapters: List[Dict[str, Any]] = field(default_factory=list)
    downloaded_chapter_ids: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    error_message: str = ""
    estimated_size_mb: float = 0.0
    estimated_seconds: float = 0.0
    real_size_bytes: int = 0
    progress_percent: int = 0
    current_chapter_num: str = "-"
    datasaver: bool = False
    cbz: bool = True
    outdir: str = "download"
    total_pages_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["chapter_mode"] = self.chapter_mode.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueueTask":
        data_copy = dict(data)
        status_val = data_copy.get("status", TaskStatus.PENDING.value)
        try:
            data_copy["status"] = TaskStatus(status_val)
        except ValueError:
            data_copy["status"] = TaskStatus.PENDING

        mode_val = data_copy.get("chapter_mode", ChapterMode.ALL.value)
        try:
            data_copy["chapter_mode"] = ChapterMode(mode_val)
        except ValueError:
            data_copy["chapter_mode"] = ChapterMode.ALL

        return cls(**data_copy)


# ----------------------------------------------------------------------
# Funções Utilitárias & Hardening de Filesystem
# ----------------------------------------------------------------------
WINDOWS_RESERVED_NAMES: Set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}


def clean_filename(name: str, max_length: int = 120, fallback: str = "Sem Titulo") -> str:
    """
    Higieniza nomes para arquivos/diretórios de forma segura no Windows, Linux e macOS:
    - Remove caracteres proibidos [/\\:*?"<>|]
    - Remove caracteres de controle ASCII (\x00-\x1f, \x7f)
    - Trata nomes de dispositivos reservados no Windows (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    - Trunca comprimento para evitar estouro de caminhos (MAX_PATH)
    - Remove pontos e espaços nas extremidades
    - Garante fallback caso o resultado seja vazio
    """
    if not name or not isinstance(name, str):
        return fallback

    # Remove caracteres de controle e nulos
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', name)
    # Substitui caracteres proibidos no Windows/Linux/macOS
    cleaned = re.sub(r'[/\\:*?"<>|]', '-', cleaned)
    # Colapsa múltiplos espaços
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Remove pontos e espaços nas extremidades
    cleaned = cleaned.strip('. ')

    if not cleaned:
        cleaned = fallback

    # Trata nomes reservados do Windows (ex: 'con', 'aux.txt', 'nul')
    name_root = cleaned.split('.')[0].upper()
    if name_root in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # Truncamento de tamanho seguro preservando extensão se houver
    if len(cleaned) > max_length:
        if '.' in cleaned and not cleaned.startswith('.'):
            base, ext = cleaned.rsplit('.', 1)
            ext = f".{ext[:10]}"
            allowed_base = max(5, max_length - len(ext))
            cleaned = f"{base[:allowed_base].rstrip('. ')}{ext}"
        else:
            cleaned = cleaned[:max_length].rstrip('. ')

    return cleaned or fallback


def safe_path_join(base_directory: str, *parts: str) -> str:
    """
    Junta caminhos de forma segura e garante que o destino resolvido
    permaneça estritamente dentro de base_directory (prevenção contra Path Traversal).
    """
    base_real = os.path.realpath(os.path.abspath(base_directory))

    # Sanitiza cada componente relativo
    sanitized_parts = []
    for p in parts:
        if not p:
            continue
        p_str = str(p)
        # Se contiver separadores de caminho ou tentativa de traversal (..), sanitiza cada segmento
        segments = [clean_filename(s) for s in re.split(r'[\\/]+', p_str) if s and s not in ('.', '..')]
        sanitized_parts.extend(segments)

    target_path = os.path.realpath(os.path.abspath(os.path.join(base_real, *sanitized_parts)))

    try:
        common = os.path.commonpath([base_real, target_path])
    except ValueError:
        raise ValueError(f"Path traversal detectado: {target_path} fora de {base_real}")

    if common != base_real:
        raise ValueError(f"Path traversal detectado: {target_path} reside fora de {base_real}")

    return target_path


from providers import ProviderRegistry


def pad_filename(filename: str) -> str:
    """Preenche números com zeros à esquerda (ex: 1.jpg -> 001.jpg)."""
    return re.sub(r'(\d+)', lambda m: m.group(1).zfill(3), filename)


def format_size(size_mb_or_bytes: float, is_bytes: bool = False) -> str:
    """Formata tamanho de forma legível (KB, MB, GB)."""
    bytes_val = size_mb_or_bytes if is_bytes else size_mb_or_bytes * 1024 * 1024
    if bytes_val < 1024:
        return f"{bytes_val:.0f} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def format_time(seconds: float) -> str:
    """Formata segundos em HH:MM:SS ou MM:SS."""
    if seconds <= 0:
        return "00s"
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    elif minutes > 0:
        return f"{minutes:02d}m {secs:02d}s"
    else:
        return f"{secs:02d}s"


def create_session() -> requests.Session:
    """Cria uma sessão requests com retries automáticos e pool de conexões."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.timeout = (10, 30)
    return session


# ----------------------------------------------------------------------
# Filtro e Seleção de Capítulos
# ----------------------------------------------------------------------
def parse_chapter_selection(
    all_chapters: List[Dict[str, Any]],
    mode: ChapterMode,
    value: str = ""
) -> List[Dict[str, Any]]:
    """
    Filtra a lista completa de capítulos com base no modo selecionado:
    - ALL: Todos
    - SINGLE: Único número (ex: '5' ou '12.5')
    - RANGE: Início e Fim (ex: '1-10' ou '1~10')
    - CHUNK: Blocos (ex: '1-10', '11-20', ou tamanho '10')
    - LATEST: Apenas o último
    - CUSTOM: Expressão separada por vírgula (ex: '1, 3, 5-10')
    """
    if not all_chapters:
        return []

    if mode == ChapterMode.ALL:
        return list(all_chapters)

    if mode == ChapterMode.LATEST:
        return [all_chapters[-1]]

    def get_num(ch: Dict[str, Any]) -> Optional[float]:
        c = ch.get("chapter") or ch.get("attributes", {}).get("chapter")
        if c is None:
            return None
        try:
            return float(c)
        except ValueError:
            return None

    selected = []
    clean_val = value.strip().replace("~", "-")

    if mode == ChapterMode.SINGLE:
        try:
            target = float(clean_val)
            for ch in all_chapters:
                n = get_num(ch)
                if n is not None and n == target:
                    selected.append(ch)
        except ValueError:
            pass

    elif mode == ChapterMode.RANGE or (mode == ChapterMode.CHUNK and "-" in clean_val):
        try:
            if "-" in clean_val:
                s_str, e_str = clean_val.split("-", 1)
                start = float(s_str.strip())
                end = float(e_str.strip())
                min_val, max_val = min(start, end), max(start, end)
                for ch in all_chapters:
                    n = get_num(ch)
                    if n is not None and min_val <= n <= max_val:
                        if ch not in selected:
                            selected.append(ch)
            else:
                # Se passou apenas um número como chunk (ex: 10) pega os primeiros N
                chunk_size = int(clean_val)
                selected = all_chapters[:chunk_size]
        except (ValueError, IndexError):
            pass

    elif mode == ChapterMode.CHUNK:
        # Se for um valor numérico inteiro simples (ex: 10 -> primeiros 10)
        try:
            size = int(clean_val)
            selected = all_chapters[:size]
        except ValueError:
            pass

    elif mode == ChapterMode.CUSTOM:
        parts = [p.strip() for p in clean_val.split(",") if p.strip()]
        for part in parts:
            if "-" in part:
                try:
                    s_str, e_str = part.split("-", 1)
                    s_num, e_num = float(s_str.strip()), float(e_str.strip())
                    for ch in all_chapters:
                        n = get_num(ch)
                        if n is not None and min(s_num, e_num) <= n <= max(s_num, e_num):
                            if ch not in selected:
                                selected.append(ch)
                except ValueError:
                    pass
            elif part.lower() == "oneshot":
                for ch in all_chapters:
                    if get_num(ch) is None and ch not in selected:
                        selected.append(ch)
            else:
                try:
                    target = float(part)
                    for ch in all_chapters:
                        n = get_num(ch)
                        if n is not None and n == target and ch not in selected:
                            selected.append(ch)
                except ValueError:
                    pass

    return selected


# ----------------------------------------------------------------------
# MangaDex API Helpers
# ----------------------------------------------------------------------
GROUP_CACHE: Dict[str, str] = {}


def find_id_in_url(url: str) -> Optional[str]:
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    for part in url.split('/'):
        clean_p = part.split('?')[0].strip()
        if uuid_pattern.match(clean_p):
            return clean_p
        if clean_p.isdigit():
            return clean_p
    return None


def get_mangadex_uuid(manga_id_or_url: str, session: requests.Session) -> str:
    extracted = find_id_in_url(manga_id_or_url) or manga_id_or_url
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', extracted, re.IGNORECASE):
        return extracted
    try:
        int_id = int(extracted)
        headers = {'Content-Type': 'application/json'}
        payload = json.dumps({"type": "manga", "ids": [int_id]})
        r = session.post("https://api.mangadex.org/legacy/mapping", headers=headers, data=payload, timeout=10)
        r.raise_for_status()
        return r.json()[0]["data"]["attributes"]["newId"]
    except Exception as e:
        raise ValueError(f"ID/URL inválido do MangaDex: '{manga_id_or_url}' ({e})")


def get_mangadex_info(uuid: str, session: requests.Session) -> Dict[str, Any]:
    r = session.get(f"https://api.mangadex.org/manga/{uuid}", timeout=10)
    r.raise_for_status()
    return r.json()["data"]["attributes"]


def choose_mangadex_title(attributes: Dict[str, Any], lang_code: str = "pt-br") -> str:
    title_dict = attributes.get("title", {})
    title = title_dict.get(lang_code)
    if not title:
        for alt in attributes.get("altTitles", []):
            if lang_code in alt:
                title = alt[lang_code]
                break
    if not title:
        title = title_dict.get("en")
    if not title and title_dict:
        title = next(iter(title_dict.values()))
    if not title:
        title = "Título desconhecido"
    return html.unescape(title)


def get_mangadex_chapters(
    uuid: str,
    lang_code: str,
    session: requests.Session
) -> List[Dict[str, Any]]:
    params = {
        "translatedLanguage[]": lang_code,
        "order[volume]": "asc",
        "order[chapter]": "asc",
        "limit": 500
    }
    url = f"https://api.mangadex.org/manga/{uuid}/feed?" + MANGADEX_RATINGS
    results = []
    offset = 0
    while True:
        p = dict(params)
        p["offset"] = offset
        r = session.get(url, params=p, timeout=10)
        r.raise_for_status()
        data = r.json()
        batch = data.get("data", [])
        results.extend(batch)
        if len(batch) < 500:
            break
        offset += 500

    # Deduplicar capítulos com o mesmo número mantendo a versão mais recente
    dedup: Dict[str, Dict[str, Any]] = {}
    for ch in results:
        cnum = ch["attributes"]["chapter"] or "Oneshot"
        created = ch["attributes"].get("createdAt", "")
        if cnum not in dedup or created > dedup[cnum]["attributes"].get("createdAt", ""):
            dedup[cnum] = ch

    def sort_key(ch: Dict[str, Any]) -> float:
        num = ch["attributes"]["chapter"]
        try:
            return float(num) if num is not None else 9999.0
        except ValueError:
            return 9999.0

    return sorted(dedup.values(), key=sort_key)


def get_mangadex_group_names(chapter: Dict[str, Any], session: requests.Session) -> str:
    group_ids = [rel["id"] for rel in chapter.get("relationships", []) if rel["type"] == "scanlation_group"]
    names = []
    for gid in group_ids:
        if gid not in GROUP_CACHE:
            try:
                r = session.get(f"https://api.mangadex.org/group/{gid}", timeout=10)
                if r.status_code == 200:
                    GROUP_CACHE[gid] = r.json()["data"]["attributes"]["name"]
                else:
                    GROUP_CACHE[gid] = f"Grupo-{gid[:6]}"
            except Exception:
                GROUP_CACHE[gid] = f"Grupo-{gid[:6]}"
        names.append(GROUP_CACHE[gid])
    return " & ".join(names) if names else "Desconhecido"


# ----------------------------------------------------------------------
# Motor de Estimativa de Tamanho e Tempo
# ----------------------------------------------------------------------
def calculate_task_estimates(
    task: QueueTask,
    measured_speed_mb_s: float = BASELINE_DOWNLOAD_SPEED_MB_S
) -> Tuple[float, float]:
    """
    Calcula (tamanho_estimado_mb, segundos_estimados) para uma tarefa.
    """
    chaps_to_download = [
        ch for ch in task.selected_chapters
        if ch.get("id") not in task.downloaded_chapter_ids
    ]
    num_chaps = len(chaps_to_download)
    if num_chaps == 0:
        return 0.0, 0.0

    # Estimativa de tamanho por página / capítulo
    if task.provider == "mangalivre":
        avg_mb_per_chap = AVG_PAGE_SIZE_MANGALIVRE_MB * AVG_PAGES_PER_CHAPTER
    elif task.provider in ("madara", "universal"):
        avg_mb_per_chap = AVG_PAGE_SIZE_GENERIC_MB * AVG_PAGES_PER_CHAPTER
    else:
        if task.datasaver:
            avg_mb_per_chap = AVG_PAGE_SIZE_MANGADEX_SAVER_MB * AVG_PAGES_PER_CHAPTER
        else:
            avg_mb_per_chap = AVG_PAGE_SIZE_MANGADEX_ORIGINAL_MB * AVG_PAGES_PER_CHAPTER

    total_mb = num_chaps * avg_mb_per_chap
    speed = max(0.5, measured_speed_mb_s)
    total_seconds = total_mb / speed

    return round(total_mb, 1), round(total_seconds, 1)


# ----------------------------------------------------------------------
# Persistência de Estado (Queue State)
# ----------------------------------------------------------------------
class StateManager:
    @staticmethod
    def save_queue(tasks: List[QueueTask], filepath: str = STATE_FILE) -> None:
        temp_path = filepath + ".tmp"
        try:
            data = [task.to_dict() for task in tasks]
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, filepath)
        except Exception as e:
            logger.warning("Falha ao salvar estado da fila: %s", e)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def load_queue(filepath: str = STATE_FILE) -> List[QueueTask]:
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [QueueTask.from_dict(d) for d in data]
        except Exception as e:
            logger.warning("Falha ao carregar estado da fila: %s", e)
            return []


# ----------------------------------------------------------------------
# Motor de Download com Pause, Resume e Cancelamento
# ----------------------------------------------------------------------
class ExecutionController:
    """Controla eventos de Pausa e Parada coordenados entre threads."""
    def __init__(self):
        self.pause_event = threading.Event()
        self.pause_event.set()  # set() = Executando; clear() = Pausado
        self.stop_event = threading.Event()  # set() = Parar imediatamente
        self.cancel_task_event = threading.Event()  # Cancelamento granular de tarefa ativa

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()  # destrava caso esteja pausado

    def cancel_current_task(self):
        """Cancela a execução da tarefa atual sem parar a fila inteira."""
        self.cancel_task_event.set()
        self.pause_event.set()  # destrava caso esteja pausado

    def is_task_cancelled(self) -> bool:
        return self.cancel_task_event.is_set()

    def reset_task_cancelled(self):
        self.cancel_task_event.clear()

    def reset(self):
        self.pause_event.set()
        self.stop_event.clear()
        self.cancel_task_event.clear()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    def check_pause_and_stop(self) -> bool:
        """
        Bloqueia enquanto estiver pausado.
        Retorna True se foi solicitado parada (stop) ou cancelamento da tarefa, False se pode prosseguir.
        """
        while not self.pause_event.is_set():
            if self.stop_event.is_set() or self.cancel_task_event.is_set():
                return True
            time.sleep(0.2)
        return self.stop_event.is_set() or self.cancel_task_event.is_set()


class DownloadEngine:
    """Motor central de execução de downloads com suporte a métricas ao vivo."""

    def __init__(self, controller: Optional[ExecutionController] = None):
        self.controller = controller or ExecutionController()
        self.session = create_session()
        self.bytes_downloaded_session = 0
        self.speed_history: List[Tuple[float, int]] = []  # (timestamp, bytes)
        self.current_speed_mb_s = BASELINE_DOWNLOAD_SPEED_MB_S

    def record_bytes(self, num_bytes: int):
        self.bytes_downloaded_session += num_bytes
        now = time.time()
        self.speed_history.append((now, num_bytes))
        # Manter histórico dos últimos 5 segundos para cálculo da velocidade móvel
        self.speed_history = [(t, b) for t, b in self.speed_history if now - t <= 5.0]
        if len(self.speed_history) > 1:
            total_bytes = sum(b for _, b in self.speed_history)
            duration = max(1.0, now - self.speed_history[0][0])
            self.current_speed_mb_s = (total_bytes / (1024 * 1024)) / duration

    def download_page_file(
        self,
        url: str,
        dest_path: str,
        session: requests.Session,
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Baixa uma página de imagem com checagem de pausa/parada e cálculo de bytes."""
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            return True

        if self.controller.check_pause_and_stop() or self.controller.is_task_cancelled():
            return False

        # Validação de segurança: apenas esquemas remotos válidos (HTTP/HTTPS) são permitidos
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
                logger.error("URL de imagem rejeitada por segurança (esquema inválido ou não remoto): %s", url)
                return False
        except Exception:
            logger.error("URL de imagem malformada rejeitada: %s", url)
            return False

        req_headers = headers or session.headers

        for attempt in range(3):
            if self.controller.check_pause_and_stop():
                return False
            try:
                r = session.get(url, headers=req_headers, timeout=(10, 30))
                if r.status_code == 200 and len(r.content) > 0:
                    with open(dest_path, "wb") as f:
                        f.write(r.content)
                    self.record_bytes(len(r.content))
                    return True
                time.sleep(1 * (attempt + 1))
            except Exception:
                time.sleep(1 * (attempt + 1))

        return False

    def download_chapter(
        self,
        task: QueueTask,
        chapter: Dict[str, Any],
        workers: int = DEFAULT_WORKERS,
        progress_cb: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, int]:
        """
        Baixa um capítulo de qualquer provedor registrado e empacota em CBZ.
        Retorna (sucesso, bytes_baixados_no_capítulo).
        """
        provider = ProviderRegistry.get_provider(task.provider)
        chap_num = chapter.get("chapter") or chapter.get("attributes", {}).get("chapter") or "0"
        group_name = provider.get_chapter_group(chapter, self.session)
        safe_title = clean_filename(task.title)
        safe_group = clean_filename(group_name)
        safe_chap_num = clean_filename(f"Capítulo {chap_num}")

        # Pasta principal da obra: download/<Título_do_Manga>/
        try:
            manga_folder = safe_path_join(task.outdir, safe_title)
            os.makedirs(manga_folder, exist_ok=True)
            final_cbz_filename = f"{safe_title} - {safe_chap_num} [{safe_group}].cbz"
            final_cbz_path = safe_path_join(manga_folder, final_cbz_filename)
            chap_folder = safe_path_join(manga_folder, f"{safe_chap_num} [{safe_group}]")
        except ValueError as e:
            task.error_message = f"Caminho de saída inseguro ou inválido: {e}"
            logger.error(task.error_message)
            return False, 0

        # Se já existe o CBZ completo, pula imediatamente (Smart Resume)
        if task.cbz and os.path.exists(final_cbz_path) and os.path.getsize(final_cbz_path) > 1024:
            if progress_cb:
                progress_cb(1, 1)
            return True, os.path.getsize(final_cbz_path)

        if self.controller.check_pause_and_stop() or self.controller.is_task_cancelled():
            return False, 0

        # Obter URLs das imagens através do provedor
        try:
            images = provider.get_chapter_pages(chapter, self.session, datasaver=task.datasaver)
        except Exception as e:
            err_msg = f"Cap. {chap_num}: Falha ao obter páginas do provedor ({e})"
            task.error_message = err_msg
            logger.error(err_msg)
            return False, 0

        if not images:
            task.error_message = f"Cap. {chap_num}: Nenhuma imagem encontrada no servidor."
            return False, 0

        os.makedirs(chap_folder, exist_ok=True)
        total_pages = len(images)
        completed_pages = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for idx, page_url in enumerate(images, 1):
                if self.controller.check_pause_and_stop() or self.controller.is_task_cancelled():
                    return False, 0
                clean_url = page_url.split("?")[0]
                ext = os.path.splitext(clean_url)[1] or ".jpg"
                if len(ext) > 5 or not ext.startswith("."):
                    ext = ".jpg"
                dest_file = safe_path_join(chap_folder, pad_filename(f"{idx}{ext}"))
                req_headers = provider.get_request_headers(page_url)
                future = executor.submit(self.download_page_file, page_url, dest_file, self.session, req_headers)
                futures[future] = idx

            for future in as_completed(futures):
                if self.controller.check_pause_and_stop() or self.controller.is_task_cancelled():
                    return False, 0
                completed_pages += 1
                if progress_cb:
                    progress_cb(completed_pages, total_pages)
                try:
                    if not future.result():
                        task.error_message = f"Cap. {chap_num}: Falha ao baixar imagens da página {futures[future]}."
                        return False, 0
                except Exception as e:
                    task.error_message = f"Cap. {chap_num}: Erro ao salvar página: {e}"
                    return False, 0

        # Calcular tamanho gerado na pasta
        total_bytes = 0
        for root, _, files in os.walk(chap_folder):
            for f in files:
                total_bytes += os.path.getsize(os.path.join(root, f))

        # Empacotar em CBZ
        if task.cbz and not self.controller.is_stopped() and not self.controller.is_task_cancelled():
            try:
                with zipfile.ZipFile(final_cbz_path, "w", zipfile.ZIP_DEFLATED) as myzip:
                    for root, _, files in os.walk(chap_folder):
                        for file in sorted(files):
                            path = os.path.join(root, file)
                            myzip.write(path, os.path.basename(path))
                shutil.rmtree(chap_folder, ignore_errors=True)
                total_bytes = os.path.getsize(final_cbz_path)
            except Exception as e:
                task.error_message = f"Cap. {chap_num}: Erro ao criar arquivo CBZ: {e}"
                return False, 0

        return True, total_bytes

    def download_chapter_mangadex(
        self,
        chapter: Dict[str, Any],
        title: str,
        outdir: str,
        datasaver: bool,
        cbz: bool,
        workers: int = DEFAULT_WORKERS,
        progress_cb: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, int]:
        """Wrapper retrocompatível para download_chapter."""
        dummy_task = QueueTask(id="compat", url="", provider="mangadex", title=title, datasaver=datasaver, cbz=cbz, outdir=outdir)
        return self.download_chapter(dummy_task, chapter, workers=workers, progress_cb=progress_cb)

    def download_chapter_mangalivre(
        self,
        chapter: Dict[str, Any],
        title: str,
        outdir: str,
        cbz: bool,
        workers: int = DEFAULT_WORKERS,
        progress_cb: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, int]:
        """Wrapper retrocompatível para download_chapter."""
        dummy_task = QueueTask(id="compat", url="", provider="mangalivre", title=title, cbz=cbz, outdir=outdir)
        return self.download_chapter(dummy_task, chapter, workers=workers, progress_cb=progress_cb)

