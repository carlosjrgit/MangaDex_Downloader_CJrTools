#!/usr/bin/env python3
"""
providers.py - Camada de provedores de leitura de mangás.
Implementa a arquitetura em cascata:
1. Provedores Dedicados (MangaDex, MangaLivre)
2. Motor Genérico de CMS WordPress (Madara / WP-Manga)
3. Extrator Universal Heurístico (Playwright Stealth + Sniffer de Rede)
"""

import html
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import mangalivre

logger = logging.getLogger("providers")

# ----------------------------------------------------------------------
# Constantes & Regexes
# ----------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CHAPTER_NUM_REGEX = re.compile(
    r'(?:cap[ií]tulo|chapter|ch\.?|ep\.?)\s*([0-9]+(?:\.[0-9]+)?)',
    re.IGNORECASE
)

# ----------------------------------------------------------------------
# Interface Base (Contrato de Provedor)
# ----------------------------------------------------------------------
class BaseMangaProvider(ABC):
    """Interface abstrata para qualquer provedor ou motor de mangá."""

    name: str = "base"
    display_name: str = "Base"

    @abstractmethod
    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        """Verifica se este provedor sabe lidar com a URL fornecida."""
        raise NotImplementedError

    @abstractmethod
    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        """
        Retorna informações estruturadas da obra:
        {
            "title": str,
            "cover_url": str,
            "available_langs": List[str],
            "chapters": List[Dict[str, Any]] # {"id": str, "chapter": str, "title": str, "url": str, "group": str}
        }
        """
        raise NotImplementedError

    @abstractmethod
    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        """Retorna a lista ordenada de URLs das imagens das páginas."""
        raise NotImplementedError

    def get_chapter_group(self, chapter: Dict[str, Any], session: requests.Session) -> str:
        """Retorna o nome da scan/grupo associado ao capítulo."""
        return chapter.get("group") or self.display_name

    def get_request_headers(self, page_url: str) -> Dict[str, str]:
        """Headers adicionais (ex: Referer) para download das imagens."""
        parsed = urlparse(page_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return {
            "User-Agent": USER_AGENT,
            "Referer": origin
        }


# ----------------------------------------------------------------------
# 1. Provedor Dedicado: MangaDex
# ----------------------------------------------------------------------
class MangaDexProvider(BaseMangaProvider):
    name = "mangadex"
    display_name = "MangaDex"

    def __init__(self):
        self.group_cache: Dict[str, str] = {}

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        lower = url.lower()
        return "mangadex.org" in lower or "api.mangadex.org" in lower

    def _find_id_in_url(self, url: str) -> Optional[str]:
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

    def _get_uuid(self, manga_id_or_url: str, session: requests.Session) -> str:
        extracted = self._find_id_in_url(manga_id_or_url) or manga_id_or_url
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', extracted, re.IGNORECASE):
            return extracted
        try:
            int_id = int(extracted)
            headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
            payload = json.dumps({"type": "manga", "ids": [int_id]})
            r = session.post("https://api.mangadex.org/legacy/mapping", headers=headers, data=payload, timeout=10)
            r.raise_for_status()
            return r.json()[0]["data"]["attributes"]["newId"]
        except Exception as e:
            raise ValueError(f"ID/URL inválido do MangaDex: '{manga_id_or_url}' ({e})")

    def _choose_title(self, attributes: Dict[str, Any], lang_code: str = "pt-br") -> str:
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
        return html.unescape(title) if title else "Título desconhecido"

    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        uuid = self._get_uuid(url, session)
        r = session.get(f"https://api.mangadex.org/manga/{uuid}", timeout=10)
        r.raise_for_status()
        attrs = r.json()["data"]["attributes"]

        title = self._choose_title(attrs, lang_code)
        available_langs = attrs.get("availableTranslatedLanguages", ["pt-br"])
        if lang_code not in available_langs and available_langs:
            lang_code = available_langs[0]
            title = self._choose_title(attrs, lang_code)

        # Buscar Capa
        cover_url = ""
        relationships = r.json()["data"].get("relationships", [])
        cover_art_id = next((rel["id"] for rel in relationships if rel.get("type") == "cover_art"), None)
        if cover_art_id:
            try:
                cov_resp = session.get(f"https://api.mangadex.org/cover/{cover_art_id}", timeout=5)
                if cov_resp.status_code == 200:
                    cov_file = cov_resp.json()["data"]["attributes"]["fileName"]
                    cover_url = f"https://uploads.mangadex.org/covers/{uuid}/{cov_file}.512.jpg"
            except Exception:
                pass

        # Buscar Capítulos
        ratings = "&".join([
            "contentRating[]=safe", "contentRating[]=suggestive",
            "contentRating[]=erotica", "contentRating[]=pornographic"
        ])
        params = {
            "translatedLanguage[]": lang_code,
            "order[volume]": "asc",
            "order[chapter]": "asc",
            "limit": 500
        }
        api_url = f"https://api.mangadex.org/manga/{uuid}/feed?{ratings}"
        raw_chapters = []
        offset = 0
        while True:
            p = dict(params)
            p["offset"] = offset
            res = session.get(api_url, params=p, timeout=10)
            res.raise_for_status()
            data = res.json()
            batch = data.get("data", [])
            raw_chapters.extend(batch)
            if len(batch) < 500:
                break
            offset += 500

        # Deduplicar capítulos com mesmo número mantendo mais recente
        dedup: Dict[str, Dict[str, Any]] = {}
        for ch in raw_chapters:
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

        sorted_raw = sorted(dedup.values(), key=sort_key)
        normalized_chapters = []
        for ch in sorted_raw:
            num = ch["attributes"]["chapter"] or "Oneshot"
            ch_title = ch["attributes"].get("title") or ""
            ch_id = ch["id"]
            normalized_chapters.append({
                "id": ch_id,
                "chapter": str(num),
                "title": ch_title,
                "url": f"https://mangadex.org/chapter/{ch_id}",
                "relationships": ch.get("relationships", []),
                "attributes": ch.get("attributes", {})
            })

        return {
            "title": title,
            "cover_url": cover_url,
            "available_langs": available_langs,
            "chapters": normalized_chapters
        }

    def get_chapter_group(self, chapter: Dict[str, Any], session: requests.Session) -> str:
        group_ids = [rel["id"] for rel in chapter.get("relationships", []) if rel.get("type") == "scanlation_group"]
        names = []
        for gid in group_ids:
            if gid not in self.group_cache:
                try:
                    r = session.get(f"https://api.mangadex.org/group/{gid}", timeout=10)
                    if r.status_code == 200:
                        self.group_cache[gid] = r.json()["data"]["attributes"]["name"]
                    else:
                        self.group_cache[gid] = f"Grupo-{gid[:6]}"
                except Exception:
                    self.group_cache[gid] = f"Grupo-{gid[:6]}"
            names.append(self.group_cache[gid])
        return " & ".join(names) if names else "Desconhecido"

    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        chap_id = chapter["id"]
        r = session.get(f"https://api.mangadex.org/at-home/server/{chap_id}", timeout=10)
        r.raise_for_status()
        data = r.json()
        baseurl = data["baseUrl"]
        chaphash = data["chapter"]["hash"]
        datamode = "dataSaver" if datasaver else "data"
        datamode2 = "data-saver" if datasaver else "data"
        page_filenames = data["chapter"].get(datamode, [])
        return [f"{baseurl}/{datamode2}/{chaphash}/{fname}" for fname in page_filenames]


# ----------------------------------------------------------------------
# 2. Provedor Dedicado: MangaLivre
# ----------------------------------------------------------------------
class MangaLivreProvider(BaseMangaProvider):
    name = "mangalivre"
    display_name = "MangaLivre"

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        return mangalivre.is_mangalivre_url(url)

    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        info = mangalivre.get_manga_info(url, session)
        return {
            "title": info["title"],
            "cover_url": info.get("cover", ""),
            "available_langs": ["pt-br"],
            "chapters": info["chapters"]
        }

    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        chap_url = chapter.get("url") or chapter.get("id")
        return mangalivre.get_chapter_images(chap_url, session)


# ----------------------------------------------------------------------
# 3. Motor Genérico: WordPress Madara / WP-Manga
# ----------------------------------------------------------------------
class MadaraProvider(BaseMangaProvider):
    name = "madara"
    display_name = "Madara (WordPress)"

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        # Heurística inicial por URL típica de temas madara/wp-manga
        parsed = urlparse(url)
        path = parsed.path.lower()
        if any(prefix in path for prefix in ["/manga/", "/manhwa/", "/manhua/", "/obra/", "/series/"]):
            # Se fornecida sessão, fazemos checagem rápida no HTML
            if session:
                try:
                    r = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=6)
                    if r.status_code == 200:
                        text = r.text.lower()
                        if any(marker in text for marker in [
                            "wp-manga", "manga-chapters-holder", "wp-content/themes/madara",
                            "admin-ajax.php", "listing-chapters_sub-head", "class=\"wp-manga-chapter\""
                        ]):
                            return True
                except Exception:
                    pass
        return False

    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        r = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Título
        title = ""
        post_title = soup.select_one(".post-title h1, .post-title h2, h1#manga-title, .manga-title h1")
        if post_title:
            title = post_title.get_text(strip=True)
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].split(" - ")[0].split(" | ")[0].strip()
        if not title and soup.title:
            title = soup.title.get_text(strip=True).split(" - ")[0].split(" | ")[0].strip()
        title = title or "Mangá Desconhecido"

        # Capa
        cover_url = ""
        summary_img = soup.select_one(".summary_image img, .manga-poster img, .tab-summary img")
        if summary_img:
            cover_url = summary_img.get("data-src") or summary_img.get("data-lazy-src") or summary_img.get("src") or ""
        if not cover_url:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                cover_url = og_img["content"]

        # Capítulos (Verificar se estão no HTML inicial ou via Ajax)
        chapters: List[Dict[str, Any]] = []
        chapter_items = soup.select("li.wp-manga-chapter, li.chapter-li, div.chapter-item")

        # Se não encontrou capítulos, tentar o endpoint AJAX do Madara
        if not chapter_items:
            manga_id_tag = soup.select_one("#manga-chapters-holder, [data-id]")
            manga_id = None
            if manga_id_tag:
                manga_id = manga_id_tag.get("data-id") or manga_id_tag.get("data-post-id")
            if not manga_id:
                # Tentar buscar ID no HTML via regex
                m_match = re.search(r'manga_id\s*=\s*["\']?(\d+)', r.text)
                if m_match:
                    manga_id = m_match.group(1)

            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Tentar via /ajax/chapters/ ou admin-ajax.php
            ajax_candidates = [
                (f"{url.rstrip('/')}/ajax/chapters/", "POST", {}),
                (f"{base_url}/wp-admin/admin-ajax.php", "POST", {"action": "manga_get_chapters", "manga": manga_id} if manga_id else None)
            ]

            for endpoint, method, payload in ajax_candidates:
                if not endpoint or (payload is None and method == "POST" and "admin-ajax" in endpoint):
                    continue
                try:
                    if method == "POST":
                        aj_res = session.post(endpoint, data=payload, headers={"User-Agent": USER_AGENT, "Referer": url}, timeout=10)
                    else:
                        aj_res = session.get(endpoint, headers={"User-Agent": USER_AGENT, "Referer": url}, timeout=10)
                    if aj_res.status_code == 200 and len(aj_res.text) > 100:
                        aj_soup = BeautifulSoup(aj_res.text, "html.parser")
                        items = aj_soup.select("li.wp-manga-chapter, li.chapter-li, a[href*='capitulo'], a[href*='chapter']")
                        if items:
                            chapter_items = items
                            break
                except Exception as e:
                    logger.debug("Tentativa ajax falhou para %s: %s", endpoint, e)

        # Parsear os capítulos encontrados
        for item in chapter_items:
            a_tag = item if item.name == "a" else item.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            ch_url = urljoin(url, a_tag["href"].strip())
            ch_text = a_tag.get_text(strip=True)

            # Extrair número do capítulo
            match = CHAPTER_NUM_REGEX.search(ch_text) or CHAPTER_NUM_REGEX.search(ch_url)
            if match:
                ch_num = match.group(1)
            else:
                nums = re.findall(r'\d+(?:\.\d+)?', ch_text)
                ch_num = nums[0] if nums else "0"

            chapters.append({
                "id": ch_url,
                "chapter": ch_num,
                "title": ch_text,
                "url": ch_url,
                "group": "WordPress"
            })

        # Ordenar capítulos numericamente em ordem crescente
        def sort_ch(c):
            try:
                return float(c["chapter"])
            except ValueError:
                return 9999.0

        # Deduplicar por número/URL
        seen_urls = set()
        dedup_chaps = []
        for c in sorted(chapters, key=sort_ch):
            if c["url"] not in seen_urls:
                seen_urls.add(c["url"])
                dedup_chaps.append(c)

        return {
            "title": title,
            "cover_url": cover_url,
            "available_langs": ["pt-br"],
            "chapters": dedup_chaps
        }

    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        chap_url = chapter["url"]
        r = session.get(chap_url, headers={"User-Agent": USER_AGENT, "Referer": chap_url}, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        images: List[str] = []
        img_tags = soup.select(
            ".reading-content img, .page-break img, .wp-manga-chapter-img, "
            "#readerarea img, .entry-content img, .chapter-content img"
        )
        for img in img_tags:
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src")
            if not src:
                continue
            src = src.strip()
            # Descartar imagens de placeholder
            if any(junk in src.lower() for junk in ["data:image", "spinner", "placeholder", "loading"]):
                continue
            full_src = urljoin(chap_url, src)
            if full_src not in images:
                images.append(full_src)

        return images


# ----------------------------------------------------------------------
# 4. Fallback Universal: Playwright Stealth + Sniffer de Rede
# ----------------------------------------------------------------------
class UniversalPlaywrightProvider(BaseMangaProvider):
    name = "universal"
    display_name = "Universal (Web)"

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        # Fallback universal para qualquer URL HTTP/HTTPS válida e remota
        try:
            parsed = urlparse(url)
            return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def _setup_browser_context(self, playwright_instance):
        browser = playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars"
            ]
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1
        )
        # Injeção de scripts stealth sem dependência externa
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
        """)
        return browser, context

    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, context = self._setup_browser_context(p)
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=25000)

                # Extrair Título
                title = page.evaluate("""() => {
                    const og = document.querySelector("meta[property='og:title']");
                    if (og && og.content) return og.content.split(' - ')[0].split(' | ')[0].trim();
                    const h1 = document.querySelector("h1");
                    if (h1 && h1.innerText) return h1.innerText.trim();
                    return document.title.split(' - ')[0].split(' | ')[0].trim();
                }""") or "Obra Universal"

                # Extrair Capa
                cover_url = page.evaluate("""() => {
                    const og = document.querySelector("meta[property='og:image']");
                    if (og && og.content) return og.content;
                    const poster = document.querySelector("img[src*='cover'], img[src*='poster'], img[src*='thumb']");
                    return poster ? poster.src : '';
                }""") or ""

                # Extrair Capítulos Heuristicamente de todas as tags <a>
                raw_links = page.evaluate(r"""() => {
                    const anchors = Array.from(document.querySelectorAll("a[href]"));
                    const regex = /(?:cap[ií]tulo|chapter|ch[-\s_.]?\d+|ep[-\s_.]?\d+|\/ler\/|\/read\/)/i;
                    const results = [];
                    for (const a of anchors) {
                        const href = a.href;
                        const text = a.innerText.trim();
                        if (regex.test(href) || regex.test(text)) {
                            results.push({ href: href, text: text });
                        }
                    }
                    return results;
                }""")

                chapters: List[Dict[str, Any]] = []
                seen_urls = set()

                for item in raw_links:
                    ch_url = item["href"]
                    ch_text = item["text"]
                    if ch_url in seen_urls or not ch_url.startswith("http"):
                        continue
                    seen_urls.add(ch_url)

                    # Descobrir número
                    match = CHAPTER_NUM_REGEX.search(ch_text) or CHAPTER_NUM_REGEX.search(ch_url)
                    if match:
                        num = match.group(1)
                    else:
                        nums = re.findall(r'\d+(?:\.\d+)?', ch_text) or re.findall(r'\d+(?:\.\d+)?', ch_url)
                        num = nums[0] if nums else "0"

                    chapters.append({
                        "id": ch_url,
                        "chapter": num,
                        "title": ch_text or f"Capítulo {num}",
                        "url": ch_url,
                        "group": "Web"
                    })

                # Ordenar capítulos em ordem crescente
                def sort_key(c):
                    try:
                        return float(c["chapter"])
                    except ValueError:
                        return 9999.0

                sorted_chapters = sorted(chapters, key=sort_key)

                return {
                    "title": title,
                    "cover_url": cover_url,
                    "available_langs": ["pt-br"],
                    "chapters": sorted_chapters
                }
            finally:
                browser.close()

    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        from playwright.sync_api import sync_playwright

        chap_url = chapter["url"]
        image_urls: List[str] = []

        with sync_playwright() as p:
            browser, context = self._setup_browser_context(p)
            try:
                page = context.new_page()

                # Sniffer de rede: intercepta requisições que retornam imagens
                def on_response(res):
                    try:
                        ct = res.headers.get("content-type", "").lower()
                        if "image/" in ct and res.status == 200:
                            u = res.url.split("?")[0]
                            # Filtro heurístico para descartar lixo (logos, avatares, ícones de anúncios)
                            if not any(junk in u.lower() for junk in [
                                "favicon", "logo", "avatar", "icon", "banner",
                                "badge", "adserver", "pixel", "tracking"
                            ]):
                                if res.url not in image_urls:
                                    image_urls.append(res.url)
                    except Exception:
                        pass

                page.on("response", on_response)
                page.goto(chap_url, wait_until="domcontentloaded", timeout=30000)

                # Rola suavemente até o final da página para acionar lazy-loading
                page.evaluate("""async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 600;
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= scrollHeight || totalHeight > 50000) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 120);
                    });
                }""")

                # Coletar também imagens declaradas diretamente nas tags <img>
                dom_imgs = page.evaluate("""() => {
                    const imgs = Array.from(document.querySelectorAll("img"));
                    const results = [];
                    for (const img of imgs) {
                        const src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.src;
                        if (src && src.startsWith('http')) {
                            results.push(src);
                        }
                    }
                    return results;
                }""")

                for src in dom_imgs:
                    if src not in image_urls and not any(junk in src.lower() for junk in [
                        "favicon", "logo", "avatar", "icon", "banner", "badge"
                    ]):
                        image_urls.append(src)

                return image_urls
            finally:
                browser.close()


# ----------------------------------------------------------------------
# Registro Global de Provedores (ProviderRegistry)
# ----------------------------------------------------------------------
class ProviderRegistry:
    """Gerenciador centralizado de provedores."""

    _providers: List[BaseMangaProvider] = [
        MangaDexProvider(),
        MangaLivreProvider(),
        MadaraProvider(),
        UniversalPlaywrightProvider()  # Fallback universal sempre no final
    ]

    @classmethod
    def get_providers(cls) -> List[BaseMangaProvider]:
        return list(cls._providers)

    @classmethod
    def get_provider(cls, name: str) -> BaseMangaProvider:
        for p in cls._providers:
            if p.name == name:
                return p
        return cls._providers[-1]  # Universal fallback

    @classmethod
    def get_provider_for_url(cls, url: str, session: Optional[requests.Session] = None) -> BaseMangaProvider:
        """
        Avalia a URL em cascata:
        1. Provedores específicos (MangaDex, MangaLivre)
        2. Provedor de CMS (Madara / WordPress)
        3. Provedor Universal Heurístico
        """
        clean_url = url.strip()
        for p in cls._providers:
            try:
                if p.can_handle(clean_url, session=session):
                    return p
            except Exception as e:
                logger.debug("Provedor %s can_handle falhou: %s", p.name, e)
        return cls.get_provider("universal")
