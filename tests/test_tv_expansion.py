"""Expanded TV-show discovery: actual show matches, never invented shows."""
import unittest
from datetime import date
from unittest.mock import patch

from fetch_tv_sets import SHOWS, find_show, fetch_tv_candidates, main
from tv_catalogs import build_tv_series


class FakeTMDB:
    def __init__(self):
        self.calls = []
    def get(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if path == '/search/tv':
            query = kwargs['query']
            if query == 'One Night Stand':
                return {'results': [
                    {'id': 100, 'name': 'One Night Stand', 'first_air_date': '2024-05-01',
                     'overview': 'A documentary about dating', 'vote_count': 999},
                    {'id': 200, 'name': 'One Night Stand', 'first_air_date': '1989-04-01',
                     'overview': 'Classic HBO stand-up comedy specials', 'vote_count': 5},
                ]}
            if query == 'Def Comedy Jam':
                return {'results': [
                    {'id': 400, 'name': 'Def Comedy Jam', 'first_air_date': '1992-03-01',
                     'overview': 'An HBO stand-up comedy show', 'vote_count': 3}]}
            return {'results': []}
        if path == '/tv/400':
            return {'name': 'Def Comedy Jam', 'overview': 'Stand-up', 'seasons':
                    [{'season_number': 0}, {'season_number': 1}],
                    'networks': [{'name': 'HBO'}], 'poster_path': '/test.jpg'}
        if path == '/tv/400/season/1':
            return {'episodes': [{'episode_number': 1, 'name': 'Episode 1',
                                  'air_date': '1992-03-01', 'id': 300}]}
        raise AssertionError('Unexpected API request ' + path)


class ExpandedTvTests(unittest.TestCase):
    def test_broad_show_roster_without_manual_episode_seeds(self):
        self.assertGreaterEqual(len(SHOWS), 20)
        names = [name for name, _ in SHOWS]
        self.assertEqual(len(set(names)), len(names))
        for name in ('Comedy Central Presents', 'Def Comedy Jam', 'Premium Blend',
                     'Gotham Comedy Live', 'Live at Gotham', 'Last Comic Standing',
                     'Comedians of the World', 'Live at the Apollo'):
            self.assertIn(name, names)

    def test_ambiguous_show_match_rejects_wrong_year_even_if_popular(self):
        match = find_show(FakeTMDB(), ('One Night Stand',), 'One Night Stand')
        self.assertEqual(match['id'], 200)

    def test_exact_title_needed_no_fuzzy_unrelated_results(self):
        class DifferentShow:
            def get(self, path, **kwargs):
                return {'results': [{'id': 999, 'name': 'Last Comic Shopping',
                                     'overview': 'A comedy show'}]}
        self.assertIsNone(find_show(DifferentShow(), ('Last Comic Standing',),
                                    'Last Comic Standing'))

    def test_real_episodes_only_and_ignores_specials_season_zero(self):
        rows = fetch_tv_candidates(FakeTMDB(), [('Def Comedy Jam', ('Def Comedy Jam',))])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['tmdb_show_id'], 400)
        self.assertEqual((rows[0]['season_number'], rows[0]['episode_number']), (1,1))
        shows, metas, counts = build_tv_series(rows)
        self.assertEqual([show['name'] for show in shows], ['Def Comedy Jam'])
        self.assertEqual([x['id'] for x in metas['tmdb:400']['videos']], ['tmdb:400:1:1'])
        self.assertEqual(counts, {'Def Comedy Jam': 1})

    def test_sparse_refresh_preserves_existing_candidates(self):
        old = {'id': 'tmdb-tv:400:1:2', 'show_title': 'Def Comedy Jam',
               'season_number': 1, 'episode_number': 2, 'source':'tmdb-tv-episode',
               'tmdb_show_id':400}
        new = {'id': 'tmdb-tv:400:1:1', 'show_title': 'Def Comedy Jam',
               'season_number': 1, 'episode_number': 1, 'source':'tmdb-tv-episode',
               'tmdb_show_id':400}
        saved = {}
        with patch('fetch_tmdb.TMDB', return_value=object()), \
             patch('fetch_tv_sets.fetch_tv_candidates', return_value=[new]), \
             patch('fetch_tv_sets.read_json', return_value=[old]), \
             patch('fetch_tv_sets.write_json', side_effect=lambda path, rows: saved.setdefault('rows', rows)):
            main()
        self.assertEqual({r['id'] for r in saved['rows']}, {'tmdb-tv:400:1:1','tmdb-tv:400:1:2'})


if __name__ == '__main__':
    unittest.main()
