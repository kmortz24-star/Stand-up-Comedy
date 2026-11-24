import json
import unittest
from datetime import date
from pathlib import Path
from build_catalogs import categories
from youtube_catalogs import merged_movie_previews, classify

ROOT = Path(__file__).resolve().parents[1]

class SmallChanges(unittest.TestCase):
    def test_legends_events(self):
        config = json.loads((ROOT / 'config.json').read_text())
        records = json.loads((ROOT / 'data/specials.json').read_text())
        groups, _ = categories(records, config, date(2026, 11, 24))
        groups = {k: rows for k, _, rows in groups}
        self.assertEqual(groups['comedy-legends'][-1]['performer'], 'Lewis Black')
        self.assertNotIn('tt14365068', {r['id'] for r in groups['comedy-legends']})
        self.assertIn('tt14365068', {r['id'] for r in groups['roasts-events']})
        self.assertFalse(any(r['id'] == 'tt14365068' for k, rows in groups.items() if k.startswith('comedians-') for r in rows))

    def test_manual_set_without_fabricated_duration(self):
        config = json.loads((ROOT / 'config.json').read_text())
        videos = json.loads((ROOT / 'data/youtube_candidates.json').read_text())
        rows, resources = merged_movie_previews(videos, config)
        ids = {e['meta']['id'] for e in rows['youtube-viral-rising']}
        self.assertTrue({'standupyt_a3BMzZVEn6g', 'standupyt_0gdIZ4nz3iE', 'standupyt_K8-GCc_Tpow'} <= ids)
        self.assertNotIn('0 min', resources['standupyt_a3BMzZVEn6g']['meta']['description'])
        entry = config['manual_youtube_sets'][0]
        self.assertIsNone(classify({**entry, 'video_id': 'zzzzzzzzzzz'}, config))
        self.assertIsNone(classify({**entry, 'embeddable': False}, config))
        rows, resources = merged_movie_previews([{**entry, 'seconds': 900}], config)
        self.assertIn('15 min', resources['standupyt_a3BMzZVEn6g']['meta']['description'])
