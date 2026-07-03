"""Utilitários compartilhados pelos scrapers."""
from __future__ import annotations

import re
import time
import logging
from datetime import datetime, date
from typing import Optional

import requests

logger = logging.getLogger("morumbi_ical")

USER_AGENT = (
    "Mozilla/5.0 (compatible; MorumbiICalBot/1.0; "
    "+https://github.com/) Python-requests"
)

# Nomes/grafias que o estádio (e o clube) já usaram para o mesmo lugar.
# Usado para filtrar jogos que aconteceram no Morumbi/MorumBIS, mesmo que
# o site mude a grafia exata ao longo do tempo.
VENUE_ALIASES = (
    "morumbis",
    "morumbi",
    "cicero pompeu de toledo",
    "cícero pompeu de toledo",
)


def get_session() -> requests.Session:
    """Sessão HTTP com retries simples e User-Agent de navegador."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch(url: str, session: Optional[requests.Session] = None,
          retries: int = 3, timeout: int = 20) -> requests.Response:
    """GET com retry/backoff simples. Lança a última exceção se tudo falhar."""
    session = session or get_session()
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:  # noqa: PERF203
            last_exc = exc
            logger.warning("Falha ao buscar %s (tentativa %d/%d): %s",
                            url, attempt, retries, exc)
            time.sleep(2 * attempt)
    assert last_exc is not None
    raise last_exc


def is_morumbi_venue(venue_text: str) -> bool:
    """Verifica se um texto de local de jogo se refere ao Morumbi/MorumBIS."""
    if not venue_text:
        return False
    normalized = venue_text.strip().lower()
    return any(alias in normalized for alias in VENUE_ALIASES)


_BR_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_BR_TIME_RE = re.compile(r"(\d{2}):(\d{2})")


def parse_br_date(text: str) -> Optional[date]:
    """Extrai uma data DD/MM/AAAA de um texto qualquer."""
    m = _BR_DATE_RE.search(text)
    if not m:
        return None
    day, month, year = (int(x) for x in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_br_time(text: str) -> Optional[tuple[int, int]]:
    """Extrai um horário HH:MM de um texto qualquer."""
    m = _BR_TIME_RE.search(text)
    if not m:
        return None
    hour, minute = (int(x) for x in m.groups())
    return hour, minute


def combine_date_time(d: date, hm: Optional[tuple[int, int]]) -> datetime:
    if hm is None:
        return datetime(d.year, d.month, d.day, 0, 0)
    return datetime(d.year, d.month, d.day, hm[0], hm[1])
