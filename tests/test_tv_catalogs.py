"""Offline checks for publishing TV anthology episodes as proper series."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tv_catalogs import build_tv_series
from build_catalogs import build


TV_ROWS = [
    {'source':'tmdb-tv-episode', 'show_title':'Comedy Central Presents', 'tmdb_show_id':4787,
     'season_number':11, 'episode_number':19, 'episode_title':'Mitch Fatel',
     'performer':'Mitch Fatel', 'air_date':'2007-04-05',
     'show_poster_path':'/known.jpg'},
    {'source':'tmdb-tv-episode', 'show_title':'Comedy Central Presents', 'tmdb_show_id':4787,
     'season_number':1, 'episode_number':2, 'episode_title':'Marc Maron',
     'performer':'Marc Maron', 'air_date':'1998-12-08'},
    {'source':'tmdb-tv-episode', 'show_title':'One Night Stand', 'tmdb_show_id':12208,
     'season_number':1, 'episode_number':1, 'episode_title':'Judy Tenuta',
     'performer':'Judy Tenuta', 'air_date':'1989-02-15'},
]


class TVCatalogTests(unittest.TestCase):
    def test_episode_metadata_preserves_real_episode_ids_and_order(self):
        previews, metas, counts = build_tv_series(TV_ROWS)
        self.assertEqual(counts, {'Comedy Central Presents':2, 'One Night Stand':1})
        self.assertEqual([x['id'] for x in previews], ['tmdb:4787', 'tmdb:12208'])
        self.assertEqual([x['id'] for x in metas['tmdb:4787']['videos']],
                         ['tmdb:4787:1:2', 'tmdb:4787:11:19'])
        self.assertEqual(metas['tmdb:4787']['videos'][1]['title'], 'Mitch Fatel')
        self.assertTrue(metas['tmdb:4787']['poster'].endswith('/known.jpg'))
        self.assertNotIn('streams', metas['tmdb:4787'])

    def test_invalid_ids_are_skipped_without_inventing_episodes(self):
        rows = [TV_ROWS[0], {**TV_ROWS[0], 'season_number':0},
                {**TV_ROWS[0], 'tmdb_show_id':'garbage'},
                {**TV_ROWS[0], 'episode_number':0},
                {**TV_ROWS[0], 'source':'untrusted'}]
        _, metas, counts = build_tv_series(rows)
        self.assertEqual(counts, {'Comedy Central Presents':1})
        self.assertEqual(len(metas['tmdb:4787']['videos']), 1)

    def test_builder_adds_only_one_series_catalog_with_episode_metadata(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        config['enable_youtube_preview_catalogs'] = False
        config['enable_tv_series_catalog'] = True
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            def json_data(path, default=None):
                if str(path).endswith('tv_episode_candidates.json'):
                    return TV_ROWS
                return default if default is not None else {}
            with patch('build_catalogs.read_json', side_effect=json_data):
                report = build([], config, output, date(2026,11,23))
            manifest = json.loads((output/'manifest.json').read_text())
            self.assertIn('series', manifest['types'])
            self.assertEqual(len([c for c in manifest['catalogs'] if c['type']=='series']),1)
            self.assertEqual(len([r for r in manifest['resources'] if isinstance(r,dict) and
                                  r['name']=='meta' and r['types']==['series']]),1)
            self.assertIn('standup-tv-series',
                (output/'catalog/series/standup-tv-series.json').as_posix())
            self.assertTrue((output/'meta/series/tmdb:4787.json').exists())
            self.assertEqual(report['tv_series']['episode_count'],3)
            self.assertFalse(report['tv_series']['playback_verified'])
            self.assertFalse((output/'stream/series/tmdb:4787:11:19.json').exists())

    def test_no_tv_candidates_preserves_old_manifest(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        config['enable_youtube_preview_catalogs'] = False
        config['enable_tv_series_catalog'] = True
        with tempfile.TemporaryDirectory() as tmp:
            with patch('build_catalogs.read_json', side_effect=lambda path, default=None: [] if str(path).endswith('tv_episode_candidates.json') else (default if default is not None else {})):
                build([],config,Path(tmp),date(2026,11,23))
            manifest=json.loads((Path(tmp)/'manifest.json').read_text())
            self.assertEqual(manifest['types'],['movie'])
            self.assertFalse(any(c['type']=='series' for c in manifest['catalogs']))

if __name__ == '__main__':
    unittest.main()
