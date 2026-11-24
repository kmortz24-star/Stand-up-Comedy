"""V15: conservative documentary exclusion plus a stricter, reversible A/B-safe rating sweep."""
import json
import unittest
from datetime import date
from pathlib import Path

from build_catalogs import (
    categories, exclude_low_rated_unknown, non_standup_movie,
    established_low_rated_performers,
)

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 24)


def record(identifier, title, performer, score, votes):
    return {'id': identifier, 'title': title, 'performer': performer,
            'vote_average': score, 'vote_count': votes, 'release_date': '2020-01-01',
            'original_language': 'en'}


def alpha_ids(rows):
    return {x['id'] for key, _, entries in rows if key.startswith('comedians-') for x in entries}


class AggressiveCleanupV15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((ROOT / 'config.json').read_text())

    def test_threshold_and_protection_roster(self):
        cfg = self.cfg
        self.assertEqual(cfg['alphabet_low_rating_cutoff'], 6.5)
        self.assertEqual(cfg['alphabet_low_rating_min_votes'], 1)
        protected = established_low_rated_performers(cfg)
        for name in ('Gary Gulman', 'Eddie Griffin', 'Ellen DeGeneres',
                     'Phil Wang', 'Doug Stanhope', 'Jackie Kashian', 'Russell Howard',
                     'Chris Ramsey', 'Tim Allen', 'Paula Poundstone', 'Bob Hope'):
            from build_catalogs import norm
            self.assertIn(norm(name), protected)

    def test_unknown_6_4_and_low_sample_hidden_but_known_survives(self):
        items = [record('weak-1', 'Unknown Comic: Sample 1', 'Unknown Comic', 6.4, 1),
                 record('weak-6', 'Unknown Comic: Sample 2', 'Unknown Comic', 6.4, 6),
                 record('good', 'Unknown Comic: Good', 'Unknown Comic', 6.7, 8),
                 record('protected', 'Gary Gulman: Great Depresh', 'Gary Gulman', 6.2, 13),
                 record('strong-known', 'Ellen DeGeneres: Relatable', 'Ellen DeGeneres', 6.3, 180)]
        got = alpha_ids(categories(items, self.cfg, TODAY)[0])
        self.assertEqual(got, {'good', 'protected', 'strong-known'})
        self.assertTrue(exclude_low_rated_unknown(items[0], self.cfg))
        self.assertFalse(exclude_low_rated_unknown(items[3], self.cfg))

    def test_known_nonstandup_is_excluded_even_from_established_comic(self):
        items = [record('doc', "Al Murray's Great British War Movies", 'Al Murray', 8.9, 100),
                 record('valid', 'Al Murray, The Pub Landlord: Giving It Both Barrels', 'Al Murray', 6.0, 4),
                 record('doc2', 'Bob Newhart: Unbuttoned', 'Bob Newhart', 9.0, 2),
                 record('live', 'Bob Newhart: Off the Record', 'Bob Newhart', 6.0, 1)]
        got = alpha_ids(categories(items, self.cfg, TODAY)[0])
        self.assertEqual(got, {'valid', 'live'})
        self.assertTrue(non_standup_movie(items[0], self.cfg))

    def test_event_not_placed_in_alphabeticals(self):
        event = record('event', 'Just for Laughs: The Gala Specials - Jo Koy', 'Just for Laughs', 9, 90)
        cfg = dict(self.cfg)
        cfg['tag_overrides'] = {**cfg.get('tag_overrides', {}), 'event': ['event']}
        rows, _ = categories([event], cfg, TODAY)
        self.assertNotIn('event', alpha_ids(rows))
        self.assertIn('event', {x['id'] for key, _, xs in rows if key == 'roasts-events' for x in xs})

    def test_malformed_performer_credit_corrected(self):
        self.assertEqual(self.cfg['performer_overrides']['tt1950332'], 'Russell Howard')
        self.assertEqual(self.cfg['performer_overrides']['tt31869794'], 'Chris Ramsey')

    def test_charity_event_not_in_alphabet(self):
        self.assertIn('event', self.cfg['tag_overrides']['tt7657600'])

    def test_no_new_category_or_alphabet_reordering(self):
        self.assertEqual(self.cfg['alphabet_groups'], ['AB', 'CDEFG', 'HIJ', 'KLM', 'NOPQR', 'STUVWXYZ'])
        self.assertEqual(self.cfg['ranked_list_size'], 200)
        self.assertEqual(self.cfg['fan_favorites_size'], 200)


if __name__ == '__main__':
    unittest.main()
