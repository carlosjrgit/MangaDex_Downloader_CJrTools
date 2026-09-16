#!/usr/bin/env python3
"""
test_explore_sources.py - Testes automatizados para a aba 'Explorar Fontes',
listagem de mangás por site, diálogo de seleção de capítulos e envio para a fila.
"""

import sys
import unittest
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

# Instância única de QApplication para testes PyQt5 headless
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from manga_core import ChapterMode, TaskStatus
from keiyoushi_catalog import catalog
from chapter_download_dialog import ChapterDownloadDialog
import mangadex_gui


class TestExploreSources(unittest.TestCase):
    """Testes de validação da aba Explorar Fontes e fluxo de download."""

    @classmethod
    def setUpClass(cls):
        catalog.load()

    def test_01_main_window_tabs(self):
        """Valida se a MainWindow possui as duas abas organizadas via QTabWidget."""
        win = mangadex_gui.MainWindow()
        self.assertIsNotNone(win.tabs)
        self.assertEqual(win.tabs.count(), 2)
        self.assertIn("Fila de Downloads", win.tabs.tabText(0))
        self.assertIn("Explorar Fontes", win.tabs.tabText(1))

        # Atributos preservados da Aba 1 (Fila)
        self.assertIsNotNone(win.table)
        self.assertIsNotNone(win.btn_start)
        self.assertIsNotNone(win.btn_add_urls)
        self.assertIsNotNone(win.btn_catalog)

        # Atributos da Aba 2 (Explorar Fontes)
        self.assertIsNotNone(win.table_sources)
        self.assertIsNotNone(win.table_mangas)
        self.assertIsNotNone(win.txt_source_filter)
        self.assertIsNotNone(win.combo_source_lang)
        self.assertIsNotNone(win.btn_refresh_catalog)
        self.assertIsNotNone(win.btn_prev_page)
        self.assertIsNotNone(win.btn_next_page)

    def test_02_sources_table_population_and_filter(self):
        """Valida que a tabela de fontes foi populada com as fontes do catálogo e o filtro funciona."""
        win = mangadex_gui.MainWindow()
        self.assertGreater(win.table_sources.rowCount(), 0, "A tabela de fontes deve estar populada.")

        # Testar filtro por texto
        win.txt_source_filter.setText("flower")
        win._filter_sources()
        count_flower = win.table_sources.rowCount()
        self.assertGreater(count_flower, 0)
        self.assertLess(count_flower, len(win.all_explore_sources))

        # Testar filtro por idioma pt-br
        idx_pt = win.combo_source_lang.findData("pt-br")
        self.assertGreaterEqual(idx_pt, 0)
        win.combo_source_lang.setCurrentIndex(idx_pt)
        win.txt_source_filter.clear()
        win._filter_sources()
        count_pt = win.table_sources.rowCount()
        self.assertGreater(count_pt, 10, "Deve haver mais de 10 fontes em pt-br.")
        self.assertLess(count_pt, 500, "Fontes em pt-br devem ser um subconjunto das 2200+.")

    def test_03_chapter_download_dialog_all_mode(self):
        """Valida o diálogo de seleção de capítulos no modo padrão (ALL)."""
        dlg = ChapterDownloadDialog(
            manga_title="Solo Leveling",
            manga_url="https://exemplo.com/manga/solo-leveling",
            source_name="Flower Mangas"
        )
        self.assertTrue(dlg.rb_all.isChecked())
        self.assertFalse(dlg.txt_range.isEnabled())
        self.assertFalse(dlg.txt_custom.isEnabled())

        # Simular confirmação
        dlg._on_confirm()
        self.assertIsNotNone(dlg.result_config)
        self.assertEqual(dlg.result_config["manga_title"], "Solo Leveling")
        self.assertEqual(dlg.result_config["chapter_mode"], ChapterMode.ALL)
        self.assertEqual(dlg.result_config["chapter_mode_value"], "")
        self.assertTrue(dlg.result_config["cbz"])

    def test_04_chapter_download_dialog_range_mode(self):
        """Valida o diálogo no modo intervalo (RANGE)."""
        dlg = ChapterDownloadDialog(
            manga_title="One Piece",
            manga_url="https://exemplo.com/manga/one-piece"
        )
        dlg.rb_range.setChecked(True)
        dlg.txt_range.setText("1-50")
        dlg.cb_cbz.setChecked(False)

        dlg._on_confirm()
        self.assertIsNotNone(dlg.result_config)
        self.assertEqual(dlg.result_config["chapter_mode"], ChapterMode.RANGE)
        self.assertEqual(dlg.result_config["chapter_mode_value"], "1-50")
        self.assertFalse(dlg.result_config["cbz"])

    def test_05_chapter_download_dialog_custom_mode(self):
        """Valida o diálogo no modo personalizado (CUSTOM)."""
        dlg = ChapterDownloadDialog(
            manga_title="Berserk",
            manga_url="https://exemplo.com/manga/berserk"
        )
        dlg.rb_custom.setChecked(True)
        dlg.txt_custom.setText("1, 5, 10-20, oneshot")

        dlg._on_confirm()
        self.assertIsNotNone(dlg.result_config)
        self.assertEqual(dlg.result_config["chapter_mode"], ChapterMode.CUSTOM)
        self.assertEqual(dlg.result_config["chapter_mode_value"], "1, 5, 10-20, oneshot")

    def test_06_enqueue_manga_from_catalog(self):
        """Valida que adicionar um mangá do catálogo enfileira a obra e exibe a mensagem de confirmação requerida."""
        win = mangadex_gui.MainWindow()
        initial_count = len(win.tasks)

        manga_item = {
            "title": "Chainsaw Man",
            "url": "https://flowermangas.net/manga/chainsaw-man/",
            "cover_url": "https://flowermangas.net/wp-content/uploads/cover.jpg",
            "chapter_info": "150 caps",
            "source_name": "Flower Mangas",
            "lang": "pt-br"
        }

        fake_cfg = {
            "manga_title": "Chainsaw Man",
            "manga_url": "https://flowermangas.net/manga/chainsaw-man/",
            "chapter_mode": ChapterMode.ALL,
            "chapter_mode_value": "",
            "cbz": True,
            "outdir": "download"
        }

        def fake_exec(dlg_self):
            dlg_self.result_config = fake_cfg
            return QDialog.Accepted

        with patch.object(ChapterDownloadDialog, "exec_", fake_exec):
            with patch.object(QMessageBox, "information") as mock_info:
                win._on_download_manga_from_catalog(manga_item)

                # Verificar se tarefa foi adicionada à fila
                self.assertEqual(len(win.tasks), initial_count + 1)
                new_task = win.tasks[-1]
                self.assertEqual(new_task.title, "Chainsaw Man")
                self.assertEqual(new_task.chapter_mode, ChapterMode.ALL)
                self.assertEqual(new_task.status, TaskStatus.PENDING)

                # Verificar se a mensagem de confirmação exata solicitada pelo usuário foi disparada
                mock_info.assert_called_once()
                args, kwargs = mock_info.call_args
                self.assertEqual(args[1], "Sucesso")
                self.assertEqual(args[2], "Mangás foram pra fila!")

    def test_07_catalog_table_rendering(self):
        """Valida que o resultado do catálogo monta as 5 colunas com botões de download e badge."""
        win = mangadex_gui.MainWindow()
        items = [
            {
                "title": "Manga Teste 1",
                "url": "https://site.com/manga/1",
                "cover_url": "https://site.com/cover1.jpg",
                "chapter_info": "Cap. 20",
                "source_name": "Site Teste",
                "lang": "pt-br"
            },
            {
                "title": "Manga Teste 2",
                "url": "https://site.com/manga/2",
                "cover_url": "",
                "chapter_info": "10 caps",
                "source_name": "Site Teste",
                "lang": "pt-br"
            }
        ]
        win._on_catalog_loaded(items, page=1)

        self.assertEqual(win.table_mangas.rowCount(), 2)
        self.assertEqual(win.table_mangas.columnCount(), 5)

        # Coluna 0: Miniatura de Capa (HoverableCoverLabel)
        lbl_cover = win.table_mangas.cellWidget(0, 0)
        self.assertIsNotNone(lbl_cover)
        self.assertIsInstance(lbl_cover, mangadex_gui.HoverableCoverLabel)
        self.assertEqual(lbl_cover.width(), 65)
        self.assertEqual(lbl_cover.height(), 90)
        self.assertIsNotNone(win.cover_popup)

    def test_08_universal_title_cleaning(self):
        """Valida a limpeza universal de títulos heurística eliminando ruídos de interface (botões, badges)."""
        from bs4 import BeautifulSoup
        from source_catalog_fetcher import _clean_card_title

        # Cenário 1: Comikey com botão "Visit Series", badges SIMUL e capítulos dentro do texto do link
        html_comikey = '''
        <a href="/comics/o-unico-destino-dos-viloes-e-a-morte/">
            <img src="/cover.jpg" alt="Cover for O Único Destino dos Vilões é a Morte">
            <span>SIMUL</span>
            <span>Visit Series</span>
            <span>160 Chapters</span>
        </a>
        '''
        soup = BeautifulSoup(html_comikey, "html.parser")
        a_tag = soup.find("a")
        img_tag = soup.find("img")
        raw_text = a_tag.get_text(separator=" ", strip=True)
        cleaned = _clean_card_title(raw_text, img_tag=img_tag, link_href=a_tag.get("href"))
        self.assertEqual(cleaned, "O Único Destino dos Vilões é a Morte")

        # Cenário 2: Sufixo "- Webtoon" e prefixo "Capa de "
        html_capa = '<a href="/manga/solo-leveling"><img src="/cover.jpg" alt="Capa de Solo Leveling - Webtoon"></a>'
        soup2 = BeautifulSoup(html_capa, "html.parser")
        cleaned2 = _clean_card_title("", img_tag=soup2.find("img"), link_href="/manga/solo-leveling")
        self.assertEqual(cleaned2, "Solo Leveling")

        # Cenário 3: Fallback por slug quando o texto do link é apenas ruído "Read Now" e img sem alt (remove sufixo -manhwa)
        html_slug = '<a href="/comics/shadow-queen-manhwa/">Read Now</a>'
        soup3 = BeautifulSoup(html_slug, "html.parser")
        cleaned3 = _clean_card_title("Read Now", img_tag=None, link_href=soup3.find("a").get("href"))
        self.assertEqual(cleaned3, "Shadow Queen")

    def test_09_cover_preview_popup_interaction(self):
        """Valida que o CoverPreviewPopup inicializa com estilização correta e exibe/oculta capa e título."""
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QPixmap

        win = mangadex_gui.MainWindow()
        popup = win.cover_popup
        self.assertIsNotNone(popup)
        self.assertTrue(popup.isHidden())

        # Testar exibição de preview com QPixmap dummy
        pix = QPixmap(100, 150)
        pix.fill()
        popup.show_preview(QPoint(100, 100), pix, "Obra Teste Preview", "Comikey")
        self.assertFalse(popup.isHidden())
        self.assertEqual(popup.lbl_title.text(), "Obra Teste Preview")
        self.assertIn("COMIKEY", popup.lbl_source.text())

        # Testar ocultação
        popup.hide_preview()
        self.assertTrue(popup.isHidden())


if __name__ == "__main__":
    unittest.main()

