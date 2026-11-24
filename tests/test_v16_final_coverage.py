"""Verified additions, metadata refresh, and preservation of approved curation."""
import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from build_catalogs import categories
from fetch_tmdb import merge_manual_additions

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 24)

class NoMatches:
    def get(self, *args, **kwargs):
        return {'movie_results': []}

class Match:
    def get(self, *args, **kwargs):
        return {'movie_results': [{'id': 123}]}

class FinalCoverage(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'config.json').read_text())
        self.seeds = json.loads((ROOT / 'data/manual_additions.json').read_text())

    def test_all_verified_seeds_are_eligible_without_fake_ratings(self):
        cache = {}
        merge_manual_additions(NoMatches(), cache, self.seeds)
        self.assertEqual(len(cache), 26)
        self.assertTrue(all('vote_average' not in r for r in cache.values()))
        rows, _ = categories(list(cache.values()), self.config, TODAY)
        alpha = {x['id'] for key, _, entries in rows if key.startswith('comedians-') for x in entries}
        # The Rose Garden is already displayed as a YouTube card.
        self.assertEqual(alpha, set(cache) - {'tt37666574'})

    def test_metadata_lookup_preserves_ratings_and_correct_credit(self):
        item = self.seeds[0]
        record = {'id': item['id'], 'tmdb_id': 123, 'title': item['title'],
                  'performer': None, 'vote_average': 7.5, 'vote_count': 50,
                  'release_date': '2015-05-02', 'poster_path': '/sample.jpg', 'tags': []}
        cache = {'tmdb:123': {'id': 'tmdb:123', 'tmdb_id': 123}}
        with patch('fetch_tmdb.movie_record', return_value=record) as mocked:
            merge_manual_additions(Match(), cache, [item])
            mocked.assert_called_once()
        self.assertNotIn('tmdb:123', cache)
        self.assertEqual(cache[item['id']]['performer'], item['performer'])
        self.assertEqual(cache[item['id']]['vote_count'], 50)
        self.assertEqual(cache[item['id']]['poster_path'], '/sample.jpg')
        self.assertNotIn('release_date_precision', cache[item['id']])
        merge_manual_additions(NoMatches(), cache, [item])
        self.assertEqual(cache[item['id']]['release_date'], '2015-05-02')
        self.assertEqual(cache[item['id']]['vote_average'], 7.5)

    def test_approval_not_override_hard_exclusion(self):
        item = self.seeds[0]
        c = dict(self.config)
        c['excluded_ids'] = list(c['excluded_ids']) + [item['id']]
        rows, _ = categories([item], c, TODAY)
        self.assertFalse(any(r['id'] == item['id'] for _, _, rs in rows for r in rs))

    def test_personal_favorites_separate_from_classics_and_public_tiers(self):
        self.assertIn('Mitch Fatel', self.config['personal_favorites'])
        self.assertNotIn('Don Rickles', self.config['personal_favorites'])
        self.assertIn('Don Rickles', self.config['legends_comedians'])
        self.assertNotIn('Dave Attell', self.config['personal_favorites'])
        self.assertIn('Dave Attell', self.config['roulette_groups']['classic_older'])
        self.assertIn('event', self.config['tag_overrides']['tt20723672'])
        self.assertTrue({'tt1717578','tt24640480','tt37666574'} <= set(self.config['alphabet_duplicate_movie_ids']))
