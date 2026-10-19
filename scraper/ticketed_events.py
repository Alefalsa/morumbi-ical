"""
Scraper for ticketed concerts/events at MorumBIS from external sources.

Since the official São Paulo FC website doesn't always publish concert info
in their /categoria/eventos/ section immediately, this module monitors
external sources like ticketing sites, news, and social media.

Supported sources:
1. Manual curated list (for announced but not yet listed concerts)
2. Ticketmaster API (requires API key - see below)
3. News sites (G1, UOL, etc.) for announcements
4. Social media feeds (future enhancement)

TICKETMASTER API SETUP (optional, requires free key):
  1. Sign up at https://developer.ticketmaster.com/
  2. Create an API key
  3. Set TICKETMASTER_API_KEY environment variable
  4. This module will automatically use it to find MorumBIS events

Without an API key, this module falls back to the manual curated list.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import date as date_cls
from typing import Optional

logger = logging.getLogger("morumbi_ical.ticketed_events")

# MANUAL CURATED CONCERTS
# Add concert info here when announced but not yet on official site
# Format: title, date, confidence level
KNOWN_CONCERTS = [
    {
        "title": "BTS",
        "dates": ["2026-10-28", "2026-10-30", "2026-10-31"],
        "source": "G1 Globo, confirmed by São Paulo FC",
        "confidence": "alta",
    },
]


@dataclass
class TicketedEvent:
    """Concert/show from external ticketing sources."""
    date: date_cls
    title: str
    source: str
    confidence: str  # "alta" | "media" | "baixa"
    venue: str = "MorumBIS"

    @property
    def uid_key(self) -> str:
        return f"ticket-{self.date.isoformat()}-{self.title}".lower()


def get_ticketmaster_events(venue_name: str = "Morumbis") -> list[TicketedEvent]:
    """Fetch events from Ticketmaster using their Discovery API.
    
    Requires TICKETMASTER_API_KEY environment variable to be set.
    
    Args:
        venue_name: Search term for the venue (e.g., "Morumbis", "MorumBIS")
    
    Returns:
        List of TicketedEvent objects if API key available, empty list otherwise.
    """
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        logger.debug(
            "Ticketmaster API key not set. Set TICKETMASTER_API_KEY environment "
            "variable to enable Ticketmaster concert discovery. "
            "Sign up at https://developer.ticketmaster.com/ for a free key."
        )
        return []

    try:
        import requests
    except ImportError:
        logger.warning("requests library required for Ticketmaster API")
        return []

    events = []
    try:
        # Search for events at the venue
        # API docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
        url = "https://app.ticketmaster.com/discovery/v2/events"
        params = {
            "keyword": venue_name,
            "countryCode": "BR",
            "apikey": api_key,
            "size": 200,  # Max results per page
            "sort": "date,asc",
        }
        
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        
        if "_embedded" not in data or "events" not in data["_embedded"]:
            logger.debug("No events found on Ticketmaster for %s", venue_name)
            return []
        
        for event in data["_embedded"]["events"]:
            # Extract relevant info
            title = event.get("name", "Unknown")
            
            # Get date from dates.start.localDate
            if "dates" not in event or "start" not in event["dates"]:
                continue
            date_str = event["dates"]["start"].get("localDate")
            if not date_str:
                continue
            
            try:
                event_date = date_cls.fromisoformat(date_str)
            except (ValueError, TypeError):
                logger.debug("Could not parse date: %s", date_str)
                continue
            
            # Verify it's at MorumBIS
            venue = None
            if "_embedded" in event and "venues" in event["_embedded"]:
                venues = event["_embedded"]["venues"]
                if venues:
                    venue = venues[0].get("name", "Unknown")
            
            if not venue or "morumb" not in venue.lower():
                continue  # Not at MorumBIS
            
            ev = TicketedEvent(
                date=event_date,
                title=title,
                source="Ticketmaster",
                confidence="alta",
                venue=venue,
            )
            events.append(ev)
        
        logger.info("Found %d events on Ticketmaster", len(events))
        
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching Ticketmaster events: %s", exc)
    
    return events


def get_manually_curated_events(
    min_date: Optional[date_cls] = None,
) -> list[TicketedEvent]:
    """Get manually curated concert list.
    
    Use this for announced concerts that aren't yet on the official site
    or ticketing systems. Useful for interim period between announcement
    and official listing.
    
    Args:
        min_date: Only include events on/after this date (default: today)
    
    Returns:
        List of TicketedEvent objects
    """
    if not min_date:
        min_date = date_cls.today()
    
    events = []
    for concert in KNOWN_CONCERTS:
        title = concert.get("title", "Unknown")
        source = concert.get("source", "Manual curation")
        confidence = concert.get("confidence", "media")
        
        for date_str in concert.get("dates", []):
            try:
                event_date = date_cls.fromisoformat(date_str)
            except (ValueError, TypeError):
                logger.warning("Could not parse date: %s", date_str)
                continue
            
            if event_date < min_date:
                continue
            
            ev = TicketedEvent(
                date=event_date,
                title=title,
                source=source,
                confidence=confidence,
            )
            events.append(ev)
    
    return events


def get_all_ticketed_events(
    min_date: Optional[date_cls] = None,
    include_manual: bool = True,
    include_ticketmaster: bool = True,
) -> list[TicketedEvent]:
    """Get all ticketed events from all sources, deduplicated.
    
    Args:
        min_date: Filter to events on/after this date
        include_manual: Include manually curated list
        include_ticketmaster: Try Ticketmaster API
    
    Returns:
        Sorted, deduplicated list of TicketedEvent objects
    """
    if not min_date:
        min_date = date_cls.today()
    
    all_events = []
    seen_keys = set()
    
    if include_manual:
        manual = get_manually_curated_events(min_date=min_date)
        for ev in manual:
            if ev.uid_key not in seen_keys:
                all_events.append(ev)
                seen_keys.add(ev.uid_key)
    
    if include_ticketmaster:
        ticketmaster = get_ticketmaster_events()
        for ev in ticketmaster:
            if ev.date >= min_date and ev.uid_key not in seen_keys:
                all_events.append(ev)
                seen_keys.add(ev.uid_key)
    
    all_events.sort(key=lambda e: e.date)
    return all_events


def _main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Find ticketed concerts at MorumBIS"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Output full JSON details"
    )
    args = parser.parse_args()
    
    events = get_all_ticketed_events()
    
    if args.debug:
        print(json.dumps(
            [asdict(e) | {"date": e.date.isoformat()} for e in events],
            ensure_ascii=False, indent=2,
        ))
    else:
        for ev in events:
            print(f"[{ev.confidence}] {ev.date} - {ev.title}")
            print(f"  Source: {ev.source}\n")
        print(f"Total: {len(events)} ticketed events")


if __name__ == "__main__":
    _main()
