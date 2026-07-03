"""Gera o arquivo .ics final a partir dos eventos coletados."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from icalendar import Calendar, Event

from .games import GameEvent
from .shows import ShowEvent

logger = logging.getLogger("morumbi_ical.ics")

CAL_NAME = "MorumBIS — Jogos e Eventos"
CAL_DESC = (
    "Agenda do estádio MorumBIS (São Paulo FC). Jogos: fonte oficial "
    "(saopaulofc.net/calendario-de-jogos). Shows/eventos: extraídos de "
    "notícias oficiais do clube de forma automática — datas marcadas como "
    "'a confirmar' podem estar incorretas, sempre confira o link da fonte."
)

DEFAULT_GAME_DURATION_HOURS = 2.5
TZID = "America/Sao_Paulo"


def _uid(key: str) -> str:
    return f"{key}@morumbi-ical"


def _add_game_event(cal: Calendar, g: GameEvent) -> None:
    ev = Event()
    ev.add("uid", _uid(g.uid_key))
    ev.add("summary", f"⚽ {g.title} — {g.competition}")

    if g.hour is not None:
        start = datetime(g.date.year, g.date.month, g.date.day, g.hour, g.minute)
        ev.add("dtstart", start, parameters={"TZID": TZID})
        ev.add("dtend", start + timedelta(hours=DEFAULT_GAME_DURATION_HOURS),
               parameters={"TZID": TZID})
    else:
        # Horário "a definir": evento de dia inteiro pra não inventar hora.
        ev.add("dtstart", g.date)
        ev.add("dtend", g.date + timedelta(days=1))

    desc_lines = [f"Competição: {g.competition}", f"Local: {g.venue}"]
    if g.home_score is not None and g.away_score is not None:
        desc_lines.append(f"Placar: {g.home_score} x {g.away_score}")
    ev.add("description", "\n".join(desc_lines))
    ev.add("location", "Estádio MorumBIS, Praça Roberto Gomes Pedrosa, 1, São Paulo - SP")
    ev.add("status", "CONFIRMED")
    cal.add_component(ev)


def _add_show_event(cal: Calendar, s: ShowEvent) -> None:
    ev = Event()
    ev.add("uid", _uid(s.uid_key))

    confidence_emoji = {"alta": "🎤", "media": "🎤❓", "baixa": "🎤❓❓"}.get(s.confidence, "🎤❓")
    ev.add("summary", f"{confidence_emoji} {s.title} (a confirmar)")
    ev.add("dtstart", s.date)
    ev.add("dtend", s.date + timedelta(days=1))
    ev.add("description",
           f"Evento extraído automaticamente de notícia oficial do SPFC.\n"
           f"Confiança da extração: {s.confidence}.\n"
           f"Confirme a data em: {s.source_url}")
    ev.add("location", "Estádio MorumBIS, Praça Roberto Gomes Pedrosa, 1, São Paulo - SP")
    ev.add("status", "TENTATIVE")
    cal.add_component(ev)


def build_calendar(games: Iterable[GameEvent], shows: Iterable[ShowEvent]) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//morumbi-ical//github.com//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", CAL_NAME)
    cal.add("x-wr-caldesc", CAL_DESC)
    cal.add("x-wr-timezone", TZID)
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")

    n_games = 0
    for g in games:
        _add_game_event(cal, g)
        n_games += 1

    n_shows = 0
    for s in shows:
        _add_show_event(cal, s)
        n_shows += 1

    logger.info("ICS montado com %d jogos e %d eventos/shows (tentativos).", n_games, n_shows)
    return cal


def write_ics(cal: Calendar, path: str) -> None:
    with open(path, "wb") as f:
        f.write(cal.to_ical())
