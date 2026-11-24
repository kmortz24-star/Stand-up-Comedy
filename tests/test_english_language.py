"""Offline regression tests for the whole-addon English-language policy."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from build_catalogs import categories, build
from fetch_tmdb import backfill_original_languages
from language_filters import (movie_allowed, performer_non_english_evidence,
                              youtube_allowed)
from tv_catalogs import build_tv_series
from youtube_catalogs import classify

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 24)


def movie(id, name, title, language=None, event=False):
    return {"id": id, "tmdb_id": int(id.split(':')[-1]), "performer": name,
            "title": title, "release_date": "2023-01-01", "original_language": language,
            "tags": ["event"] if event else [], "vote_average": 8.5,
            "vote_count": 50, "popularity": 2}


class EnglishOnlyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config.json").read_text())
        self.config["enable_youtube_preview_catalogs"] = False
        self.config["enable_tv_series_catalog"] = False
        self.config["alphabet_unrated_only_established"] = False
        self.config["alphabet_low_rated_only_established"] = False

    def test_non_english_excluded_in_every_movie_catalog(self):
        records = [movie("tmdb:111111", "Alice English", "Alice English: Live", "en"),
                   movie("tmdb:222222", "Berto Spanish", "Berto Spanish: Live", "es"),
                   movie("tmdb:333333", "Alice English", "Roast of Alice English", "en", True),
                   movie("tmdb:444444", "Berto Spanish", "Roast of Berto Spanish", "es", True)]
        groups, _ = categories(records, self.config, TODAY)
        published = {r["id"] for _, _, items in groups for r in items}
        self.assertIn("tmdb:111111", published)
        self.assertIn("tmdb:333333", published)
        self.assertNotIn("tmdb:222222", published)
        self.assertNotIn("tmdb:444444", published)
        with tempfile.TemporaryDirectory() as path:
            report = build(records, self.config, Path(path), TODAY)
            self.assertEqual(report["english_language_policy"]["known_non_english_published_movie_records"], 0)

    def test_missing_languages_of_non_english_performer_inferred_conservatively(self):
        records = [movie("tmdb:111111", "Cem Yılmaz", "Turkish Special", "tr"),
                   movie("tmdb:222222", "Cem Yılmaz", "Other Comedy", None),
                   movie("tmdb:333333", "English Only", "Recorded Comedy", "en"),
                   movie("tmdb:444444", "English Only", "Unknown Audio", None)]
        hints = performer_non_english_evidence(records)
        self.assertFalse(movie_allowed(records[1], True, hints))
        self.assertTrue(movie_allowed(records[3], True, hints))
        self.assertTrue(movie_allowed(records[2], True, hints))
        self.assertTrue(movie_allowed(records[1], False, hints))

    def test_missing_language_with_english_credit_not_falsely_rejected(self):
        records = [movie("tmdb:111111", "Bilingual Comic", "Their English Special", "en"),
                   movie("tmdb:222222", "Bilingual Comic", "Their Spanish Special", "es"),
                   movie("tmdb:333333", "Bilingual Comic", "Unknown Special", None)]
        hints = performer_non_english_evidence(records)
        self.assertNotIn("bilingual comic", hints)
        self.assertTrue(movie_allowed(records[2], True, hints))

    def test_youtube_rejects_explicit_non_english_audio(self):
        self.assertFalse(youtube_allowed({"audio_language":"es-MX"}, True))
        self.assertTrue(youtube_allowed({"audio_language":"en-US", "default_language":"es"}, True))
        self.assertTrue(youtube_allowed({}, True))  # Unknown is not verified English.
        clip = {"video_id":"abcdefghijk", "title":"John Mulaney Stand-Up Comedy Special",
                "channel":"John Mulaney", "seconds":3600, "audio_language":"tr"}
        self.assertIsNone(classify(clip, self.config))

    def test_tv_skips_multilingual_show_and_non_english_episode(self):
        rows = [
            {"source":"tmdb-tv-episode", "show_title":"COMEDIANS of the world",
             "tmdb_show_id":85418, "season_number":1, "episode_number":1},
            {"source":"tmdb-tv-episode", "show_title":"Comedy Central Presents",
             "tmdb_show_id":4787, "season_number":1, "episode_number":1,
             "episode_audio_language":"es"},
            {"source":"tmdb-tv-episode", "show_title":"Comedy Central Presents",
             "tmdb_show_id":4787, "season_number":1, "episode_number":2,
             "show_original_language":"en"},
        ]
        _, metas, counts = build_tv_series(rows, english_only=True,
                                           exclude_multilingual=["COMEDIANS of the world"])
        self.assertEqual(counts, {"Comedy Central Presents":1})
        self.assertEqual(len(metas["tmdb:4787"]["videos"]), 1)

    def test_backfill_language_of_legacy_english_and_foreign_specials(self):
        cache = {"tt1": movie("tmdb:1", "Cem Yılmaz", "CM101", None),
                 "tt2": movie("tmdb:2", "A Comic", "English Set", None)}
        class API:
            calls = []
            def get(self, route):
                self.calls.append(route)
                return {"original_language": "tr" if route.endswith("/1") else "en"}
        state = {}
        count = backfill_original_languages(API(), cache, state=state, today=TODAY)
        self.assertEqual(count, 2)
        self.assertEqual(cache["tt1"]["original_language"], "tr")
        self.assertEqual(cache["tt2"]["original_language"], "en")
        self.assertEqual(backfill_original_languages(API(), cache, state=state, today=TODAY), 0)


if __name__ == "__main__":
    unittest.main()
