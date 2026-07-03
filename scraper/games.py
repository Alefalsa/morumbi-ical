"""
Scraper da agenda de jogos oficial do São Paulo FC.

Fonte: https://www.saopaulofc.net/calendario-de-jogos/
Esta é a página oficial do clube (mandante do MorumBIS) com o calendário
completo da temporada — passado e futuro — incluindo o local de cada
partida. Filtramos apenas as partidas cujo local é o MorumBIS.

A página não expõe uma API JSON pública conhecida, então fazemos parsing
de HTML. Como o site pode alterar nomes de classes CSS a qualquer momento,
o parser abaixo NÃO depende de seletores CSS específicos: ele localiza os
"cards" de jogo a partir do padrão de texto (data DD/MM/AAAA) e sobe na
árvore do DOM até achar o bloco que contém esse jogo, então extrai os
times (via texto e/ou atributo alt das imagens dos escudos), placar,
local e competição a partir desse bloco.

Se o site mudar MUITO a estrutura, rode `python -m scraper.games --debug`
para inspecionar quais blocos estão sendo detectados.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import date as date_cls
from typing import Optional

from bs4 import BeautifulSoup, Tag

from .utils import (
    fetch, get_session, is_morumbi_venue, parse_br_date, parse_br_time,
)

logger = logging.getLogger("morumbi_ical.games")

CALENDAR_URL = "https://www.saopaulofc.net/calendario-de-jogos/"

DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
COMPETITION_YEAR_RE = re.compile(r"^(?P<competicao>.+?)\s+(?P<ano>\d{4})\b")
SCORE_RE = re.compile(r"^\d{1,2}$")


@dataclass
class GameEvent:
    date: date_cls
    hour: Optional[int]
    minute: Optional[int]
    competition: str
    home_team: str
    away_team: str
    venue: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None

    @property
    def uid_key(self) -> str:
        return f"game-{self.date.isoformat()}-{self.home_team}-{self.away_team}".lower()

    @property
    def title(self) -> str:
        return f"{self.home_team} x {self.away_team}"


def _find_date_text_nodes(soup: BeautifulSoup):
    return soup.find_all(string=DATE_RE)


def _climb_to_card(date_node) -> Optional[Tag]:
    """Sobe na árvore a partir do nó de texto com a data até achar um
    container 'card' plausível: precisa conter pelo menos uma imagem
    (escudo) e não pode ser a página inteira."""
    node = date_node.parent
    levels = 0
    best = None
    while node is not None and levels < 8:
        if isinstance(node, Tag):
            imgs = node.find_all("img")
            if len(imgs) >= 1:
                best = node
            # Para de subir se já achamos um card com pelo menos 2 imagens
            # (os dois escudos) — geralmente é o menor container correto.
            if len(imgs) >= 2:
                return node
        node = node.parent
        levels += 1
    return best


def _lines_of(card: Tag) -> list[str]:
    text = card.get_text("\n")
    lines = [ln.strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln]


def _extract_competition_and_year(lines: list[str], date_line_idx: int) -> tuple[str, Optional[int]]:
    # A linha da competição normalmente é a primeira linha do card ou a
    # linha imediatamente anterior à data.
    for idx in range(date_line_idx, -1, -1):
        m = COMPETITION_YEAR_RE.match(lines[idx])
        if m:
            return m.group("competicao").strip(), int(m.group("ano"))
    return "Jogo", None


def _extract_venue(lines: list[str], date_line_idx: int) -> str:
    # O local geralmente aparece na primeira linha não vazia depois da
    # linha com a data/horário.
    for ln in lines[date_line_idx + 1:]:
        candidate = ln.lstrip("#").strip()
        if candidate and "x" != candidate.lower():
            return candidate
    return "A definir"


def _extract_teams_and_score(
    card: Tag, lines: list[str], exclude: Optional[set[str]] = None,
) -> tuple[str, str, Optional[int], Optional[int]]:
    # 1) Tenta achar via "TeamA <score> x <score> TeamB" no texto corrido.
    home = away = ""
    home_score = away_score = None
    exclude_norm = {e.strip().lower() for e in (exclude or set()) if e}

    def _is_real_name(ln: str) -> bool:
        return bool(ln) and ln.strip().lower() not in exclude_norm

    try:
        x_idx = next(i for i, ln in enumerate(lines) if ln.strip().lower() == "x")
    except StopIteration:
        x_idx = None

    if x_idx is not None:
        before = lines[max(0, x_idx - 2):x_idx]
        after = lines[x_idx + 1:x_idx + 3]

        before_scores = [b for b in before if SCORE_RE.match(b)]
        before_names = [b for b in before if not SCORE_RE.match(b) and _is_real_name(b)]
        after_scores = [a for a in after if SCORE_RE.match(a)]
        after_names = [a for a in after if not SCORE_RE.match(a) and _is_real_name(a)]

        if before_names:
            home = before_names[-1]
        if after_names:
            away = after_names[0]
        if before_scores:
            home_score = int(before_scores[-1])
        if after_scores:
            away_score = int(after_scores[0])

    # 2) Fallback / verificação cruzada: usa o atributo alt dos escudos,
    # que normalmente carrega o nome do time mesmo quando não há texto
    # visível (ex.: jogos já realizados, onde só aparece o placar).
    img_alts = [img.get("alt", "").strip() for img in card.find_all("img") if img.get("alt")]
    img_alts = [a for a in img_alts if a]
    if len(img_alts) >= 2:
        if not home:
            home = img_alts[0]
        if not away:
            away = img_alts[1]

    return home or "?", away or "?", home_score, away_score


def parse_calendar_html(html: str) -> list[GameEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[GameEvent] = []
    seen_keys = set()

    for date_node in _find_date_text_nodes(soup):
        card = _climb_to_card(date_node)
        if card is None:
            continue

        lines = _lines_of(card)
        try:
            date_line_idx = next(i for i, ln in enumerate(lines) if DATE_RE.search(ln))
        except StopIteration:
            continue

        date_line = lines[date_line_idx]
        d = parse_br_date(date_line)
        if d is None:
            continue
        hm = parse_br_time(date_line)

        competition, _year = _extract_competition_and_year(lines, date_line_idx)
        venue = _extract_venue(lines, date_line_idx)
        home, away, home_score, away_score = _extract_teams_and_score(
            card, lines, exclude={competition, venue, date_line}
        )

        ev = GameEvent(
            date=d,
            hour=hm[0] if hm else None,
            minute=hm[1] if hm else None,
            competition=competition,
            home_team=home,
            away_team=away,
            venue=venue,
            home_score=home_score,
            away_score=away_score,
        )

        if ev.uid_key in seen_keys:
            continue
        seen_keys.add(ev.uid_key)
        events.append(ev)

    return events


def get_morumbi_games() -> list[GameEvent]:
    """Busca e filtra apenas os jogos cujo local é o MorumBIS."""
    session = get_session()
    resp = fetch(CALENDAR_URL, session=session)
    all_games = parse_calendar_html(resp.text)
    logger.info("Total de jogos encontrados na página: %d", len(all_games))
    morumbi_games = [g for g in all_games if is_morumbi_venue(g.venue)]
    logger.info("Jogos no MorumBIS: %d", len(morumbi_games))
    return morumbi_games


def _main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                         help="Mostra todos os jogos encontrados (não só MorumBIS) em JSON")
    args = parser.parse_args()

    session = get_session()
    resp = fetch(CALENDAR_URL, session=session)
    games = parse_calendar_html(resp.text)

    if args.debug:
        print(json.dumps([asdict(g) | {"date": g.date.isoformat()} for g in games],
                          ensure_ascii=False, indent=2))
    else:
        morumbi = [g for g in games if is_morumbi_venue(g.venue)]
        for g in morumbi:
            print(f"{g.date} {g.hour:02d}:{g.minute:02d} - {g.title} ({g.competition}) @ {g.venue}"
                  if g.hour is not None else f"{g.date} - {g.title} ({g.competition}) @ {g.venue}")
        print(f"\nTotal no MorumBIS: {len(morumbi)} / {len(games)} jogos no calendário")


if __name__ == "__main__":
    _main()
