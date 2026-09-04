#!/usr/bin/env python3
"""
MangaLivre Scraper & Downloader
Módulo de extração e download para mangalivre.blog
"""

import html
import logging
import os
import re
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from manga_core import clean_filename, safe_path_join

logger = logging.getLogger("mangalivre-dl")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://mangalivre.blog/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

DEFAULT_WORKERS = 4


def create_session() -> requests.Session:
    """Cria uma sessão requests com retries, pooling e headers de navegador."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.timeout = (10, 30)
    return session


def is_mangalivre_url(url: str) -> bool:
    """Verifica se a URL fornecida pertence ao MangaLivre."""
    return "mangalivre" in url.lower()


def pad_filename(filename: str) -> str:
    """Adiciona preenchimento de zeros à numeração para ordenação correta."""
    return re.sub(r'(\d+)', lambda m: m.group(1).zfill(3), filename)


def extract_chapter_number(text_or_url: str) -> str:
    """Extrai o número ou identificador do capítulo a partir do texto ou URL."""
    # Ex: '...-capitulo-415/' ou 'Capítulo 415.1'
    match = re.search(r'capitulo-(\d+(?:[\.-]\d+)?)', text_or_url, re.IGNORECASE)
    if match:
        return match.group(1).replace('-', '.')

    match_num = re.search(r'(\d+(?:\.\d+)?)', text_or_url)
    if match_num:
        return match_num.group(1)

    return "0"


def get_manga_info(url: str, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """
    Raspa a página do mangá no MangaLivre e retorna:
    - title: Título do mangá
    - cover: URL da capa
    - chapters: Lista de capítulos [{'title': str, 'chapter': str, 'url': str}] ordenados do menor para o maior.
    """
    if session is None:
        session = create_session()

    # Se o usuário passou link de capítulo em vez do mangá, tenta normalizar
    if "/capitulo/" in url:
        # Ex: https://mangalivre.blog/capitulo/eleceed-capitulo-415/ -> https://mangalivre.blog/manga/eleceed/
        slug_match = re.search(r'/capitulo/([a-zA-Z0-9_-]+?)-capitulo-', url)
        if slug_match:
            url = f"https://mangalivre.blog/manga/{slug_match.group(1)}/"

    r = session.get(url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Extrai o título
    title = None
    for h in soup.find_all("h1"):
        classes = h.get("class", [])
        parent_classes = h.parent.get("class", []) if h.parent else []
        if "site-title" not in classes and "site-branding" not in parent_classes:
            title = h.get_text(strip=True)
            break

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].split("-")[0].strip()
        else:
            title = soup.title.string.split("-")[0].strip() if soup.title else "Manga Desconhecido"

    title = html.unescape(title)

    # Extrai a capa
    cover = ""
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        cover = og_img["content"]
    else:
        post_img = soup.find("img", class_="wp-post-image")
        if post_img:
            cover = post_img.get("src") or ""

    # Extrai todos os capítulos
    chapters_map: Dict[str, Dict[str, Any]] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/capitulo/" in href:
            # Normalizar URL
            href = href.split("?")[0].rstrip("/") + "/"
            if href not in chapters_map:
                text = a.get_text(strip=True)
                cap_num = extract_chapter_number(href)
                display_name = text if text and "ler" not in text.lower() and "iniciar" not in text.lower() else f"Capítulo {cap_num}"
                chapters_map[href] = {
                    "id": href,
                    "title": display_name,
                    "chapter": cap_num,
                    "url": href,
                    "attributes": {
                        "chapter": cap_num,
                        "title": display_name,
                        "createdAt": ""
                    }
                }

    # Ordenar capítulos numericamente (ascendente)
    def sort_key(ch: Dict[str, Any]) -> float:
        try:
            return float(ch["chapter"])
        except ValueError:
            return 9999.0

    chapters = sorted(chapters_map.values(), key=sort_key)

    return {
        "title": title,
        "cover": cover,
        "chapters": chapters
    }


def get_chapter_images(chapter_url: str, session: Optional[requests.Session] = None) -> List[str]:
    """
    Acessa a página do capítulo no MangaLivre e extrai todas as URLs de imagens do leitor.
    """
    if session is None:
        session = create_session()

    r = session.get(chapter_url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    images: List[str] = []
    seen = set()

    for img in soup.find_all("img"):
        classes = img.get("class", [])
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue

        # Filtra imagens do leitor
        is_reader_img = False
        if "chapter-image" in classes:
            is_reader_img = True
        elif "/uploads/" in src:
            # Exclui avatares, bandeiras, ícones e emojis
            ignored_keywords = ["flagcdn", "cropped", "removebg", "emoji", "avatar", "discord", "logo", "banner"]
            if not any(k in src.lower() for k in ignored_keywords):
                is_reader_img = True

        if is_reader_img and src not in seen:
            seen.add(src)
            images.append(src)

    return images


def download_page(url: str, page_num: int, dest_folder: str, session: requests.Session) -> bool:
    """Baixa uma única página de imagem salvando na pasta de destino com retry."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            logger.error("URL de página rejeitada (não remota ou inválida): %s", url)
            return False
    except Exception:
        return False

    clean_url = url.split("?")[0]
    ext = os.path.splitext(clean_url)[1] or ".jpg"
    if len(ext) > 5 or not ext.startswith("."):
        ext = ".jpg"
    dest_filename = pad_filename(f"{page_num}{ext}")
    try:
        outfile = safe_path_join(dest_folder, dest_filename)
    except ValueError as e:
        logger.error("Caminho de arquivo inválido: %s", e)
        return False

    if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
        return True

    for attempt in range(3):
        try:
            r = session.get(url, timeout=(10, 30))
            if r.status_code == 200 and len(r.content) > 0:
                with open(outfile, "wb") as f:
                    f.write(r.content)
                return True
            time.sleep(1 * (attempt + 1))
        except requests.RequestException:
            time.sleep(1 * (attempt + 1))

    return False


def download_chapter(
    chapter: Dict[str, Any],
    title: str,
    session: requests.Session,
    cbz: bool = True,
    outdir: str = "download",
    max_workers: int = DEFAULT_WORKERS,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Realiza o download de todas as páginas de um capítulo e empacota em CBZ.
    """
    chap_num = chapter.get("chapter") or "0"
    chap_url = chapter.get("url") or chapter.get("id")

    logger.info("Buscando imagens do Capítulo %s...", chap_num)
    images = get_chapter_images(chap_url, session)
    if not images:
        logger.warning("Nenhuma imagem encontrada para o Capítulo %s (%s).", chap_num, chap_url)
        return False

    safe_title = clean_filename(title)
    safe_chap_num = clean_filename(f"Capítulo {chap_num}")
    try:
        manga_folder = safe_path_join(outdir, safe_title)
        chap_folder = safe_path_join(manga_folder, safe_chap_num)
        os.makedirs(chap_folder, exist_ok=True)
    except ValueError as e:
        logger.error("Caminho de diretório inválido: %s", e)
        return False

    # Verificar se todas as páginas já existem
    all_exist = True
    for page_num, img_url in enumerate(images, 1):
        clean_url = img_url.split("?")[0]
        ext = os.path.splitext(clean_url)[1] or ".jpg"
        if len(ext) > 5 or not ext.startswith("."):
            ext = ".jpg"
        dest_filename = pad_filename(f"{page_num}{ext}")
        try:
            expected_file = safe_path_join(chap_folder, dest_filename)
        except ValueError:
            all_exist = False
            break
        if not os.path.exists(expected_file) or os.path.getsize(expected_file) == 0:
            all_exist = False
            break

    if not all_exist:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for idx, img_url in enumerate(images, 1):
                if is_cancelled and is_cancelled():
                    return False
                future = executor.submit(download_page, img_url, idx, chap_folder, session)
                futures[future] = idx

            completed_count = 0
            for future in as_completed(futures):
                if is_cancelled and is_cancelled():
                    return False
                idx = futures[future]
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, len(images))
                try:
                    if not future.result():
                        logger.warning("Falha no download da página %d do capítulo %s.", idx, chap_num)
                except Exception as e:
                    logger.error("Erro na página %d: %s", idx, e)

    # Empacotar em CBZ
    if cbz:
        try:
            zip_name = safe_path_join(manga_folder, f"{safe_title} - {safe_chap_num} [MangaLivre].cbz")
            with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as myzip:
                for root, _, files in os.walk(chap_folder):
                    for file in sorted(files):
                        path = os.path.join(root, file)
                        myzip.write(path, os.path.basename(path))
            shutil.rmtree(chap_folder, ignore_errors=True)
            logger.info("Capítulo %s empacotado em CBZ com sucesso!", chap_num)
        except Exception as e:
            logger.error("Erro ao empacotar CBZ: %s", e)
            return False

    return True


# ----------------------------------------------------------------------
# Execução direta via CLI para testes
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if len(sys.argv) < 2:
        print("Uso: python mangalivre.py <URL_DO_MANGA>")
        sys.exit(1)

    manga_url = sys.argv[1]
    sess = create_session()
    print(f"Obtendo informações de: {manga_url}")
    info = get_manga_info(manga_url, sess)
    print(f"Título: {info['title']}")
    print(f"Total de capítulos: {len(info['chapters'])}")

    if info['chapters']:
        latest = info['chapters'][-1]
        print(f"\nBaixando capítulo mais recente: {latest['title']} ({latest['url']})")
        download_chapter(latest, info['title'], sess, cbz=True, outdir="download")
        print("\nDownload concluído!")
