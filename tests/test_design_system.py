"""
Testes automatizados para validação do Design System oficial,
identidade visual MangaDex_Downloader_CJrTools, assets e tela Sobre.
"""

import sys
import unittest
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QLabel

# Assegurar uma instância única de QApplication para testes headless
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

import styles
import icons
from about_dialog import AboutDialog
import mangadex_gui


class TestDesignSystem(unittest.TestCase):

    def test_app_metadata(self):
        """Valida que o nome e metadados do software foram atualizados corretamente."""
        self.assertEqual(mangadex_gui.APP_NAME, "MangaHubRip_CJrTools")
        self.assertEqual(mangadex_gui.ORGANIZATION_NAME, "CJRDOOM")
        self.assertEqual(mangadex_gui.__version__, "2.0.0")

    def test_assets_exist(self):
        """Valida a existência dos assets oficiais (logo e ícones Phosphor)."""
        base_dir = Path(__file__).resolve().parent.parent
        logo_png = base_dir / "assets" / "logo.png"
        self.assertTrue(logo_png.is_file(), f"Logo não encontrada em {logo_png}")

        reg_icons = base_dir / "assets" / "icons" / "regular"
        fill_icons = base_dir / "assets" / "icons" / "fill"
        self.assertTrue(reg_icons.is_dir(), "Diretório de ícones regular ausente")
        self.assertTrue(fill_icons.is_dir(), "Diretório de ícones fill ausente")

        # Verificar ícones essenciais
        for ic in ["plus.svg", "play.svg", "pause.svg", "stop.svg", "broom.svg", "folder-open.svg", "info.svg"]:
            self.assertTrue((reg_icons / ic).is_file(), f"Ícone regular {ic} ausente")

    def test_icons_provider(self):
        """Valida a geração vetorial de ícones e pixmaps via icons.py."""
        pix = icons.get_pixmap("plus", color="#FFAC2B", size=24)
        self.assertFalse(pix.isNull(), "Falha ao renderizar QPixmap vetorial do ícone 'plus'")
        self.assertEqual(pix.width(), 24)
        self.assertEqual(pix.height(), 24)

        ic = icons.get_icon("play", color="#F0F0F0", size=20)
        self.assertFalse(ic.isNull(), "Falha ao criar QIcon do ícone 'play'")

    def test_design_tokens(self):
        """Valida se todos os tokens de cores do Design System correspondem exatamente às especificações."""
        self.assertEqual(styles.COLOR_BACKGROUND, "#2E2D2D")
        self.assertEqual(styles.COLOR_SURFACE, "#363535")
        self.assertEqual(styles.COLOR_SURFACE_ELEVATED, "#3D3C3C")
        self.assertEqual(styles.COLOR_SURFACE_ACTIVE, "#454444")
        self.assertEqual(styles.COLOR_SURFACE_DISABLED, "#303030")
        self.assertEqual(styles.COLOR_ACCENT, "#FFAC2B")
        self.assertEqual(styles.COLOR_BORDER_STRONG, "#9E9E9E")
        self.assertEqual(styles.COLOR_BORDER_SUBTLE, "#4A4949")
        self.assertEqual(styles.COLOR_TEXT_PRIMARY, "#F0F0F0")
        self.assertEqual(styles.COLOR_TEXT_SECONDARY, "#BDBDBD")
        self.assertEqual(styles.COLOR_TEXT_DISABLED, "#666666")

    def test_about_dialog_content(self):
        """Valida a presença exata de todos os textos requeridos e do card de contraste da logo."""
        dlg = AboutDialog()
        labels = dlg.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels if lbl.text()]

        # Validação dos textos requeridos
        self.assertTrue(any("MangaHubRip_CJrTools" in t for t in texts), "Título ausente na tela Sobre")
        self.assertTrue(any("Version 2.0.0" in t for t in texts), "Versão 2.0.0 ausente na tela Sobre")
        self.assertTrue(any("Designed and developed by" in t for t in texts), "Crédito 'Designed and developed by' ausente")
        self.assertTrue(any("CJRDOOM" in t for t in texts), "Crédito 'CJRDOOM' ausente")
        self.assertTrue(any("© 2026 Carlos Junior" in t for t in texts), "Copyright ausente")

        # Validação do card de logo
        logo_label = [lbl for lbl in labels if lbl.pixmap() is not None]
        self.assertTrue(len(logo_label) >= 1, "Logo não renderizada na tela Sobre")

    def test_main_window_instantiation(self):
        """Valida que a janela principal instancia com o tema oficial e widgets corretos."""
        win = mangadex_gui.MainWindow()
        self.assertIn("MangaHubRip_CJrTools", win.windowTitle())
        self.assertIsNotNone(win.table)
        self.assertIsNotNone(win.btn_add_urls)
        self.assertIsNotNone(win.btn_start)
        self.assertIsNotNone(win.btn_header_about)


if __name__ == "__main__":
    unittest.main()
