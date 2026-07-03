#!/usr/bin/env python3
"""
Ponto de entrada principal: roda os scrapers de jogos e shows e gera o
arquivo morumbis.ics na raiz do repositório.

Uso:
    python build_ics.py
    python build_ics.py --no-shows          # só jogos (mais confiável)
    python build_ics.py --show-pages 5      # varre mais páginas de notícias
    python build_ics.py --output caminho.ics
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from scraper.games import get_morumbi_games
from scraper.shows import get_show_candidates, MAX_PAGES_DEFAULT
from scraper.ics_writer import build_calendar, write_ics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("morumbi_ical")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="morumbis.ics",
                         help="Caminho do arquivo .ics gerado (default: morumbis.ics)")
    parser.add_argument("--no-shows", action="store_true",
                         help="Não inclui shows/eventos extraídos de notícias (só jogos)")
    parser.add_argument("--show-pages", type=int, default=MAX_PAGES_DEFAULT,
                         help="Quantas páginas de /categoria/eventos/ varrer")
    parser.add_argument("--include-past-days", type=int, default=2,
                         help="Quantos dias no passado ainda incluir no calendário")
    args = parser.parse_args()

    min_date = date.today() - timedelta(days=args.include_past_days)

    try:
        games = get_morumbi_games()
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao buscar jogos: %s", exc)
        games = []

    games = [g for g in games if g.date >= min_date]

    shows = []
    if not args.no_shows:
        try:
            shows = get_show_candidates(max_pages=args.show_pages, min_date=min_date)
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao buscar shows/eventos: %s", exc)
            shows = []

    if not games and not shows:
        logger.error(
            "Nenhum jogo nem show encontrado. Isso provavelmente indica que "
            "o site oficial mudou de estrutura e o scraper precisa de ajuste "
            "(veja README.md, seção 'Se o site mudar'). Mantendo o .ics "
            "anterior sem sobrescrever para não publicar um calendário vazio."
        )
        return 1

    cal = build_calendar(games, shows)
    write_ics(cal, args.output)
    logger.info("Arquivo gerado: %s (%d jogos, %d shows/eventos)",
                args.output, len(games), len(shows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
