"""
Testes automatizados de segurança e regressão para o núcleo (manga_core.py),
provedores e mitigação de vulnerabilidades (Path Traversal, Sanitização de Nomes,
Validação de URLs, persistência de estado e controle de execução).
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from manga_core import (
    ChapterMode,
    DownloadEngine,
    ExecutionController,
    QueueTask,
    StateManager,
    TaskStatus,
    calculate_task_estimates,
    clean_filename,
    pad_filename,
    parse_chapter_selection,
    safe_path_join
)
from providers import UniversalPlaywrightProvider


class TestSecurityAndCore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = os.path.realpath(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. Testes de Sanitização de Filenames e Segurança do Filesystem
    # ------------------------------------------------------------------
    def test_clean_filename_forbidden_chars(self):
        """Verifica se caracteres proibidos são substituídos."""
        raw = 'Manga: Title / Chapter * 1 ? <Special> | "Quote"'
        cleaned = clean_filename(raw)
        for char in '/\\:*?"<>|':
            self.assertNotIn(char, cleaned, f"Caractere proibido '{char}' encontrado em '{cleaned}'")

    def test_clean_filename_control_characters(self):
        """Verifica se caracteres de controle e nulos são removidos."""
        raw = "Title\x00With\x1fControl\x7fChars"
        cleaned = clean_filename(raw)
        self.assertEqual(cleaned, "TitleWithControlChars")

    def test_clean_filename_windows_reserved_names(self):
        """Garante que palavras reservadas do Windows sejam prefixadas."""
        reserved_list = ["CON", "prn", "AUX", "NUL", "com1", "LPT9"]
        for res in reserved_list:
            cleaned = clean_filename(res)
            self.assertTrue(cleaned.startswith("_"), f"'{res}' não foi prefixado: {cleaned}")

        # Com extensão
        cleaned_ext = clean_filename("aux.cbz")
        self.assertTrue(cleaned_ext.startswith("_"), f"'aux.cbz' não foi prefixado: {cleaned_ext}")

    def test_clean_filename_dots_spaces_and_fallbacks(self):
        """Testa remoção de pontos/espaços periféricos e retorno de fallback."""
        self.assertEqual(clean_filename("..."), "Sem Titulo")
        self.assertEqual(clean_filename("   "), "Sem Titulo")
        self.assertEqual(clean_filename(None), "Sem Titulo")
        self.assertEqual(clean_filename("  Normal Title. . "), "Normal Title")

    def test_clean_filename_length_truncation(self):
        """Verifica se nomes excessivamente longos são truncados mantendo extensão."""
        long_title = "A" * 200 + ".cbz"
        cleaned = clean_filename(long_title, max_length=50)
        self.assertLessEqual(len(cleaned), 50)
        self.assertTrue(cleaned.endswith(".cbz"))

    # ------------------------------------------------------------------
    # 2. Testes de Safe Path Join e Prevenção de Path Traversal
    # ------------------------------------------------------------------
    def test_safe_path_join_valid(self):
        """Verifica criação de caminhos normais dentro do diretório base."""
        res = safe_path_join(self.base_dir, "manga_name", "chapter_1")
        self.assertTrue(res.startswith(self.base_dir))
        self.assertEqual(res, os.path.join(self.base_dir, "manga_name", "chapter_1"))

    def test_safe_path_join_traversal_parent_dir(self):
        """Garante que tentativas de subida de diretório ('..') sejam neutralizadas."""
        res = safe_path_join(self.base_dir, "..", "..", "etc", "passwd")
        self.assertTrue(res.startswith(self.base_dir))
        self.assertNotIn("..", res)

    # ------------------------------------------------------------------
    # 3. Testes de Segurança de Download e Validação de Esquemas de URL
    # ------------------------------------------------------------------
    def test_download_page_file_rejects_file_scheme(self):
        """Verifica se URLs do tipo 'file://' são categoricamente rejeitadas."""
        controller = ExecutionController()
        engine = DownloadEngine(controller=controller)
        mock_session = MagicMock()

        dest_file = os.path.join(self.base_dir, "page.jpg")
        result = engine.download_page_file("file:///etc/passwd", dest_file, mock_session)
        self.assertFalse(result, "download_page_file não deve aceitar 'file://'")
        self.assertFalse(os.path.exists(dest_file))

    def test_download_page_file_rejects_arbitrary_schemes(self):
        """Verifica se esquemas perigosos (data:, gopher:, javascript:) são rejeitados."""
        controller = ExecutionController()
        engine = DownloadEngine(controller=controller)
        mock_session = MagicMock()

        dest_file = os.path.join(self.base_dir, "page2.jpg")
        for bad_url in ["data:text/plain;base64,AAAA", "gopher://evil.com", "javascript:alert(1)"]:
            result = engine.download_page_file(bad_url, dest_file, mock_session)
            self.assertFalse(result, f"Deveria ter rejeitado esquema em {bad_url}")

    def test_universal_provider_can_handle_url_validation(self):
        """Verifica se o UniversalPlaywrightProvider valida esquemas HTTP/HTTPS."""
        prov = UniversalPlaywrightProvider()
        self.assertTrue(prov.can_handle("https://example.com/manga/1"))
        self.assertTrue(prov.can_handle("http://example.com/manga/1"))
        self.assertFalse(prov.can_handle("file:///C:/Windows/system32"))
        self.assertFalse(prov.can_handle("ftp://ftp.example.com"))
        self.assertFalse(prov.can_handle("not-a-valid-url"))

    # ------------------------------------------------------------------
    # 4. Testes de Núcleo: Seleção de Capítulos, Estimativas e Estado
    # ------------------------------------------------------------------
    def test_parse_chapter_selection_modes(self):
        """Valida modos de seleção de capítulos."""
        sample_chaps = [
            {"id": "1", "chapter": "1", "title": "Capítulo 1"},
            {"id": "2", "chapter": "2", "title": "Capítulo 2"},
            {"id": "3", "chapter": "3", "title": "Capítulo 3"},
            {"id": "4", "chapter": "4.5", "title": "Capítulo 4.5"},
            {"id": "5", "chapter": "5", "title": "Capítulo 5"},
        ]

        # ALL
        sel_all = parse_chapter_selection(sample_chaps, ChapterMode.ALL)
        self.assertEqual(len(sel_all), 5)

        # SINGLE
        sel_single = parse_chapter_selection(sample_chaps, ChapterMode.SINGLE, "3")
        self.assertEqual(len(sel_single), 1)
        self.assertEqual(sel_single[0]["id"], "3")

        # RANGE
        sel_range = parse_chapter_selection(sample_chaps, ChapterMode.RANGE, "2-4")
        self.assertEqual([c["id"] for c in sel_range], ["2", "3"])

        # LATEST
        sel_latest = parse_chapter_selection(sample_chaps, ChapterMode.LATEST)
        self.assertEqual(len(sel_latest), 1)
        self.assertEqual(sel_latest[0]["id"], "5")

        # CUSTOM
        sel_custom = parse_chapter_selection(sample_chaps, ChapterMode.CUSTOM, "1, 4.5, 5")
        self.assertEqual([c["id"] for c in sel_custom], ["1", "4", "5"])

    def test_state_manager_atomic_save_and_load(self):
        """Valida que o StateManager salva e recupera tarefas atomicamente."""
        state_file = os.path.join(self.base_dir, "test_queue_state.json")
        task1 = QueueTask(id="task-1", url="https://mangadex.org/title/123", title="Manga 1")
        task2 = QueueTask(id="task-2", url="https://mangadex.org/title/456", title="Manga 2", status=TaskStatus.READY)

        StateManager.save_queue([task1, task2], filepath=state_file)
        self.assertTrue(os.path.isfile(state_file))

        loaded = StateManager.load_queue(filepath=state_file)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].id, "task-1")
        self.assertEqual(loaded[1].status, TaskStatus.READY)

    def test_execution_controller_lifecycle(self):
        """Testa pause, resume, stop e cancelamento de tarefa."""
        ctrl = ExecutionController()
        self.assertFalse(ctrl.is_paused())
        self.assertFalse(ctrl.is_stopped())

        ctrl.pause()
        self.assertTrue(ctrl.is_paused())

        ctrl.resume()
        self.assertFalse(ctrl.is_paused())

        ctrl.cancel_current_task()
        self.assertTrue(ctrl.is_task_cancelled())
        ctrl.reset_task_cancelled()
        self.assertFalse(ctrl.is_task_cancelled())

        ctrl.stop()
        self.assertTrue(ctrl.is_stopped())


if __name__ == "__main__":
    unittest.main()
