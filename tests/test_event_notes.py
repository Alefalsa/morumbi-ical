import unittest
from datetime import date

from scraper.ics_writer import build_calendar
from scraper.shows import ShowEvent
from scraper.ticketed_events import get_manually_curated_events


class EventNotesTest(unittest.TestCase):
    def test_bts_events_keep_g1_traffic_warning(self) -> None:
        events = get_manually_curated_events(min_date=date(2026, 10, 19))

        self.assertEqual(3, len(events))
        self.assertTrue(all(event.source == "G1" for event in events))
        self.assertTrue(all("g1.globo.com" in event.source_url for event in events))
        self.assertTrue(all("bloqueios de ruas" in (event.note or "") for event in events))

    def test_show_description_includes_source_and_note(self) -> None:
        show = ShowEvent(
            date=date(2026, 10, 28),
            title="BTS",
            source_url="https://g1.globo.com/example",
            confidence="alta",
            source_name="G1",
            note="ALERTA DE TRÂNSITO: haverá bloqueios de ruas.",
        )

        calendar = build_calendar([], [show])
        event = calendar.walk("VEVENT")[0]
        description = str(event["description"])

        self.assertIn("Fonte: G1.", description)
        self.assertIn("ALERTA DE TRÂNSITO", description)
        self.assertIn("https://g1.globo.com/example", description)


if __name__ == "__main__":
    unittest.main()
