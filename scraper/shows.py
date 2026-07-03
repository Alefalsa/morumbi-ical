"""
Scraper (best-effort) de shows/eventos não-futebolísticos no MorumBIS.

Fonte: https://www.saopaulofc.net/categoria/eventos/  (notícias oficiais do clube)

IMPORTANTE — leia antes de confiar 100% nisso:
O site oficial NÃO publica uma agenda futura estruturada de shows (a única
tabela estruturada que existe é histórica, de shows que já aconteceram).
O que temos de "oficial" sobre shows futuros são posts de notícia em texto
livre, nem sempre com data explícita e clara.

Esse módulo varre essas notícias e tenta extrair datas usando `dateparser`
em português. Quando encontra uma data plausível, cria um evento marcado
como TENTATIVE (provisório) no calendário, com link para a notícia
original — para você confirmar manualmente. É menos preciso que o scraper
de jogos, de propósito: preferimos errar pra "menos eventos automáticos"
do que inventar datas.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date as date_cls, timedelta
from typing import Optional

from bs4 import BeautifulSoup
import dateparser
from dateparser.search import search_dates

from .utils import fetch, get_session

logger = logging.getLogger("morumbi_ical.shows")

EVENTOS_BASE = "https://www.saopaulofc.net/categoria/eventos/"

# Palavras que aumentam a confiança de que o texto fala de um show/evento
# futuro (e não, por exemplo, de uma homenagem ou notícia institucional).
EVENT_HINT_WORDS = (
    "show", "shows", "ingresso", "ingressos", "turnê", "tour",
    "festival", "apresenta", "apresentação", "se apresenta",
    "venda de ingressos", "pré-venda",
)

MAX_PAGES_DEFAULT = 3
MAX_DATES_PER_POST = 3


@dataclass
class ShowEvent:
    date: date_cls
    title: str
    source_url: str
    confidence: str  # "alta" | "media" | "baixa"

    @property
    def uid_key(self) -> str:
        return f"show-{self.date.isoformat()}-{self.title}".lower()


def _post_links_from_listing(html: str) -> list[tuple[str, str]]:
    """Retorna [(titulo, url)] dos posts listados em uma página de categoria."""
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 8:
            continue
        if "/categoria/" in href or "saopaulofc.net" not in href:
            continue
        if href in seen:
            continue
        # Heurística: posts de notícia ficam direto sob o domínio,
        # sem mais um nível de "/categoria/".
        seen.add(href)
        results.append((title, href))
    return results


def _fetch_listing_pages(session, max_pages: int) -> list[tuple[str, str]]:
    all_posts: list[tuple[str, str]] = []
    seen_urls = set()
    for page in range(1, max_pages + 1):
        url = EVENTOS_BASE if page == 1 else f"{EVENTOS_BASE}page/{page}/"
        try:
            resp = fetch(url, session=session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não consegui buscar página %d de eventos: %s", page, exc)
            break
        posts = _post_links_from_listing(resp.text)
        new_posts = [p for p in posts if p[1] not in seen_urls]
        if not new_posts:
            break
        for p in new_posts:
            seen_urls.add(p[1])
        all_posts.extend(new_posts)
    return all_posts


def _article_text(session, url: str) -> str:
    resp = fetch(url, session=session)
    soup = BeautifulSoup(resp.text, "lxml")
    # Remove menus/rodapé óbvios para reduzir ruído na busca de datas.
    for tag in soup.find_all(["nav", "footer", "header", "script", "style"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup
    return main.get_text(" ", strip=True)


def _confidence_for(text_lower: str) -> str:
    hint_count = sum(1 for w in EVENT_HINT_WORDS if w in text_lower)
    if hint_count >= 3:
        return "alta"
    if hint_count >= 1:
        return "media"
    return "baixa"


_DIA_PREFIX_RE = re.compile(r"\b(no\s+|nos\s+)?dias?\s+(\d{1,2})\b", re.IGNORECASE)
_NOISE_SNIPPETS = {
    "a", "o", "do", "da", "de", "no", "em", "e", "as", "os", "um", "uma",
}


_PURE_TIME_RE = re.compile(r"^\d{1,2}h\d{0,2}$", re.IGNORECASE)


def _preprocess_for_dateparser(text: str) -> str:
    """dateparser.search tem um bug conhecido: a palavra 'dia'/'dias' antes
    de um número (comum em PT-BR: 'no dia 25 de abril') faz a busca de
    datas falhar silenciosamente. Removemos essa palavra antes de buscar."""
    return _DIA_PREFIX_RE.sub(r"\2", text)


def _extract_dates(title: str, body: str, published_hint: Optional[datetime]) -> list[date_cls]:
    text = _preprocess_for_dateparser(f"{title}. {body}")
    settings = {
        "PREFER_DATES_FROM": "future",
        "STRICT_PARSING": False,
        "RELATIVE_BASE": published_hint or datetime.now(),
    }
    try:
        found = search_dates(text, languages=["pt"], settings=settings)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Falha ao extrair datas de texto: %s", exc)
        return []
    if not found:
        return []

    out = []
    for snippet, dt in found:
        snippet_norm = snippet.strip().lower()
        # Descarta "datas" extraídas de palavras curtas/comuns (falso positivo
        # típico do dateparser quando ele tenta interpretar uma palavra
        # qualquer como expressão relativa de data).
        if len(snippet_norm) < 3 or snippet_norm in _NOISE_SNIPPETS:
            continue
        if _PURE_TIME_RE.match(snippet_norm):
            continue
        d = dt.date() if isinstance(dt, datetime) else dt
        out.append(d)

    dedup = sorted(set(out))
    return dedup[:MAX_DATES_PER_POST]


def get_show_candidates(
    max_pages: int = MAX_PAGES_DEFAULT,
    min_date: Optional[date_cls] = None,
) -> list[ShowEvent]:
    """Varre notícias de eventos e retorna candidatos a evento (TENTATIVE).

    `min_date`: ignora datas extraídas anteriores a essa data (default: hoje).
    """
    session = get_session()
    min_date = min_date or date_cls.today()

    posts = _fetch_listing_pages(session, max_pages=max_pages)
    logger.info("Posts de 'Eventos' encontrados: %d", len(posts))

    candidates: list[ShowEvent] = []
    seen_keys = set()

    for title, url in posts:
        try:
            body = _article_text(session, url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao buscar artigo %s: %s", url, exc)
            continue

        text_lower = f"{title} {body}".lower()
        if not any(w in text_lower for w in EVENT_HINT_WORDS):
            # Sem nenhuma palavra-chave de show/evento: ignora (provavelmente
            # institucional, aniversário do clube, etc.)
            continue

        dates = _extract_dates(title, body, published_hint=None)
        confidence = _confidence_for(text_lower)

        for d in dates:
            if d < min_date:
                continue
            ev = ShowEvent(date=d, title=title, source_url=url, confidence=confidence)
            if ev.uid_key in seen_keys:
                continue
            seen_keys.add(ev.uid_key)
            candidates.append(ev)

    candidates.sort(key=lambda e: e.date)
    return candidates


def _main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=MAX_PAGES_DEFAULT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    candidates = get_show_candidates(max_pages=args.pages)
    if args.debug:
        print(json.dumps(
            [asdict(c) | {"date": c.date.isoformat()} for c in candidates],
            ensure_ascii=False, indent=2,
        ))
    else:
        for c in candidates:
            print(f"[{c.confidence}] {c.date} - {c.title}\n    {c.source_url}")
        print(f"\nTotal de candidatos: {len(candidates)}")


if __name__ == "__main__":
    _main()
