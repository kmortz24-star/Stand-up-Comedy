"""Roast-first ranking, Legends-only removal, and sketch TV placement."""
import json
import unittest
from datetime import date
from pathlib import Path
from build_catalogs import categories, roast_event_sort_key
from fetch_tv_sets import SKETCH_SHOWS, fetch_tv_candidates
from tv_catalogs import build_tv_series

ROOT = Path(__file__).resolve().parents[1]

class RoastsAndSketch(unittest.TestCase):
    def test_roasts_first_and_consensus_over_tiny_samples(self):
        rows = [dict(id='event', title='Comedy Tour', vote_average=9, vote_count=1000),
                dict(id='small', title='The Roast of Small', vote_average=10, vote_count=1),
                dict(id='established', title='The Roast of Big', vote_average=7.5, vote_count=150),
                dict(id='roasting', title='Roasting Shaq', vote_average=0, vote_count=0),
                dict(id='lowevent', title='Another Tour', vote_average=5, vote_count=5)]
        ranked = sorted(rows, key=roast_event_sort_key)
        self.assertEqual([r['id'] for r in ranked], ['established','small','roasting','event','lowevent'])

    def test_sinbad_stays_in_alphabet_and_other_legends_unchanged(self):
        c = json.loads((ROOT/'config.json').read_text())
        records = json.loads((ROOT/'data/specials.json').read_text())
        def indexed(cfg):
            groups, _ = categories(records, cfg, date(2026,11,24))
            return {k: rows for k, _, rows in groups}
        new = indexed(c)
        old = indexed({**c, 'legends_comedians': c['legends_comedians'][:-2]+['Sinbad']+c['legends_comedians'][-2:]})
        self.assertFalse(any(r['performer']=='Sinbad' for r in new['comedy-legends']))
        self.assertEqual(new['comedy-legends'][-1]['performer'], 'Lewis Black')
        for key in new:
            if key.startswith('comedians-'):
                self.assertEqual([r['id'] for r in new[key]], [r['id'] for r in old[key]])
        self.assertTrue(any(r['performer']=='Sinbad' for k,rows in new.items() if k.startswith('comedians-') for r in rows))
        self.assertEqual({r['id'] for r in new['roasts-events']}, {r['id'] for r in old['roasts-events']})

    def test_sketches_inserted_after_eight_ranked_standup_shows(self):
        rows = [dict(source='tmdb-tv-episode', show_title=f'Standup {i}', tmdb_show_id=i,
                     season_number=1, episode_number=1, show_vote_average=7,
                     show_vote_count=i*10, show_popularity=i) for i in range(1,11)]
        rows += [dict(source='tmdb-tv-episode', show_title='MADtv', show_kind='sketch',
                      tmdb_show_id=50, season_number=1, episode_number=1,
                      episode_title='Episode 1', episode_overview='Sketches.', performer='Not a performer'),
                 dict(source='tmdb-tv-episode', show_title='Saturday Night Live', show_kind='sketch',
                      tmdb_show_id=51, season_number=1, episode_number=1)]
        previews, details, _ = build_tv_series(rows, rank_by_popularity=True,
                   sketch_order=['Saturday Night Live','MADtv'], sketch_after=8)
        self.assertEqual([r['name'] for r in previews[:8]], [f'Standup {i}' for i in range(10,2,-1)])
        self.assertEqual([r['name'] for r in previews[8:10]], ['Saturday Night Live','MADtv'])
        self.assertEqual([r['name'] for r in previews[10:]], ['Standup 2','Standup 1'])
        self.assertEqual(details['tmdb:50']['videos'][0]['overview'], 'Sketches.')

    def test_sketch_fetch_uses_original_series_and_no_comedian_attribution(self):
        class API:
            def get(self, path, **kwargs):
                if path=='/search/tv':
                    return {'results':[{'id': 12,'name':'MADtv','first_air_date':'2016-01-01','vote_count':999},
                                       {'id': 13,'name':'MADtv','first_air_date':'1995-01-01','vote_count':40}]}
                if path=='/tv/13':
                    return {'name':'MADtv','vote_average':7.4,'vote_count':40,'popularity':12,
                            'seasons':[{'season_number':1}]}
                if path=='/tv/13/season/1':
                    return {'episodes':[{'id': 50,'episode_number':1,'name':'Guest Star','overview':'A sketch show.'}]}
                raise AssertionError(path)
        rows = fetch_tv_candidates(API(), [next(x for x in SKETCH_SHOWS if x[0]=='MADtv')])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['tmdb_show_id'],13)
        self.assertEqual(rows[0]['show_kind'],'sketch')
        self.assertIsNone(rows[0]['performer'])
        self.assertEqual(rows[0]['show_vote_count'],40)
        self.assertEqual(rows[0]['episode_overview'],'A sketch show.')

    def test_roster_and_config_match(self):
        c = json.loads((ROOT/'config.json').read_text())
        self.assertEqual(c['tv_sketch_order'], [n for n,_ in SKETCH_SHOWS])
        self.assertEqual(c['tv_sketch_after'],8)
        self.assertTrue(c['rank_tv_by_popularity'])

if __name__=='__main__':
    unittest.main()
