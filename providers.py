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
import os
import re
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import mangalivre
except ImportError:
    mangalivre = None

logger = logging.getLogger("providers")


def configure_playwright_environment():
    """
    Configura variáveis de ambiente para que o Playwright localize os navegadores
    instalados no sistema operacional (ex: %LOCALAPPDATA%\\ms-playwright),
    evitando que executáveis congelados via PyInstaller apontem para caminhos
    inexistentes em diretórios temporários.
    """
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(local_appdata, "ms-playwright")
        elif sys.platform == "darwin":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser("~/Library/Caches/ms-playwright")
        else:
            cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(cache_home, "ms-playwright")


configure_playwright_environment()


def get_playwright_profile_dir() -> str:
    """Retorna o diretório de perfil persistente para sessões e cookies do navegador."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        path = os.path.join(local_appdata, "MangaDex_CJrTools_browser")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/MangaDex_CJrTools_browser")
    else:
        cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        path = os.path.join(cache_home, "MangaDex_CJrTools_browser")
    os.makedirs(path, exist_ok=True)
    return path


def launch_playwright_browser(playwright_instance, headless: bool = True, args: Optional[List[str]] = None):
    """
    Inicia o Chromium de forma resiliente:
    1. Tenta o Chromium padrão do Playwright (respeitando PLAYWRIGHT_BROWSERS_PATH).
    2. Em caso de falha, tenta o Google Chrome instalado no sistema (channel="chrome").
    3. Em caso de falha, tenta o Microsoft Edge instalado no sistema (channel="msedge").
    """
    browser_args = args or [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars"
    ]

    # 1. Tentativa padrão Playwright
    try:
        return playwright_instance.chromium.launch(headless=headless, args=browser_args)
    except Exception as err:
        logger.warning("Chromium padrão do Playwright indisponível (%s). Tentando Chrome do sistema...", err)

    # 2. Fallback para Google Chrome instalado no sistema
    try:
        return playwright_instance.chromium.launch(channel="chrome", headless=headless, args=browser_args)
    except Exception as err:
        logger.warning("Google Chrome do sistema indisponível (%s). Tentando Microsoft Edge...", err)

    # 3. Fallback para Microsoft Edge instalado no sistema
    try:
        return playwright_instance.chromium.launch(channel="msedge", headless=headless, args=browser_args)
    except Exception as err:
        logger.error("Falha ao inicializar Chromium, Chrome e Edge: %s", err)
        raise RuntimeError(
            "Nenhum navegador compatível com Playwright foi encontrado no sistema.\n"
            "Instale os navegadores com 'playwright install' ou certifique-se de "
            "ter o Google Chrome ou Microsoft Edge instalados."
        ) from err


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

    def get_chapters_for_language(
        self,
        url: str,
        lang_code: str,
        session: requests.Session
    ) -> List[Dict[str, Any]]:
        """Retorna a lista de capítulos para um idioma específico."""
        info = self.get_manga_info(url, session, lang_code=lang_code)
        return info.get("chapters", [])

    def get_request_headers(self, page_url: str, chapter_url: Optional[str] = None) -> Dict[str, str]:
        """Headers adicionais (ex: Referer) para download das imagens."""
        if chapter_url:
            referer = chapter_url
        else:
            parsed = urlparse(page_url)
            referer = f"{parsed.scheme}://{parsed.netloc}"
        return {
            "User-Agent": USER_AGENT,
            "Referer": referer
        }

    def close_session(self):
        """Libera recursos ou instâncias de navegadores associadas ao provedor."""
        pass


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

        # Buscar Capítulos via método auxiliar
        normalized_chapters = self._fetch_chapters(uuid, lang_code, session)

        return {
            "title": title,
            "cover_url": cover_url,
            "available_langs": available_langs,
            "chapters": normalized_chapters
        }

    def _fetch_chapters(
        self,
        uuid: str,
        lang_code: str,
        session: requests.Session
    ) -> List[Dict[str, Any]]:
        """Busca e deduplica todos os capítulos para um idioma no MangaDex."""
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
        return normalized_chapters

    def get_chapters_for_language(
        self,
        url: str,
        lang_code: str,
        session: requests.Session
    ) -> List[Dict[str, Any]]:
        uuid = self._get_uuid(url, session)
        return self._fetch_chapters(uuid, lang_code, session)

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

    def _get_mangalivre(self):
        global mangalivre
        if mangalivre is None:
            import mangalivre
        return mangalivre

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        return self._get_mangalivre().is_mangalivre_url(url)

    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        info = self._get_mangalivre().get_manga_info(url, session)
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
        return self._get_mangalivre().get_chapter_images(chap_url, session)


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
# 4. Provedor de Fontes Catalogadas: Keiyoushi (index.pb)
# ----------------------------------------------------------------------
class KeiyoushiSourceProvider(BaseMangaProvider):
    name = "keiyoushi"
    display_name = "Keiyoushi (Catálogo)"

    def __init__(self):
        from keiyoushi_catalog import catalog
        self.catalog = catalog
        self._profile_dir = get_playwright_profile_dir()

    def close_session(self):
        """Método de compatibilidade para fechamento de sessões do provedor."""
        pass

    def _inject_stealth_scripts(self, context):
        """Injeta scripts anti-detecção no contexto do navegador."""
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
        """)

    def _launch_browser_context(self, playwright_instance, headless: bool = False):
        """
        Inicia um contexto de navegador Playwright de forma resiliente:
        1. Tenta perfil persistente em subdiretório dedicado ('user_profile').
        2. Em caso de lock ou falha, faz fallback automático para browser padrão + cookies salvos em JSON.
        Retorna uma tupla (context, browser_to_close). Se browser_to_close for None, o contexto é persistente.
        """
        import json
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars"
        ]
        sub_profile = os.path.join(self._profile_dir, "user_profile")
        os.makedirs(sub_profile, exist_ok=True)

        for channel in [None, "chrome", "msedge"]:
            try:
                kw = {"channel": channel} if channel else {}
                ctx = playwright_instance.chromium.launch_persistent_context(
                    user_data_dir=sub_profile,
                    headless=headless,
                    args=browser_args,
                    viewport={"width": 1280, "height": 800},
                    user_agent=USER_AGENT,
                    **kw
                )
                if ctx:
                    self._inject_stealth_scripts(ctx)
                    return ctx, None
            except Exception as e:
                logger.debug("Tentativa de persistent_context (%s) falhou: %s", channel, e)

        # Fallback: browser normal efêmero com injeção dos cookies salvos
        browser = launch_playwright_browser(playwright_instance, headless=headless, args=browser_args)
        ctx = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800}
        )
        self._inject_stealth_scripts(ctx)

        cookie_file = os.path.join(self._profile_dir, "mangafire_cookies.json")
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    saved_cookies = json.load(f)
                    ctx.add_cookies(saved_cookies)
            except Exception:
                pass
        return ctx, browser

    def _ensure_active_page(self, url: str):
        """Método de compatibilidade para verificação de página."""
        return None

    def can_handle(self, url: str, session: Optional[requests.Session] = None) -> bool:
        lower = url.lower()
        if "mangadex.org" in lower or "mangalivre" in lower:
            return False
        return self.catalog.find_source_by_url(url) is not None

    def get_source_info(self, url: str):
        return self.catalog.find_source_by_url(url)



    def get_manga_info(
        self,
        url: str,
        session: requests.Session,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        source = self.get_source_info(url)
        source_name = source.name if source else "Keiyoushi"
        source_lang = source.lang if source else "pt-br"
        logger.info("Analisando obra via fonte Keiyoushi: %s [%s] (%s)", source_name, source_lang, url)

        parsed_origin = urlparse(url)
        base_origin = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": base_origin
        }

        # 1. Tentativa rápida via HTTP requests + BeautifulSoup
        use_playwright = False
        soup = None
        html_text = ""

        try:
            r = session.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                html_text = r.text
                lower_text = html_text.lower()
                if any(cf_marker in lower_text for cf_marker in ["just a moment", "cf-browser-verification", "turnstile", "ddos-guard"]):
                    logger.info("Proteção Cloudflare/anti-bot detectada via requests. Escalando para Playwright...")
                    use_playwright = True
                else:
                    soup = BeautifulSoup(html_text, "html.parser")
            else:
                logger.info("Status HTTP %d ao acessar %s. Escalando para Playwright...", r.status_code, url)
                use_playwright = True
        except Exception as e:
            logger.info("Falha na requisição direta (%s). Escalando para Playwright...", e)
            use_playwright = True

        # Se requisição direta foi bem sucedida, tentar extração estruturada
        if not use_playwright and soup:
            info = self._extract_from_soup(soup, html_text, url, session, source_name)
            if info and info.get("chapters"):
                info["available_langs"] = [source_lang.lower()]
                info["provider"] = "keiyoushi"
                info["provider_display"] = f"{source_name} ({source_lang})"
                return info
            logger.info("Seletores HTML diretos não encontraram capítulos. Escalando para Playwright...")

        # 2. Fallback Playwright com bypass stealth
        return self._extract_via_playwright(url, source_name, source_lang, lang_code=lang_code)

    def _extract_from_soup(
        self,
        soup: BeautifulSoup,
        html_text: str,
        url: str,
        session: requests.Session,
        source_name: str
    ) -> Optional[Dict[str, Any]]:
        # Título
        title = ""
        post_title = soup.select_one(
            ".post-title h1, .post-title h2, h1#manga-title, .manga-title h1, "
            "h1.entry-title, .infox h1, h1.title-detail, .title h1, "
            ".detail-info h1, .title-detail__info h1, .manga-info h1"
        )
        if post_title:
            cand = post_title.get_text(strip=True)
            if cand and not any(sw in cand.lower() for sw in ["mangafire", "read manga online", "welcome"]):
                title = cand
        if not title:
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                cand = h1.get_text(strip=True)
                if cand and not any(sw in cand.lower() for sw in ["mangafire", "read manga online", "welcome"]):
                    title = cand
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                cand = og_title["content"].split(" - ")[0].split(" | ")[0].strip()
                if cand and not any(sw in cand.lower() for sw in ["mangafire", "read manga online"]):
                    title = cand
        if not title and soup.title:
            cand = soup.title.get_text(strip=True).split(" - ")[0].split(" | ")[0].strip()
            if cand and not any(sw in cand.lower() for sw in ["mangafire", "read manga online"]):
                title = cand
        title = title or "Mangá Desconhecido"

        # Capa
        cover_url = ""
        summary_img = soup.select_one(
            ".summary_image img, .manga-poster img, .tab-summary img, "
            ".thumb img, .infox .thumb img, .col-image img, .detail-info img"
        )
        if summary_img:
            cover_url = summary_img.get("data-src") or summary_img.get("data-lazy-src") or summary_img.get("src") or ""
        if not cover_url:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                cover_url = og_img["content"]

        # Capítulos: testar seletores de múltiplos CMS (Madara, MangaThemesia, WpComics)
        chapter_items = soup.select(
            "li.wp-manga-chapter, li.chapter-li, div.chapter-item, "
            ".eph-num, #chapterlist li, .clstyle li, ul.cl-list li, "
            ".list-chapter li, ul.chapter-list li"
        )

        # Se não achou nos itens, tentar AJAX do Madara
        if not chapter_items:
            manga_id_tag = soup.select_one("#manga-chapters-holder, [data-id], [data-post-id]")
            manga_id = None
            if manga_id_tag:
                manga_id = manga_id_tag.get("data-id") or manga_id_tag.get("data-post-id")
            if not manga_id:
                m_match = re.search(r'manga_id\s*=\s*["\']?(\d+)', html_text)
                if m_match:
                    manga_id = m_match.group(1)

            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
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
                except Exception:
                    pass

        # Parsear links de capítulos
        chapters: List[Dict[str, Any]] = []
        seen_urls = set()
        for item in chapter_items:
            a_tag = item if item.name == "a" else item.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            ch_url = urljoin(url, a_tag["href"].strip())
            ch_text = a_tag.get_text(strip=True)

            if ch_url in seen_urls:
                continue
            seen_urls.add(ch_url)

            match = CHAPTER_NUM_REGEX.search(ch_text) or CHAPTER_NUM_REGEX.search(ch_url)
            if match:
                ch_num = match.group(1)
            else:
                nums = re.findall(r'\d+(?:\.\d+)?', ch_text)
                ch_num = nums[0] if nums else "0"

            chapters.append({
                "id": ch_url,
                "chapter": ch_num,
                "title": ch_text or f"Capítulo {ch_num}",
                "url": ch_url,
                "group": source_name
            })

        if not chapters:
            return None

        def sort_ch(c):
            try:
                return float(c["chapter"])
            except ValueError:
                return 9999.0

        chapters.sort(key=sort_ch)
        return {
            "title": title,
            "cover_url": cover_url,
            "chapters": chapters,
            "all_chapters": chapters,
            "selected_chapters": chapters,
            "available_langs": [source_lang.lower()],
            "detected_langs": [source_lang],
            "current_lang": source_lang
        }

    def _extract_via_playwright(
        self,
        url: str,
        source_name: str,
        source_lang: str,
        lang_code: str = "pt-br"
    ) -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright
        import json
        import time

        with sync_playwright() as p:
            ctx, browser_to_close = self._launch_browser_context(p, headless=False)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # Se houver desafio WAF / Cloudflare Turnstile, aguarda resolução humana (até 60s)
                start_t = time.time()
                while time.time() - start_t < 60:
                    curr_url = page.url
                    curr_title = page.title().lower()
                    if "@waf" in curr_url or "challenge" in curr_url or "security check" in curr_title or "just a moment" in curr_title:
                        logger.info("Aguardando verificação de segurança no navegador visível...")
                        page.wait_for_timeout(1000)
                    else:
                        break

                page.wait_for_timeout(1500)

                # Salva cookies atualizados para sessões futuras
                try:
                    cookies = ctx.cookies()
                    cookie_file = os.path.join(self._profile_dir, "mangafire_cookies.json")
                    with open(cookie_file, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, indent=2)
                except Exception:
                    pass

                # Extrair Título: prioriza #syncData (MangaFire), headings e título do conteúdo sobre og:title genérico
                title = page.evaluate("""() => {
                    const syncScript = document.querySelector("#syncData");
                    if (syncScript) {
                        try {
                            const data = JSON.parse(syncScript.textContent);
                            if (data && data.name) return data.name.trim();
                        } catch(e) {}
                    }
                    const heading = document.querySelector(".title-detail__title, .title-detail__info h1, .post-title h1, .entry-title, h1#manga-title, .title-detail h1, .detail-info h1, h1");
                    if (heading && heading.innerText) {
                        const text = heading.innerText.trim();
                        if (text && !/mangafire|read manga online|welcome|home/i.test(text)) {
                            return text;
                        }
                    }
                    if (document.title) {
                        const t = document.title.split(' - ')[0].split(' | ')[0].trim();
                        if (t && !/mangafire|read manga online/i.test(t)) return t;
                    }
                    const og = document.querySelector("meta[property='og:title']");
                    if (og && og.content) {
                        const t = og.content.split(' - ')[0].split(' | ')[0].trim();
                        if (t && !/mangafire|read manga online/i.test(t)) return t;
                    }
                    return "Mangá Keiyoushi";
                }""") or "Mangá Keiyoushi"

                # Extrair Capa (suporta .title-detail__poster img)
                cover_url = page.evaluate("""() => {
                    const poster = document.querySelector(".title-detail__poster img, .summary_image img, .thumb img, img[src*='cover'], img[src*='poster']");
                    if (poster) return poster.dataset.src || poster.src || '';
                    const og = document.querySelector("meta[property='og:image']");
                    if (og && og.content) return og.content;
                    return '';
                }""") or ""

                # Detectar Idiomas Disponíveis e alternar para o idioma desejado (MangaFire)
                target_norm = (lang_code or "pt-br").lower()
                detected_langs = []
                switched_lang = False
                try:
                    # 1. Abre o dropdown de idiomas
                    opened_lang = page.evaluate("""() => {
                        const langBtn = Array.from(document.querySelectorAll('button.select')).find(b => b.innerText.toUpperCase().includes('LANG'));
                        if (langBtn) {
                            langBtn.click();
                            return true;
                        }
                        return false;
                    }""")
                    if opened_lang:
                        page.wait_for_timeout(400)
                        lang_res = page.evaluate("""(target) => {
                            const items = Array.from(document.querySelectorAll('.dropdown__item, [role="menuitem"]'));
                            const langs = [];
                            let targetItem = null;
                            const isPt = target.startsWith('pt');
                            const isEn = target.startsWith('en');
                            const isEs = target.startsWith('es');

                            for (const it of items) {
                                const txt = it.innerText.toLowerCase();
                                if (txt.includes('portuguese') || txt.includes('português')) {
                                    langs.push('pt-br');
                                    if (isPt) targetItem = it;
                                } else if (txt.includes('english') || txt.includes('inglês')) {
                                    langs.push('en');
                                    if (isEn) targetItem = it;
                                } else if (txt.includes('latam') || txt.includes('spanish (latam)')) {
                                    langs.push('es-la');
                                    if (isEs && target.includes('la')) targetItem = it;
                                } else if (txt.includes('spanish') || txt.includes('espanhol')) {
                                    langs.push('es');
                                    if (isEs && !targetItem) targetItem = it;
                                } else if (txt.includes('japanese') || txt.includes('japonês')) {
                                    langs.push('ja');
                                    if (target.startsWith('ja')) targetItem = it;
                                }
                            }

                            if (targetItem) {
                                targetItem.click();
                                return {switched: true, detected: Array.from(new Set(langs))};
                            } else {
                                const langBtn = Array.from(document.querySelectorAll('button.select')).find(b => b.innerText.toUpperCase().includes('LANG'));
                                if (langBtn) langBtn.click();
                                return {switched: false, detected: Array.from(new Set(langs))};
                            }
                        }""", target_norm)
                        detected_langs = lang_res.get("detected", [])
                        switched_lang = lang_res.get("switched", False)
                        if switched_lang:
                            page.wait_for_timeout(1800)
                except Exception:
                    pass

                available_langs = detected_langs if detected_langs else [source_lang.lower()]
                if "pt-br" not in available_langs and "pt" in available_langs:
                    available_langs.append("pt-br")

                # Extrair Capítulos (com suporte a paginação assíncrona como no MangaFire)
                def extract_page_anchors():
                    return page.evaluate(r"""() => {
                        const selectors = [
                            ".title-detail__chapters a[href*='/chapter/']",
                            "li.wp-manga-chapter a", "#chapterlist li a", ".clstyle li a",
                            ".list-chapter li a", "ul.chapter-list li a", ".eph-num a"
                        ];
                        let anchors = [];
                        for (const sel of selectors) {
                            const found = Array.from(document.querySelectorAll(sel));
                            if (found.length > 0) {
                                anchors = found;
                                break;
                            }
                        }
                        if (anchors.length === 0) {
                            anchors = Array.from(document.querySelectorAll("a[href]"));
                        }
                        const regex = /(?:cap[ií]tulo|chapter|ch[-\s_.]?\d+|ep[-\s_.]?\d+|\/ler\/|\/read\/|\/cap-\d+|\/chapter\/)/i;
                        const results = [];
                        for (const a of anchors) {
                            const href = a.href;
                            const text = a.innerText.trim();
                            if (regex.test(href) || regex.test(text)) {
                                const isOfficial = !!a.querySelector('.title-detail__row-badge[title="Official"]') ||
                                                  !!a.closest('.title-detail__row')?.querySelector('.title-detail__row-badge[title="Official"]');
                                results.push({ href: href, text: text, official: isOfficial });
                            }
                        }
                        return results;
                    }""")

                raw_links = extract_page_anchors()

                # Paginação completa via botão "Next page" ou botão numérico subsequente (.npager__num)
                try:
                    crawled_pages = 0
                    while crawled_pages < 150:
                        crawled_pages += 1
                        has_next = page.evaluate("""() => {
                            const nextBtn = document.querySelector('button.npager__nav[aria-label="Next page"]');
                            if (nextBtn && !nextBtn.disabled && !nextBtn.classList.contains('disabled')) {
                                nextBtn.click();
                                return true;
                            }
                            const activeEl = document.querySelector('.npager__num.is-active');
                            const activeNum = activeEl ? parseInt(activeEl.innerText.trim()) : 0;
                            const nums = Array.from(document.querySelectorAll('.npager__num'));
                            const nextNum = nums.find(b => parseInt(b.innerText.trim()) === activeNum + 1);
                            if (nextNum) {
                                nextNum.click();
                                return true;
                            }
                            return false;
                        }""")
                        if not has_next:
                            break
                        page.wait_for_timeout(600)
                        page_links = extract_page_anchors()
                        raw_links.extend(page_links)
                except Exception:
                    pass

                chapters_by_num: Dict[str, Dict[str, Any]] = {}
                seen_urls = set()
                for item in raw_links:
                    ch_url = item["href"]
                    ch_text = item["text"]
                    is_official = item.get("official", False)
                    if ch_url in seen_urls or not ch_url.startswith("http"):
                        continue
                    seen_urls.add(ch_url)

                    match = CHAPTER_NUM_REGEX.search(ch_text) or CHAPTER_NUM_REGEX.search(ch_url)
                    if match:
                        num = match.group(1)
                    else:
                        nums = re.findall(r'\d+(?:\.\d+)?', ch_text) or re.findall(r'\d+(?:\.\d+)?', ch_url)
                        num = nums[0] if nums else "0"

                    ch_obj = {
                        "id": ch_url,
                        "chapter": num,
                        "title": ch_text or f"Capítulo {num}",
                        "url": ch_url,
                        "group": f"{source_name} (Oficial)" if is_official else source_name
                    }

                    # Se já existe esse número de capítulo, prioriza versão Oficial para evitar duplicação em fila
                    if num in chapters_by_num:
                        if is_official and "(Oficial)" not in chapters_by_num[num].get("group", ""):
                            chapters_by_num[num] = ch_obj
                    else:
                        chapters_by_num[num] = ch_obj

                chapters = list(chapters_by_num.values())

                def sort_key(c):
                    try:
                        return float(c["chapter"])
                    except ValueError:
                        return 9999.0

                return {
                    "title": title,
                    "cover_url": cover_url,
                    "available_langs": available_langs,
                    "current_lang": lang_code,
                    "chapters": sorted(chapters, key=sort_key),
                    "provider": "keiyoushi",
                    "provider_display": f"{source_name} ({source_lang})"
                }
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
                if browser_to_close:
                    try:
                        browser_to_close.close()
                    except Exception:
                        pass

    def get_chapter_pages(
        self,
        chapter: Dict[str, Any],
        session: requests.Session,
        datasaver: bool = False
    ) -> List[str]:
        chap_url = chapter["url"]
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": chap_url
        }

        # Tentativa rápida via requests + BeautifulSoup
        try:
            r = session.get(chap_url, headers=headers, timeout=12)
            if r.status_code == 200 and "just a moment" not in r.text.lower():
                soup = BeautifulSoup(r.text, "html.parser")
                img_tags = soup.select(
                    ".reading-content img, .page-break img, .wp-manga-chapter-img, "
                    "#readerarea img, .reader-area img, .page-chapter img, "
                    ".reading-detail img, .chapter-content img, .entry-content img"
                )
                images: List[str] = []
                for img in img_tags:
                    src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src")
                    if not src:
                        continue
                    src = src.strip()
                    if any(junk in src.lower() for junk in ["data:image", "spinner", "placeholder", "loading", "logo", "banner"]):
                        continue
                    full_src = urljoin(chap_url, src)
                    if full_src not in images:
                        images.append(full_src)
                if len(images) > 1:
                    return images
        except Exception:
            pass

        # Fallback via Playwright com sniffer de rede e scroll
        return self._get_chapter_pages_playwright(chap_url)

    def _get_chapter_pages_playwright(self, chap_url: str) -> List[str]:
        from playwright.sync_api import sync_playwright
        import json
        import time

        api_pages: List[str] = []
        image_urls: List[str] = []

        with sync_playwright() as p:
            ctx, browser_to_close = self._launch_browser_context(p, headless=True)
            try:
                page = ctx.new_page()

                def on_response(res):
                    try:
                        # 1. Interceptar APIs de capítulos estruturadas (ex: MangaFire /api/chapters/<id>)
                        if ("/api/chapters/" in res.url or "/api/chapter/" in res.url) and res.status == 200:
                            data = res.json()
                            if isinstance(data, dict):
                                ch_data = data.get("data", data)
                                pages_list = ch_data.get("pages") or ch_data.get("images") or []
                                for item in pages_list:
                                    u = item.get("url") if isinstance(item, dict) else str(item)
                                    if u and u.startswith("http") and u not in api_pages:
                                        api_pages.append(u)

                        # 2. Sniffer de rede para respostas com content-type de imagem
                        ct = res.headers.get("content-type", "").lower()
                        if "image/" in ct and res.status == 200:
                            u = res.url.split("?")[0]
                            if not any(junk in u.lower() for junk in [
                                "favicon", "logo", "avatar", "icon", "banner",
                                "badge", "adserver", "pixel", "tracking"
                            ]):
                                if res.url not in image_urls:
                                    image_urls.append(res.url)
                    except Exception:
                        pass

                page.on("response", on_response)
                page.goto(chap_url, wait_until="domcontentloaded", timeout=40000)

                start_t = time.time()
                while time.time() - start_t < 10:
                    if api_pages:
                        break
                    if "@waf" in page.url or "challenge" in page.url:
                        page.wait_for_timeout(1000)
                    else:
                        page.wait_for_timeout(500)

                if api_pages:
                    logger.info("Capítulo extraído via API interceptada: %d páginas", len(api_pages))
                    return api_pages

                # Scroll para lazy loading
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

                dom_imgs = page.evaluate("""() => {
                    const selectors = [
                        ".reader__page img", ".reader-swiper img", ".reader-swiper__img",
                        "img.reader-img", ".swiper-slide img", "#readerarea img",
                        ".reading-content img", ".page-chapter img", ".entry-content img",
                        ".reader-body img", ".reader__strip img", "img"
                    ];
                    let found = [];
                    for (const s of selectors) {
                        const list = Array.from(document.querySelectorAll(s));
                        if (list.length > 2) {
                            found = list;
                            break;
                        }
                    }
                    if (found.length === 0) found = Array.from(document.querySelectorAll("img"));
                    const results = [];
                    for (const img of found) {
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
                try:
                    ctx.close()
                except Exception:
                    pass
                if browser_to_close:
                    try:
                        browser_to_close.close()
                    except Exception:
                        pass

    def get_chapter_group(self, chapter: Dict[str, Any], session: requests.Session) -> str:
        if chapter.get("group"):
            return chapter["group"]
        source = self.get_source_info(chapter.get("url", ""))
        return source.name if source else self.display_name

    def get_request_headers(self, page_url: str, chapter_url: Optional[str] = None) -> Dict[str, str]:
        if chapter_url:
            referer = chapter_url
        else:
            parsed = urlparse(page_url)
            referer = f"{parsed.scheme}://{parsed.netloc}"
        return {
            "User-Agent": USER_AGENT,
            "Referer": referer
        }


# ----------------------------------------------------------------------
# 5. Fallback Universal: Playwright Stealth + Sniffer de Rede
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
        browser = launch_playwright_browser(
            playwright_instance,
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
        import time

        chap_url = chapter["url"]
        api_pages: List[str] = []
        image_urls: List[str] = []

        with sync_playwright() as p:
            browser, context = self._setup_browser_context(p)
            try:
                page = context.new_page()

                # Sniffer de rede: intercepta requisições estruturadas e de imagens
                def on_response(res):
                    try:
                        if ("/api/chapters/" in res.url or "/api/chapter/" in res.url) and res.status == 200:
                            data = res.json()
                            if isinstance(data, dict):
                                ch_data = data.get("data", data)
                                pages_list = ch_data.get("pages") or ch_data.get("images") or []
                                for item in pages_list:
                                    u = item.get("url") if isinstance(item, dict) else str(item)
                                    if u and u.startswith("http") and u not in api_pages:
                                        api_pages.append(u)

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

                start_t = time.time()
                while time.time() - start_t < 10:
                    if api_pages:
                        break
                    page.wait_for_timeout(500)

                if api_pages:
                    logger.info("Universal: Capítulo extraído via API interceptada: %d páginas", len(api_pages))
                    return api_pages

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
                    const selectors = [
                        ".reader__page img", ".reader-swiper img", ".reader-swiper__img",
                        "img.reader-img", ".swiper-slide img", "#readerarea img",
                        ".reading-content img", ".page-chapter img", ".entry-content img",
                        ".reader-body img", ".reader__strip img", "img"
                    ];
                    let found = [];
                    for (const s of selectors) {
                        const list = Array.from(document.querySelectorAll(s));
                        if (list.length > 2) {
                            found = list;
                            break;
                        }
                    }
                    if (found.length === 0) found = Array.from(document.querySelectorAll("img"));
                    const results = [];
                    for (const img of found) {
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
        KeiyoushiSourceProvider(),
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
        2. Provedor de Fontes Keiyoushi (index.pb)
        3. Provedor de CMS (Madara / WordPress)
        4. Provedor Universal Heurístico
        """
        clean_url = url.strip()
        for p in cls._providers:
            try:
                if p.can_handle(clean_url, session=session):
                    return p
            except Exception as e:
                logger.debug("Provedor %s can_handle falhou: %s", p.name, e)
        return cls.get_provider("universal")
