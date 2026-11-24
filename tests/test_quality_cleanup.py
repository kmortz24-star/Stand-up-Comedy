"""Exercise optional quality trimming while protecting established comedy."""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from build_catalogs import categories, build, exclude_low_rated_unknown
from test_unrated_cleanup import BASE, rec

TODAY = date(2026, 11, 23)


def config():
    c = copy.deepcopy(BASE)
    c.update({
        'alphabet_low_rated_only_established': True,
        'alphabet_low_rating_min_votes': 5,
        'alphabet_low_rating_cutoff': 6.0,
        'quality_additional_established': ['Ken Jeong'],
        'unrated_additional_established': ['Jackie Kashian'],
        'excluded_ids': ['bad-movie'],
        'roast_title_terms': ['roast', 'kill tony'],
    })
    return c


def ids(rows, key='comedians-'):
    return {item['id'] for ident, _, items in rows if ident.startswith(key) for item in items}


class QualityCleanupTests(unittest.TestCase):
    def test_reviewed_comics_survive_weak_ratings(self):
        c = config()
        items = [
            rec('ken', 'Ken Jeong', 88, 5.8),
            rec('doug', 'Doug Stanhope', 18, 4.6),
            rec('new', 'Unknown Comic', 15, 5.4),
            rec('poor', 'Unknown Comic', 6, 2.7),
            rec('tiny', 'Unknown Comic', 2, 5.0),
            rec('good', 'Unknown Comic', 15, 6.7),
            rec('unrated', 'Unknown Comic'),
            rec('jackie', 'Jackie Kashian'),
        ]
        rows, _ = categories(items, c, TODAY)
        self.assertEqual(ids(rows), {'ken', 'doug', 'tiny', 'good', 'jackie'})
        self.assertFalse(exclude_low_rated_unknown(items[0], c))
        self.assertTrue(exclude_low_rated_unknown(items[2], c))

    def test_ensemble_events_not_removed_or_misfiled(self):
        c = config()
        event = rec('kt', 'Kill Tony', 20, 5.5)
        event['title'] = 'Kill Tony: Kill or Be Killed'
        rows, _ = categories([event], c, TODAY)
        self.assertNotIn('kt', ids(rows))
        self.assertIn('kt', ids(rows, 'roasts-events'))

    def test_confirmed_wrong_movie_excluded(self):
        items = [rec('bad-movie', 'Robin Williams', 60, 7.8)]
        rows, _ = categories(items, config(), TODAY)
        self.assertNotIn('bad-movie', ids(rows))

    def test_optional_and_reversible_audit(self):
        c = config()
        items = [rec('est', 'Ken Jeong', 15, 5.2),
                 rec('low', 'Unknown Comic', 6, 5.6),
                 rec('solid', 'Unknown Comic', 12, 7.4)]
        snapshot = json.dumps(items)
        with tempfile.TemporaryDirectory() as td:
            report = build(items, c, Path(td), TODAY)
            summary = report['quality_cleanup']
            self.assertEqual(summary['low_rated_movies_hidden'], 1)
            self.assertEqual(summary['low_rated_established_movies_kept'], 1)
            detail = json.loads((Path(td) / 'quality_cleanup_report.json').read_text())
            self.assertEqual([v['id'] for v in detail['hidden']], ['low'])
        rows, _ = categories(items, {**c, 'alphabet_low_rated_only_established': False}, TODAY)
        self.assertIn('low', ids(rows))
        self.assertEqual(snapshot, json.dumps(items))


if __name__ == '__main__':
    unittest.main()
