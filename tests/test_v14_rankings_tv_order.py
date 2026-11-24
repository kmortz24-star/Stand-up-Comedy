"""Regression checks for 200 rated specials and recognition-ordered TV rows."""
import json
import unittest
from pathlib import Path

from build_catalogs import ranked_specials
from tv_catalogs import build_tv_series

ROOT = Path(__file__).resolve().parents[1]

class V14Tests(unittest.TestCase):
    def test_top_rated_200_and_favorites_200_without_new_catalog_ids(self):
        cfg = json.loads((ROOT / 'config.json').read_text())
        self.assertEqual(cfg['ranked_list_size'], 200)
        self.assertEqual(cfg['fan_favorites_size'], 200)
        records = [dict(id=f'tmdb:{i}', title=f'Comic {i} Special',
                        performer=f'Comic {i}', original_language='en',
                        vote_average=7.0 + (i % 25) / 20, vote_count=25 + i,
                        release_date='2020-01-01') for i in range(250)]
        rated, favorites = ranked_specials(records, cfg)
        self.assertEqual(len(rated), 200)
        self.assertEqual(len(favorites), 200)
        self.assertEqual(len({r['id'] for r in rated}), 200)

    def test_tv_recognition_first_and_all_episodes_preserved(self):
        rows = []
        for show_id, show_name in [(100, 'Z New Show'), (200, 'Def Comedy Jam'),
                                   (300, 'Comedy Central Presents'), (400, 'A New Show')]:
            for ep in (1, 2):
                rows.append(dict(source='tmdb-tv-episode', show_title=show_name,
                                 tmdb_show_id=show_id, season_number=1,
                                 episode_number=ep, episode_title=f'Episode {ep}'))
        previews, details, counts = build_tv_series(
            rows, priority_order=['Comedy Central Presents', 'Def Comedy Jam'])
        self.assertEqual([p['name'] for p in previews],
                         ['Comedy Central Presents', 'Def Comedy Jam', 'A New Show', 'Z New Show'])
        self.assertEqual(len(details), 4)
        self.assertEqual(sum(counts.values()), 8)
        self.assertEqual([e['id'] for e in details['tmdb:300']['videos']],
                         ['tmdb:300:1:1', 'tmdb:300:1:2'])

    def test_real_repository_tv_names_have_unique_priority_positions(self):
        cfg = json.loads((ROOT / 'config.json').read_text())
        order = cfg['tv_show_priority_order']
        self.assertEqual(len(order), len({x.casefold() for x in order}))
        candidates = json.loads((ROOT / 'data/tv_episode_candidates.json').read_text())
        previews, details, counts = build_tv_series(candidates,
                         english_only=cfg['english_language_only'],
                         exclude_multilingual=cfg['exclude_multilingual_tv_shows'],
                         priority_order=order)
        self.assertGreaterEqual(len(previews), 20)
        self.assertEqual(previews[0]['name'], 'Comedy Central Presents')
        self.assertEqual(previews[1]['name'], 'Def Comedy Jam')
        self.assertEqual(previews[2]['name'], 'Last Comic Standing')
        self.assertEqual(sum(counts.values()), sum(len(m['videos']) for m in details.values()))

if __name__ == '__main__':
    unittest.main()
