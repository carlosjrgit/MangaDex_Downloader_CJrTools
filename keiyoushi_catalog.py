#!/usr/bin/env python3
"""
keiyoushi_catalog.py - Gerenciador e indexador do repositório de extensões Keiyoushi (index.pb).
Decodifica o índice compilado em Protocol Buffers (gzipped) e fornece mapeamento
rápido de URLs/domínios para metadados de mais de 2.200 fontes e 1.400 extensões.
"""

import gzip
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("keiyoushi_catalog")


@dataclass
class KeiyoushiSource:
    id: int
    name: str
    lang: str
    base_url: str
    pkg: str
    version: str = ""
    apk_url: str = ""
    icon_url: str = ""
    flags: int = 0


class KeiyoushiCatalog:
    """Gerencia o carregamento sob demanda e consulta ao index.pb."""

    _instance: Optional["KeiyoushiCatalog"] = None

    def __init__(self, pb_path: Optional[str] = None):
        if pb_path:
            self.pb_path = Path(pb_path)
        else:
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass and (Path(meipass) / "index.pb").exists():
                self.pb_path = Path(meipass) / "index.pb"
            elif (Path(sys.executable).parent / "index.pb").exists():
                self.pb_path = Path(sys.executable).parent / "index.pb"
            else:
                self.pb_path = Path(__file__).resolve().parent / "index.pb"

        self.is_loaded: bool = False
        self.sources: List[KeiyoushiSource] = []
        self._domain_map: Dict[str, List[KeiyoushiSource]] = {}

    @classmethod
    def get_instance(cls) -> "KeiyoushiCatalog":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _decode_varint(buf: bytes, pos: int):
        res, shift = 0, 0
        while True:
            b = buf[pos]
            pos += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return res, pos

    @classmethod
    def _parse_proto_message(cls, buf: bytes) -> Dict[int, list]:
        p, fields = 0, {}
        b_len = len(buf)
        while p < b_len:
            tag, p = cls._decode_varint(buf, p)
            wire, fn = tag & 7, tag >> 3
            if wire == 0:
                val, p = cls._decode_varint(buf, p)
                fields.setdefault(fn, []).append(("varint", val))
            elif wire == 2:
                length, p = cls._decode_varint(buf, p)
                fields.setdefault(fn, []).append(("bytes", buf[p:p + length]))
                p += length
            elif wire == 1:
                fields.setdefault(fn, []).append(("64bit", buf[p:p + 8]))
                p += 8
            elif wire == 5:
                fields.setdefault(fn, []).append(("32bit", buf[p:p + 4]))
                p += 4
            else:
                break
        return fields

    def load(self, force_reload: bool = False) -> bool:
        """Carrega e decodifica o arquivo index.pb em memória."""
        if self.is_loaded and not force_reload:
            return True

        if not self.pb_path.exists():
            logger.warning("Arquivo de catálogo index.pb não encontrado em: %s", self.pb_path)
            return False

        try:
            with gzip.open(self.pb_path, "rb") as f:
                data = f.read()

            repo = self._parse_proto_message(data)
            ext_list_entries = repo.get(101, [])
            if not ext_list_entries:
                logger.warning("Nenhuma extensão encontrada no payload do index.pb")
                return False

            ext_list = ext_list_entries[0][1]
            p = 0
            e_len = len(ext_list)
            loaded_sources: List[KeiyoushiSource] = []
            domain_map: Dict[str, List[KeiyoushiSource]] = {}

            while p < e_len:
                tag, p = self._decode_varint(ext_list, p)
                length, p = self._decode_varint(ext_list, p)
                ext_data = self._parse_proto_message(ext_list[p:p + length])
                p += length

                pkg = ext_data.get(2, [(None, b"")])[0][1].decode("utf-8", errors="ignore")
                version = ext_data.get(6, [(None, b"")])[0][1].decode("utf-8", errors="ignore")
                flags = ext_data.get(7, [(None, 0)])[0][1]

                # Download URLs
                apk_url = ""
                icon_url = ""
                if 3 in ext_data and ext_data[3]:
                    f3_data = self._parse_proto_message(ext_data[3][0][1])
                    apk_url = f3_data.get(1, [(None, b"")])[0][1].decode("utf-8", errors="ignore")
                    icon_url = f3_data.get(2, [(None, b"")])[0][1].decode("utf-8", errors="ignore")

                # Fontes
                sources_entries = ext_data.get(8, [])
                for s in sources_entries:
                    sf = self._parse_proto_message(s[1])
                    s_id = sf.get(1, [(None, 0)])[0][1]
                    s_name = sf.get(2, [(None, b"")])[0][1].decode("utf-8", errors="ignore")
                    s_lang = sf.get(3, [(None, b"")])[0][1].decode("utf-8", errors="ignore")
                    s_url = sf.get(4, [(None, b"")])[0][1].decode("utf-8", errors="ignore")

                    if not s_url:
                        continue

                    source_obj = KeiyoushiSource(
                        id=s_id,
                        name=s_name,
                        lang=s_lang,
                        base_url=s_url.rstrip("/"),
                        pkg=pkg,
                        version=version,
                        apk_url=apk_url,
                        icon_url=icon_url,
                        flags=flags
                    )
                    loaded_sources.append(source_obj)

                    # Indexar por netloc (normalizado)
                    netloc = self.extract_domain(s_url)
                    if netloc:
                        domain_map.setdefault(netloc, []).append(source_obj)
                        # Indexar também sem subdomínio 'www.' se houver
                        if netloc.startswith("www."):
                            domain_map.setdefault(netloc[4:], []).append(source_obj)

            self.sources = loaded_sources
            self._domain_map = domain_map
            self.is_loaded = True
            logger.info("Catálogo Keiyoushi carregado com sucesso: %d fontes, %d domínios",
                        len(self.sources), len(self._domain_map))
            return True

        except Exception as e:
            logger.error("Falha ao decodificar index.pb: %s", e, exc_info=True)
            return False

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extrai o host/domínio normalizado de uma URL."""
        if not url:
            return ""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().strip()
            # Remover porta se houver
            return host.split(":")[0]
        except Exception:
            return ""

    def find_source_by_url(self, url: str) -> Optional[KeiyoushiSource]:
        """
        Retorna os metadados da fonte Keiyoushi correspondente à URL.
        Se houver múltiplas (ex: múltiplos idiomas), dá preferência a pt-BR, pt ou all.
        """
        if not self.is_loaded:
            self.load()

        domain = self.extract_domain(url)
        if not domain:
            return None

        candidates = self._domain_map.get(domain)
        if not candidates and domain.startswith("www."):
            candidates = self._domain_map.get(domain[4:])
        if not candidates:
            # Tentar correspondência parcial de subdomínio (ex: leitor.site.com -> site.com)
            parts = domain.split(".")
            if len(parts) > 2:
                parent_domain = ".".join(parts[-2:])
                candidates = self._domain_map.get(parent_domain)

        if not candidates:
            return None

        # Priorizar português se existir
        for s in candidates:
            if s.lang.lower() in ("pt-br", "pt"):
                return s
        for s in candidates:
            if s.lang.lower() in ("all", "en"):
                return s
        return candidates[0]

    def search(self, query: str = "", lang: Optional[str] = None) -> List[KeiyoushiSource]:
        """Pesquisa fontes por texto (nome, url, pkg) e opcionalmente idioma."""
        if not self.is_loaded:
            self.load()

        q = query.lower().strip()
        results = []
        for s in self.sources:
            if lang and s.lang.lower() != lang.lower():
                continue
            if not q or q in s.name.lower() or q in s.base_url.lower() or q in s.pkg.lower():
                results.append(s)
        return results

    def get_supported_domains(self) -> List[str]:
        """Retorna lista ordenada de todos os domínios mapeados."""
        if not self.is_loaded:
            self.load()
        return sorted(list(self._domain_map.keys()))


# Instância global facilitadora
catalog = KeiyoushiCatalog.get_instance()
