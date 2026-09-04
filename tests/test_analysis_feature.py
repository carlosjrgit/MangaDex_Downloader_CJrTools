"""
Testes unitários e de regressão para a funcionalidade de Análise Prévia de Links,
detecção de idiomas disponíveis, alternância de idioma e tabela de fila de 9 colunas.
"""

import sys
import unittest
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from manga_core import (
    TaskStatus,
    get_language_display_name,
)
from providers import MangaDexProvider
import mangadex_gui


class TestAnalysisFeature(unittest.TestCase):

    def test_language_display_name(self):
        """Valida a resolução de códigos ISO de idiomas para nomes amigáveis em português."""
        self.assertEqual(get_language_display_name("pt-br"), "Português (Brasil) [pt-br]")
        self.assertEqual(get_language_display_name("pt"), "Português [pt]")
        self.assertEqual(get_language_display_name("en"), "English (Inglês) [en]")
        self.assertEqual(get_language_display_name("es-la"), "Español (Latinoamérica) [es-la]")
        self.assertEqual(get_language_display_name("ja"), "日本語 (Japonês) [ja]")
        self.assertEqual(get_language_display_name("xyz"), "Idioma [xyz]")

    def test_mangadex_provider_get_chapters_for_language(self):
        """Valida que o MangaDexProvider implementa get_chapters_for_language corretamente."""
        provider = MangaDexProvider()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "ok",
            "data": [
                {
                    "id": "chap_1",
                    "attributes": {
                        "chapter": "1",
                        "title": "Primeiro Capítulo",
                        "pages": 20,
                        "translatedLanguage": "pt-br"
                    }
                }
            ],
            "total": 1
        }
        mock_session.get.return_value = mock_resp

        chaps = provider.get_chapters_for_language(
            "https://mangadex.org/title/801513ba-a712-498b-87ab-cf690a7a1f60/bocchi-the-rock",
            "pt-br",
            session=mock_session
        )
        self.assertEqual(len(chaps), 1)
        self.assertEqual(chaps[0]["id"], "chap_1")
        self.assertEqual(chaps[0]["chapter"], "1")
        self.assertEqual(chaps[0]["attributes"]["pages"], 20)

    def test_main_window_table_nine_columns(self):
        """Valida que a tabela de tarefas possui 9 colunas incluindo Idioma."""
        win = mangadex_gui.MainWindow()
        self.assertEqual(win.table.columnCount(), 9)
        headers = [win.table.horizontalHeaderItem(i).text() for i in range(9)]
        expected = ["#", "Obra / Título", "Provedor", "Idioma", "Capítulos", "Tamanho Est.", "Tempo Est.", "Progresso", "Status"]
        self.assertEqual(headers, expected)

    def test_main_window_has_analysis_widgets(self):
        """Valida presença dos widgets de análise na interface."""
        win = mangadex_gui.MainWindow()
        self.assertIsNotNone(win.btn_analyze_link)
        self.assertEqual(win.btn_analyze_link.text(), "🔍 Analisar Link")
        self.assertIsNotNone(win.card_analysis)
        self.assertIsNotNone(win.combo_lang)
        self.assertIsNotNone(win.btn_add_analyzed)
        self.assertIsNotNone(win.lbl_preview_calc)
        self.assertIsNotNone(win.btn_batch_add)
        self.assertIsNotNone(win.btn_add_urls)

    def test_add_analyzed_to_queue(self):
        """Valida a adição de obra analisada com metadados completos e status READY."""
        win = mangadex_gui.MainWindow()
        win.tasks.clear()

        # Simular dados de análise prévia
        win.current_analysis = {
            "url": "https://mangadex.org/title/801513ba-a712-498b-87ab-cf690a7a1f60/bocchi-the-rock",
            "provider": "mangadex",
            "provider_display": "MangaDex",
            "title": "Bocchi the Rock!",
            "cover_url": "",
            "cover_bytes": None,
            "available_langs": ["pt-br", "en"],
            "current_lang": "pt-br",
            "chapters": [
                {"id": "c1", "chapter": "1", "pages_count": 25},
                {"id": "c2", "chapter": "2", "pages_count": 25},
            ]
        }
        win.combo_lang.clear()
        win.combo_lang.addItem("Português (Brasil)", "pt-br")
        win.combo_lang.addItem("English", "en")
        win.combo_lang.setCurrentIndex(0)
        win.combo_mode.setCurrentIndex(0)  # ALL

        win.add_analyzed_to_queue()

        self.assertEqual(len(win.tasks), 1)
        task = win.tasks[0]
        self.assertEqual(task.title, "Bocchi the Rock!")
        self.assertEqual(task.lang_code, "pt-br")
        self.assertEqual(len(task.selected_chapters), 2)
        self.assertEqual(task.status, TaskStatus.READY)

        # Validação na tabela
        self.assertEqual(win.table.rowCount(), 1)
        self.assertEqual(win.table.item(0, 1).text(), "Bocchi the Rock!")
        self.assertEqual(win.table.item(0, 2).text(), "MangaDex")
        self.assertEqual(win.table.item(0, 3).text(), "PT-BR")
        self.assertEqual(win.table.item(0, 4).text(), "2 caps")
        self.assertEqual(win.table.item(0, 8).text(), TaskStatus.READY.value)

    def test_chapter_mode_hints_and_range_parsing(self):
        """Valida que o label de exemplo orienta corretamente o usuário e suporta 1-10, 1,10 e 1, 6, 10."""
        from manga_core import ChapterMode, parse_chapter_selection
        win = mangadex_gui.MainWindow()
        self.assertIsNotNone(win.lbl_mode_example)

        # Alternar para modo RANGE
        range_idx = win.combo_mode.findData(ChapterMode.RANGE.value)
        win.combo_mode.setCurrentIndex(range_idx)
        self.assertIn("1-10 ou 1,10", win.lbl_mode_example.text())

        # Testar parsing com hífen e vírgula
        all_chaps = [{"id": f"c_{i}", "chapter": str(i)} for i in range(1, 21)]
        res_hyphen = parse_chapter_selection(all_chaps, ChapterMode.RANGE, "1-5")
        self.assertEqual(len(res_hyphen), 5)
        res_comma = parse_chapter_selection(all_chaps, ChapterMode.RANGE, "1,5")
        self.assertEqual(len(res_comma), 5)

        # Testar modo CUSTOM com 1, 6, 10
        custom_idx = win.combo_mode.findData(ChapterMode.CUSTOM.value)
        win.combo_mode.setCurrentIndex(custom_idx)
        self.assertIn("1, 6, 10", win.lbl_mode_example.text())
        res_custom = parse_chapter_selection(all_chaps, ChapterMode.CUSTOM, "1, 6, 10")
        self.assertEqual(len(res_custom), 3)
        self.assertEqual([c["chapter"] for c in res_custom], ["1", "6", "10"])

    def test_table_cell_widget_cleanup(self):
        """Garante que a atualização da tabela remove widgets anteriores, evitando sobreposição no viewport."""
        from manga_core import QueueTask
        win = mangadex_gui.MainWindow()
        task_a = QueueTask(id="a", url="https://a", title="Obra A", status=TaskStatus.READY)
        task_b = QueueTask(id="b", url="https://b", title="Obra B", status=TaskStatus.COMPLETED)

        win.tasks = [task_a]
        win._refresh_table()
        self.assertEqual(win.table.rowCount(), 1)

        win.tasks = [task_a, task_b]
        win._refresh_table()
        self.assertEqual(win.table.rowCount(), 2)

        # Apenas a coluna 7 deve conter QProgressBar
        from PyQt5.QtWidgets import QProgressBar
        progress_bars = [w for w in win.table.findChildren(QProgressBar) if w.parent() is not None]
        self.assertEqual(len(progress_bars), 2)


if __name__ == "__main__":
    unittest.main()

