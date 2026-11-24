"""Offline tests for YouStream-compatible YouTube preview catalogs."""
import tempfile
import unittest
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from youtube_catalogs import classify, identify_performer, preview_rows
from build_catalogs import build

CONFIG = {"addon_id": "com.example.test", "addon_name": "Test Stand-Up",
          "alphabet_groups": ["ABCD", "EFGH", "IJKL", "MNOP", "QRST", "UVWXYZ"],
          "viral_rising_comedians": ["Ari Matti", "Maddie Wiener"],
          "roulette_groups": {"well_known": ["Bill Burr"], "b_tier": ["Joe DeRosa"]},
          "legends_comedians": ["George Carlin"],
          "weekly_hidden_gems_count": 5, "weekly_viral_rising_count": 5,
          "weekly_roulette_count": 4, "roulette_group_size": 1, "new_specials_months": 18,
          "hidden_gems_max_popularity": 15, "hidden_gems_min_rating": 6.5,
          "hidden_gems_min_votes": 3, "roast_title_terms": ["roast"],
          "enable_youtube_preview_catalogs": True}


def video(id, title, channel, secs=1200, who=""):
    return {"video_id": id, "title": title, "channel": channel,
            "seconds": secs, "performer_search": who, "published_at": "2026-11-23T00:00:00Z"}


class YoutubeCatalogTests(unittest.TestCase):
    def test_viral_newcomer_on_dont_tell_comedy(self):
        v = video('aaaaaaaaaaa', 'The Plot | Ashley Monique | Stand Up Comedy', "Don't Tell Comedy", 700)
        self.assertEqual(classify(v, CONFIG), ('youtube-viral-rising', 'Ashley Monique'))

    def test_known_comedian_goes_to_gems_not_rising(self):
        v = video('bbbbbbbbbbb', '15 Minutes of Bill Burr Stand-Up Comedy', 'Netflix Is A Joke', 900)
        self.assertEqual(classify(v, CONFIG), ('youtube-hidden-gems', 'Bill Burr'))

    def test_long_special_separate(self):
        v = video('ccccccccccc', 'Chad Daniels: Nothing To Fix (FULL COMEDY SPECIAL)', 'Chad Daniels', 3600,
                  'Chad Daniels')
        self.assertEqual(classify(v, CONFIG), ('youtube-full-specials', 'Chad Daniels'))

    def test_false_search_attribution_and_podcasts_rejected(self):
        v = video('ddddddddddd', 'Maddy Smith Stand-Up Comedy | Best Set', 'New York Comedy Club', 700,
                  'Maddie Wiener')
        self.assertNotEqual(identify_performer(v, CONFIG), 'Maddie Wiener')
        v2 = video('eeeeeeeeeee', 'Dr. Phil LIVE! With Matt Rife and Kam Patterson', 'Adam Ray', 5000)
        self.assertIsNone(classify(v2, CONFIG))
        v3 = video('fffffffffff', 'Best of Ari Matti Stand Up Comedy', 'Ari Matti', 1000)
        self.assertIsNone(classify(v3, CONFIG))

    def test_bad_ids_and_untrusted_channels_not_published(self):
        self.assertIsNone(classify(video('bad id', 'Ari Matti stand up special', 'Ari Matti'), CONFIG))
        self.assertIsNone(classify(video('ggggggggggg', 'Random Person | Aaron Adams | Stand Up Comedy', 'SpamTV'), CONFIG))

    def test_duplicate_video_keeps_one_youtube_meta(self):
        v = video('hhhhhhhhhhh', 'The Joke | Ashley Monique | Stand Up Comedy', "Don't Tell Comedy")
        rows = preview_rows([v, v], CONFIG)
        self.assertEqual(len(rows['youtube-viral-rising']), 1)
        self.assertEqual(rows['youtube-viral-rising'][0]['id'], 'yt_id:hhhhhhhhhhh')
        self.assertEqual(rows['youtube-viral-rising'][0]['type'], 'youtube')

    def test_generated_manifest_preserves_movie_rows_and_adds_youtube(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = video('iiiiiiiiiii', 'Funny Story | Ashley Monique | Stand Up Comedy', "Don't Tell Comedy")
            with patch('build_catalogs.read_json', side_effect=lambda path, default=None: [v] if str(path).endswith('youtube_candidates.json') else (default if default is not None else {})):
                report = build([], CONFIG, Path(tmp), date(2026, 11, 23))
            manifest = json.loads((Path(tmp) / 'manifest.json').read_text())
            self.assertIn('movie', manifest['types'])
            self.assertIn('youtube', manifest['types'])
            self.assertTrue(any(c['id'] == 'viral-and-rising' and c['type'] == 'movie' for c in manifest['catalogs']))
            self.assertTrue(any(c['id'] == 'youtube-viral-rising' and c['type'] == 'youtube' for c in manifest['catalogs']))
            data = json.loads((Path(tmp) / 'catalog/youtube/youtube-viral-rising.json').read_text())
            self.assertEqual(data['metas'][0]['id'], 'yt_id:iiiiiiiiiii')
            self.assertTrue(report['youtube_preview']['unverified_playback'])

if __name__ == '__main__':
    unittest.main()
