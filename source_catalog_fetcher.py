#!/usr/bin/env python3
"""
source_catalog_fetcher.py - Mecanismo de extração e indexação do catálogo de mangás por site.
Permite listar os mangás disponíveis em qualquer uma das mais de 2.200 fontes do index.pb,
incluindo MangaDex (via API oficial) e sites baseados em Madara, MangaThemesia, WpComics e genéricos.
Possui suporte a paginação e cache local em JSON para carregamento instantâneo.
"""

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from keiyoushi_catalog import KeiyoushiSource, catalog

logger = logging.getLogger("source_catalog_fetcher")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

if getattr(sys, "frozen", False):
    CACHE_DIR = Path(sys.executable).resolve().parent / "catalog_cache"
else:
    CACHE_DIR = Path(__file__).resolve().parent / "catalog_cache"



def get_cache_path(domain: str, page: int, lang: str = "") -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    clean_domain = re.sub(r'[^a-zA-Z0-9_\.-]', '_', domain)
    clean_lang = re.sub(r'[^a-zA-Z0-9_\.-]', '_', lang.lower()) if lang else ""
    suffix = f"_{clean_lang}" if clean_lang else ""
    return CACHE_DIR / f"{clean_domain}{suffix}_p{page}.json"


def fetch_source_catalog(
    source: KeiyoushiSource,
    page: int = 1,
    force_refresh: bool = False,
    timeout: int = 10
) -> List[Dict[str, Any]]:
    """
    Busca a lista de mangás disponíveis para a fonte informada na página indicada.
    Retorna lista de dicionários com: title, url, cover_url, chapter_info, source_name, lang.
    """
    domain = catalog.extract_domain(source.base_url)
    cache_file = get_cache_path(domain, page, lang=source.lang)

    # Verificar se existe cache recente (< 12 horas)
    if not force_refresh and cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime < 12 * 3600:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if isinstance(cached, list) and cached:
                        logger.info("Retornando %d mangás do cache local para %s [%s] (página %d)", len(cached), domain, source.lang, page)
                        return cached
        except Exception as e:
            logger.debug("Falha ao ler cache local: %s", e)

    results = []

    # 1. Provedor Especial: MangaDex
    if "mangadex" in source.pkg.lower() or "mangadex.org" in source.base_url.lower():
        results = _fetch_mangadex_catalog(page, source, timeout)

    # 2. Provedor Especial: MangaFire
    elif "mangafire" in source.pkg.lower() or "mangafire.to" in source.base_url.lower():
        results = _fetch_mangafire_catalog(source, page, timeout)

    # 3. Fontes da Web / Scans Gerais
    if not results:
        results = _fetch_web_catalog(source, page, timeout)

    # Salvar em cache se houver resultados
    if results:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("Falha ao salvar cache local: %s", e)

    return results


def _fetch_mangadex_catalog(page: int, source: KeiyoushiSource, timeout: int) -> List[Dict[str, Any]]:
    """Consulta os mangás populares da API oficial do MangaDex com capa e título."""
    limit = 30
    offset = (page - 1) * limit
    api_url = f"https://api.mangadex.org/manga?limit={limit}&offset={offset}&order[followedCount]=desc&includes[]=cover_art"

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        r = session.get(api_url, timeout=timeout)
        if r.status_code != 200:
            return []

        data = r.json().get("data", [])
        results = []
        for item in data:
            m_id = item.get("id", "")
            attrs = item.get("attributes", {})

            # Título: preferir pt-br, depois en, depois o primeiro disponível
            title_dict = attrs.get("title", {})
            title = title_dict.get("pt-br") or title_dict.get("en")
            if not title and title_dict:
                title = next(iter(title_dict.values()))
            title = title or "Título Desconhecido"

            # Capa
            cover_url = ""
            for rel in item.get("relationships", []):
                if rel.get("type") == "cover_art":
                    c_attrs = rel.get("attributes", {})
                    file_name = c_attrs.get("fileName")
                    if file_name:
                        cover_url = f"https://uploads.mangadex.org/covers/{m_id}/{file_name}.256.jpg"
                    break

            last_ch = attrs.get("lastChapter") or ""
            ch_info = f"Até Cap. {last_ch}" if last_ch else "Disponível"

            m_url = f"https://mangadex.org/title/{m_id}"
            results.append({
                "title": title,
                "url": m_url,
                "cover_url": cover_url,
                "chapter_info": ch_info,
                "source_name": "MangaDex",
                "lang": source.lang or "pt-br"
            })
        return results

    except Exception as e:
        logger.warning("Falha ao buscar catálogo do MangaDex: %s", e)
        return []


def _fetch_mangafire_catalog(source: KeiyoushiSource, page: int, timeout: int) -> List[Dict[str, Any]]:
    """Consulta o catálogo do MangaFire com suporte ao filtro de idioma e paginação via Playwright."""
    from playwright.sync_api import sync_playwright

    base_url = source.base_url.rstrip("/")
    lang_raw = (source.lang or "pt-br").lower()
    if lang_raw in ("pt-br", "pt"):
        lang_param = "pt-br"
    elif lang_raw in ("es-419", "es-la"):
        lang_param = "es-la"
    elif lang_raw in ("en", "es", "ja", "fr"):
        lang_param = lang_raw
    else:
        lang_param = ""

    if lang_param:
        target_url = f"{base_url}/browse?languages%5B%5D={lang_param}&page={page}"
    else:
        target_url = f"{base_url}/browse?page={page}"

    results: List[Dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            from providers import launch_playwright_browser
            browser = launch_playwright_browser(
                p,
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars"]
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800}
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
            """)
            page_obj = context.new_page()

            def on_response(res):
                if "/api/titles" in res.url and res.status == 200:
                    try:
                        j = res.json()
                        items = j.get("items", [])
                        for it in items:
                            title = it.get("title", "")
                            slug = it.get("url") or ""
                            url = f"{base_url}{slug}" if slug.startswith("/") else slug
                            poster = it.get("poster")
                            cover_url = ""
                            if isinstance(poster, dict):
                                cover_url = poster.get("medium") or poster.get("large") or poster.get("small") or ""
                            elif isinstance(poster, str):
                                cover_url = poster
                            ch = it.get("latestChapter")
                            ch_info = f"Cap. {ch}" if ch else "Disponível"
                            if title and url and not any(r["url"] == url for r in results):
                                results.append({
                                    "title": title,
                                    "url": url,
                                    "cover_url": cover_url,
                                    "chapter_info": ch_info,
                                    "source_name": source.name,
                                    "lang": source.lang or "pt-br"
                                })
                    except Exception:
                        pass

            page_obj.on("response", on_response)
            page_obj.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            start_t = time.time()
            while time.time() - start_t < 8:
                if len(results) >= 20:
                    break
                if "@waf" in page_obj.url or "challenge" in page_obj.url:
                    page_obj.wait_for_timeout(1000)
                else:
                    page_obj.wait_for_timeout(500)

            # Fallback DOM se a API não interceptou nada
            if not results:
                cards = page_obj.evaluate(r"""() => {
                    const els = Array.from(document.querySelectorAll('.manga-card, .card, .title-row-card, .title-grid__link'));
                    return els.map(c => {
                        const a = c.tagName === 'A' ? c : (c.querySelector('a') || c.closest('a'));
                        const img = c.querySelector('img');
                        const titleEl = c.querySelector('.manga-card__title, .card__title, .title-row-card__title');
                        const chEl = c.querySelector('.manga-card__foot, .title-row-card__meta, .manga-card__ch');
                        return {
                            href: a ? a.href : '',
                            title: titleEl ? titleEl.innerText.trim() : (img ? img.alt : ''),
                            img: img ? (img.dataset.src || img.src || '') : '',
                            ch: chEl ? chEl.innerText.trim() : 'Disponível'
                        };
                    }).filter(x => x.href && x.title);
                }""")
                for c in cards:
                    if not any(r["url"] == c["href"] for r in results):
                        results.append({
                            "title": c["title"],
                            "url": c["href"],
                            "cover_url": c["img"],
                            "chapter_info": c["ch"],
                            "source_name": source.name,
                            "lang": source.lang or "pt-br"
                        })
            browser.close()
    except Exception as e:
        logger.error("Erro ao buscar catálogo do MangaFire via Playwright: %s", e)

    return results


def _fetch_web_catalog(source: KeiyoushiSource, page: int, timeout: int) -> List[Dict[str, Any]]:
    """Tenta obter o catálogo via HTTP direto (Madara, MangaThemesia, WpComics) ou Playwright fallback."""
    base_url = source.base_url.rstrip("/")
    candidates = [
        f"{base_url}/manga/page/{page}/",
        f"{base_url}/manga/?page={page}",
        f"{base_url}/manga/?order=popular&page={page}",
        f"{base_url}/manga/?m_orderby=views&page={page}",
        f"{base_url}/projetos/page/{page}/",
        f"{base_url}/projetos/?page={page}",
        f"{base_url}/series/page/{page}/",
        f"{base_url}/obras/page/{page}/",
        f"{base_url}/manga/" if page == 1 else "",
        f"{base_url}/" if page == 1 else ""
    ]

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": base_url
    })

    use_playwright = False
    for target_url in candidates:
        if not target_url:
            continue
        try:
            r = session.get(target_url, timeout=timeout)
            if r.status_code == 200:
                lower = r.text.lower()
                if any(cf in lower for cf in ["just a moment", "cf-browser-verification", "turnstile", "ddos-guard"]):
                    use_playwright = True
                    break

                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select(
                    ".page-item-detail, .manga-item, .bsx, .item, .story-item, "
                    ".c-tabs-item__content, article, .box-item, .manga-card, "
                    ".title-row-card, .title-grid__link"
                )
                if cards:
                    items = _parse_cards(cards, base_url, source)
                    if items:
                        return items
            elif r.status_code in (403, 503):
                use_playwright = True
                break
        except Exception as e:
            logger.debug("Falha na tentativa de rota %s: %s", target_url, e)
            continue

    if use_playwright:
        logger.info("Iniciando Playwright para extrair catálogo com proteção Cloudflare de %s", base_url)
        return _fetch_web_catalog_playwright(base_url, page, source)

    return []


def _clean_card_title(raw_title: str, img_tag=None, m_url: str = "", **kwargs) -> str:
    """Aplica heurística universal para extrair o título limpo e correto da obra."""
    if not m_url and "link_href" in kwargs:
        m_url = kwargs["link_href"] or ""

    # 1. Se a imagem de capa tiver um atributo alt significativo (muito comum em plataformas modernas)
    if img_tag:
        img_alt = (img_tag.get("alt") or "").strip()
        if img_alt:
            # Remover prefixos comuns de acessibilidade
            c_alt = re.sub(
                r'^(?:cover\s+(?:for|of)|capa\s+(?:de|para)|poster\s+for|thumbnail\s+for|image\s+for)\s+',
                '',
                img_alt,
                flags=re.I
            ).strip()
            # Remover sufixos comuns
            c_alt = re.sub(
                r'\s+-\s+(?:manga|webtoon|comic|manhwa|read\s+online|scan|oficial).*$',
                '',
                c_alt,
                flags=re.I
            ).strip()
            if len(c_alt) >= 2 and not any(noise in c_alt.lower() for noise in ['banner', 'thumbnail', 'thumb', 'chapter', 'default cover', 'no cover', 'no image', 'placeholder', 'sem capa']):
                return c_alt

    # 2. Verificar se raw_title contém ruídos de botões da interface (ex: Visit Series, Read Now, SIMUL, etc.)
    noise_indicators = [
        "visit series", "read now", "read online", "simul", "diário", "diario",
        "evento", "webtoon", "chapter", "chapters"
    ]
    has_noise = any(n in raw_title.lower() for n in noise_indicators)

    # 3. Se raw_title não tem ruído e é válido, usa ele
    if raw_title and not has_noise and len(raw_title) >= 2:
        return raw_title

    # 4. Fallback Universal: Extrair e formatar título a partir do slug da URL
    path_parts = [p for p in urlparse(m_url).path.split('/') if p and not p.isdigit()]
    if path_parts:
        slug = path_parts[-1]
        slug = re.sub(r'-(?:webtoon|manga|comic|manhwa|series|read|scan)$', '', slug, flags=re.I)
        clean = slug.replace('-', ' ').replace('_', ' ').strip().title()
        if len(clean) >= 2:
            return clean

    return raw_title or "Obra sem título"


def _parse_cards(cards, base_url: str, source: KeiyoushiSource) -> List[Dict[str, Any]]:
    """Extrai campos estruturados (título, url, capa, capítulo) de tags de card HTML."""
    results = []
    seen_urls = set()

    ignored_slugs = {
        "", "comics", "genres", "news", "manga", "series", "projetos", "obras",
        "latest", "popular", "home", "about", "contact", "contato", "sobre",
        "login", "register", "privacy", "terms", "faq", "dmca", "categoria"
    }

    for c in cards:
        a_tag = (
            c.select_one(".post-title a, h3 a, h4 a, .tt a, a.series, .title a, a[title]")
            or c.find("a")
        )
        if not a_tag or not a_tag.get("href"):
            continue

        href = a_tag["href"].strip()
        m_url = urljoin(base_url, href)
        if m_url in seen_urls:
            continue

        parsed = urlparse(m_url)
        path_clean = parsed.path.strip("/")
        if path_clean.lower() in ignored_slugs or not path_clean:
            continue

        # Ignorar links de autores, pessoas, tags ou buscas
        query_lower = parsed.query.lower()
        if any(qp in query_lower for qp in ["person=", "author=", "genre=", "tag=", "search="]):
            continue

        seen_urls.add(m_url)

        raw_title = a_tag.get_text(strip=True) or a_tag.get("title") or ""
        if not raw_title:
            h = c.select_one("h1, h2, h3, h4, h5, .title, .tt")
            if h:
                raw_title = h.get_text(strip=True)

        img = c.select_one("img")
        title = _clean_card_title(raw_title, img, m_url)
        if not title or len(title) < 2 or title.lower() in ignored_slugs:
            continue

        cover_url = ""
        if img:
            cover_url = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("src")
                or ""
            ).strip()
            if cover_url:
                cover_url = urljoin(base_url, cover_url)

        # Informação de capítulos
        ch_tag = c.select_one(".chapter-item, .list-chapter, .epxs, .chapter, span.font-meta, .chapter-title")
        ch_info = ch_tag.get_text(strip=True) if ch_tag else "Disponível"

        results.append({
            "title": title,
            "url": m_url,
            "cover_url": cover_url,
            "chapter_info": ch_info,
            "source_name": source.name,
            "lang": source.lang or "pt-br"
        })

    return results


def _fetch_web_catalog_playwright(base_url: str, page: int, source: KeiyoushiSource) -> List[Dict[str, Any]]:
    """Usa Playwright stealth com espera de Cloudflare para extrair o catálogo da página."""
    from playwright.sync_api import sync_playwright

    target_url = f"{base_url}/manga/page/{page}/" if page > 1 else f"{base_url}/manga/"
    results = []

    try:
        with sync_playwright() as p:
            from providers import launch_playwright_browser
            browser = launch_playwright_browser(
                p,
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars"]
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            """)
            page_obj = context.new_page()

            try:
                page_obj.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                # Aguardar se Cloudflare estiver ativo
                for _ in range(5):
                    t = page_obj.title().lower()
                    if "just a moment" in t or "cloudflare" in t:
                        page_obj.wait_for_timeout(1500)
                    else:
                        break

                cards_data = page_obj.evaluate(r"""() => {
                    const selectors = [
                        ".page-item-detail", ".manga-item", ".bsx", ".item", ".story-item",
                        "article", ".manga-card", ".title-row-card", ".title-grid__link"
                    ];
                    let cards = [];
                    for (const sel of selectors) {
                        const found = Array.from(document.querySelectorAll(sel));
                        if (found.length > 0) {
                            cards = found;
                            break;
                        }
                    }
                    const list = [];
                    for (const c of cards) {
                        const a = c.querySelector(".post-title a, h3 a, h4 a, .tt a, a[title]") || c.querySelector("a");
                        if (!a || !a.href) continue;
                        const title = a.innerText.trim() || a.title || "";
                        const img = c.querySelector("img");
                        const cover = img ? (img.dataset.src || img.dataset.lazySrc || img.src || "") : "";
                        const ch = c.querySelector(".chapter-item, .list-chapter, .epxs, .chapter, span.font-meta");
                        const chInfo = ch ? ch.innerText.trim() : "Disponível";
                        list.push({ title: title, url: a.href, cover_url: cover, chapter_info: chInfo });
                    }
                    return list;
                }""")

                for it in cards_data:
                    if it.get("title") and it.get("url"):
                        results.append({
                            "title": it["title"],
                            "url": it["url"],
                            "cover_url": it.get("cover_url", ""),
                            "chapter_info": it.get("chapter_info", "Disponível"),
                            "source_name": source.name,
                            "lang": source.lang or "pt-br"
                        })
            finally:
                browser.close()
    except Exception as e:
        logger.error("Erro no Playwright ao buscar catálogo de %s: %s", base_url, e)

    return results
