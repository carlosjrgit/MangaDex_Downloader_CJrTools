#!/usr/bin/env python3
"""
test_keiyoushi_integration.py - Testes de integração do catálogo Keiyoushi (index.pb),
verificação de prioridades no ProviderRegistry e preservação do MangaDex/MangaLivre.
"""

import unittest
from keiyoushi_catalog import catalog
from providers import (
    ProviderRegistry,
    MangaDexProvider,
    MangaLivreProvider,
    KeiyoushiSourceProvider,
    UniversalPlaywrightProvider
)


class TestKeiyoushiIntegration(unittest.TestCase):
    """Testes de validação da camada de catálogo e provedores."""

    def test_01_catalog_load(self):
        """Verifica se o index.pb é lido e indexado com sucesso."""
        loaded = catalog.load()
        self.assertTrue(loaded, "O catálogo Keiyoushi deve carregar com sucesso.")
        self.assertGreater(len(catalog.sources), 1000, "Deve haver mais de 1000 fontes indexadas.")
        self.assertGreater(len(catalog.get_supported_domains()), 500, "Deve haver centenas de domínios únicos.")

    def test_02_catalog_domain_lookup(self):
        """Verifica se URLs de fontes conhecidas são reconhecidas no catálogo."""
        pt_source = catalog.find_source_by_url("https://flowermangas.net/manga/exemplo")
        self.assertIsNotNone(pt_source)
        self.assertEqual(pt_source.lang.lower(), "pt-br")

        argos = catalog.find_source_by_url("https://aniargos.com/obra/exemplo")
        self.assertIsNotNone(argos)
        self.assertIn("argos", argos.name.lower())

        mangafire = catalog.find_source_by_url("https://mangafire.to/manga/exemplo")
        self.assertIsNotNone(mangafire)

        # Domínio não existente
        unknown = catalog.find_source_by_url("https://meu-site-inexistente-123.org/manga")
        self.assertIsNone(unknown)

    def test_03_mangadex_preservation(self):
        """Garante que URLs do MangaDex continuam sendo tratadas pelo MangaDexProvider."""
        url = "https://mangadex.org/title/a9667631-4722-45e0-96f9-715a4ec7649f"
        prov = ProviderRegistry.get_provider_for_url(url)
        self.assertIsInstance(prov, MangaDexProvider, "URLs do MangaDex devem ser atribuídas ao MangaDexProvider.")
        self.assertEqual(prov.name, "mangadex")

    def test_04_mangalivre_preservation(self):
        """Garante que URLs do MangaLivre continuam sendo tratadas pelo MangaLivreProvider."""
        url = "https://mangalivre.net/manga/solo-leveling/7702"
        prov = ProviderRegistry.get_provider_for_url(url)
        self.assertIsInstance(prov, MangaLivreProvider, "URLs do MangaLivre devem ser atribuídas ao MangaLivreProvider.")
        self.assertEqual(prov.name, "mangalivre")

    def test_05_keiyoushi_routing(self):
        """Garante que URLs de sites catalogados no index.pb são atribuídas ao KeiyoushiSourceProvider."""
        test_urls = [
            "https://flowermangas.net/manga/o-retorno-do-heroi/",
            "https://aniargos.com/obra/123",
            "https://mangafire.to/manga/one-piece.123",
            "https://br.comikey.com/comics/123",
            "https://leemiau.com/obra/123",
            "https://loverstoon.com/manga/exemplo"
        ]
        for u in test_urls:
            prov = ProviderRegistry.get_provider_for_url(u)
            self.assertIsInstance(prov, KeiyoushiSourceProvider, f"A URL {u} deveria ser tratada pelo KeiyoushiSourceProvider")
            self.assertEqual(prov.name, "keiyoushi")

    def test_06_universal_fallback(self):
        """Garante que URLs de sites desconhecidos caem no fallback universal."""
        url = "https://site-aleatorio-totalmente-desconhecido.xyz/manga/1"
        prov = ProviderRegistry.get_provider_for_url(url)
        self.assertIsInstance(prov, UniversalPlaywrightProvider)
        self.assertEqual(prov.name, "universal")

    def test_07_request_headers_referer(self):
        """Verifica se os headers de requisição montam o Referer correto para evitar erro 403."""
        prov = ProviderRegistry.get_provider("keiyoushi")
        headers = prov.get_request_headers("https://flowermangas.net/wp-content/uploads/page1.jpg")
        self.assertIn("Referer", headers)
        self.assertEqual(headers["Referer"], "https://flowermangas.net")
        self.assertIn("User-Agent", headers)

    def test_08_request_headers_with_chapter_url(self):
        """Verifica se chapter_url tem precedência para contornar proteções de CDN externas (MangaFire, etc)."""
        prov = ProviderRegistry.get_provider("keiyoushi")
        chap_url = "https://mangafire.to/title/0rm7-monster-tale/chapter/7556224"
        cdn_img_url = "https://nw8.mfcdn1.xyz/mf/abc/h/p.jpg"
        headers = prov.get_request_headers(cdn_img_url, chapter_url=chap_url)
        self.assertEqual(headers["Referer"], chap_url)
        self.assertIn("User-Agent", headers)

    def test_09_close_session_and_profile_dir(self):
        """Verifica se get_playwright_profile_dir e close_session funcionam corretamente."""
        from providers import get_playwright_profile_dir
        p_dir = get_playwright_profile_dir()
        self.assertTrue(len(p_dir) > 0)
        self.assertIn("MangaDex_CJrTools_browser", p_dir)

        prov = ProviderRegistry.get_provider("keiyoushi")
        self.assertTrue(hasattr(prov, "close_session"))
        self.assertTrue(hasattr(prov, "_ensure_active_page"))
        # Chamada idempotente não deve lançar exceção
        prov.close_session()
        prov.close_session()

    def test_10_mangafire_chapter_pages_api_interception(self):
        """Verifica a lógica de interceptação da API /api/chapters/ para extração das páginas."""
        from unittest.mock import MagicMock, patch
        prov = ProviderRegistry.get_provider("keiyoushi")
        chap_url = "https://mangafire.to/title/0rm7-monster-tale/chapter/7556224"

        # Simula resposta interceptada da API do MangaFire
        fake_api_response = {
            "data": {
                "pages": [
                    {"url": "https://nw8.mfcdn1.xyz/mf/1.jpg", "width": 1000},
                    {"url": "https://nw8.mfcdn1.xyz/mf/2.jpg", "width": 1000},
                    {"url": "https://nw8.mfcdn1.xyz/mf/3.jpg", "width": 1000}
                ]
            }
        }

        mock_res = MagicMock()
        mock_res.url = "https://mangafire.to/api/chapters/7556224?vrf=testtoken"
        mock_res.status = 200
        mock_res.json.return_value = fake_api_response

        # Testa com mock do Playwright
        with patch.object(prov, "_launch_browser_context") as mock_launch:
            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_launch.return_value = (mock_ctx, None)
            mock_ctx.new_page.return_value = mock_page

            def fake_on(event, handler):
                if event == "response":
                    handler(mock_res)

            mock_page.on.side_effect = fake_on

            pages = prov._get_chapter_pages_playwright(chap_url)
            self.assertEqual(len(pages), 3)
            self.assertEqual(pages[0], "https://nw8.mfcdn1.xyz/mf/1.jpg")
            self.assertEqual(pages[-1], "https://nw8.mfcdn1.xyz/mf/3.jpg")

    def test_11_mangafire_catalog_api_parsing(self):
        """Verifica o parsing do catálogo MangaFire a partir de interceptação da API /api/titles."""
        from unittest.mock import MagicMock, patch
        from source_catalog_fetcher import _fetch_mangafire_catalog, KeiyoushiSource

        source = KeiyoushiSource(
            id=7842137233968841729,
            name="MangaFire",
            lang="pt-BR",
            base_url="https://mangafire.to",
            pkg="eu.kanade.tachiyomi.extension.all.mangafire"
        )

        fake_titles_response = {
            "items": [
                {
                    "title": "Monster Tale",
                    "url": "/title/0rm7-monster-tale",
                    "poster": {"medium": "https://static.mfcdn.nl/cover.jpg"},
                    "latestChapter": 193
                }
            ]
        }

        mock_res = MagicMock()
        mock_res.url = "https://mangafire.to/api/titles?languages%5B%5D=pt-br&page=1&vrf=token"
        mock_res.status = 200
        mock_res.json.return_value = fake_titles_response

        with patch("playwright.sync_api.sync_playwright") as mock_pw_cls:
            mock_p = MagicMock()
            mock_pw_cls.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_ctx
            mock_ctx.new_page.return_value = mock_page

            def fake_on(event, handler):
                if event == "response":
                    handler(mock_res)

            mock_page.on.side_effect = fake_on

            items = _fetch_mangafire_catalog(source, page=1, timeout=10)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Monster Tale")
            self.assertEqual(items[0]["url"], "https://mangafire.to/title/0rm7-monster-tale")
            self.assertEqual(items[0]["cover_url"], "https://static.mfcdn.nl/cover.jpg")
            self.assertEqual(items[0]["chapter_info"], "Cap. 193")
            self.assertEqual(items[0]["source_name"], "MangaFire")
            self.assertEqual(items[0]["lang"], "pt-BR")


if __name__ == "__main__":
    unittest.main()
