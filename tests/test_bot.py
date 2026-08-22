from __future__ import annotations

import unittest
from datetime import datetime, timezone

import bot


class PostingHoursTests(unittest.TestCase):
    def test_start_boundary_is_allowed(self) -> None:
        self.assertTrue(bot.is_within_posting_hours(datetime(2026, 1, 1, 9, 0)))

    def test_end_boundary_is_quiet(self) -> None:
        self.assertFalse(bot.is_within_posting_hours(datetime(2026, 1, 1, 21, 0)))

    def test_aware_datetime_is_converted_to_eastern(self) -> None:
        # 14:00 UTC is 09:00 Eastern on this winter date.
        self.assertTrue(
            bot.is_within_posting_hours(
                datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
            )
        )


class QuoteLibraryTests(unittest.TestCase):
    def test_quote_library_loads(self) -> None:
        quotes = bot.load_quotes()
        self.assertGreaterEqual(len(quotes), 24)
        self.assertTrue(all(item["quote"] for item in quotes))


if __name__ == "__main__":
    unittest.main()
