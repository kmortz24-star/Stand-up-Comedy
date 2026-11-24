"""No-network coverage and comedian-priority regression tests."""
import unittest
from datetime import date

from audit_coverage import roster_tiers, coverage_report
from fetch_tmdb import discovery_names, scheduled_names, title_search_queue


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'legends_comedians': ['Robin Comic'],
            'roulette_groups': {
                'well_known': ['Adele Comic'],
                'b_tier': ['Bill Comic'],
                'classic_older': [],
                'discovery': ['Random Comic']},
            'viral_rising_comedians': ['Viral Comic'],
            'coverage_priority': {
                'established_extra': ['Connie Comic'],
                'select_underrated': ['Dina Comic']},
        }

    def test_only_established_and_select_underrated_are_priority(self):
        tiers = roster_tiers(self.config)
        self.assertEqual(len(tiers), 5)
        self.assertEqual(tiers['dina comic']['priority'], 'select_underrated')
        self.assertNotIn('random comic', tiers)
        self.assertNotIn('viral comic', tiers)
        names, prioritized = discovery_names(self.config, {}, {})
        self.assertIn('Viral Comic', names)  # still discoverable
        self.assertNotIn('viral comic', prioritized)  # not high priority
        self.assertIn('bill comic', prioritized)

    def test_priority_searches_first_even_if_unknown_name_has_older_cursor(self):
        names, prioritized = discovery_names(self.config, {}, {})
        state = {'searched_performers': {'random comic': '2024-01-01'}}
        due = scheduled_names(names, prioritized, state, {},
                              today=date(2026, 11, 24), max_searches=5)
        self.assertEqual(set(due), {'Robin Comic', 'Adele Comic', 'Bill Comic',
                                    'Connie Comic', 'Dina Comic'})

    def test_title_discovery_prioritizes_established_names(self):
        state = {'works': [
            {'qid': 'Q1', 'name': 'Lost Special 1', 'performer': 'Random Comic'},
            {'qid': 'Q2', 'name': 'Lost Special 2', 'performer': 'Bill Comic'},
            {'qid': 'Q3', 'name': 'Lost Special 3', 'performer': 'Adele Comic'},
        ]}
        ranked = title_search_queue(state, {}, today=date(2026,11,24), limit=2,
                                    priority_performers={'bill comic','adele comic'})
        self.assertEqual({r['performer'] for r in ranked}, {'Bill Comic','Adele Comic'})

    def test_unmatched_titles_remain_review_leads_without_inserting_records(self):
        state = {'works': [
            {'qid': 'Q1', 'name': 'A Rare Night', 'performer': 'Robin Comic'},
            {'qid': 'Q2', 'name': 'Robin Comic: Live', 'performer': 'Robin Comic', 'imdb': 'tt4567'},
        ]}
        movies = [{'id': 'tt4567', 'tmdb_id': 89, 'title': 'Robin Comic: Live',
                   'performer': 'Robin Comic', 'release_date': '1991-01-01'}]
        report = coverage_report(self.config, movies, [], [], state)
        robin = next(p for p in report['comedians'] if p['name'] == 'Robin Comic')
        self.assertEqual(robin['movie_special_records'], 1)
        self.assertEqual([w['title'] for w in robin['independent_unmatched_works']],
                         ['A Rare Night'])
        self.assertTrue(robin['needs_attention'])
        self.assertNotIn('complete', robin)
        self.assertEqual(len(movies), 1)  # audit doesn't modify catalog

    def test_tv_only_names_flagged_for_more_work(self):
        report = coverage_report(self.config, [],
                                 [{'id': 'tv-1', 'performer': 'Dina Comic'}],
                                 [{'video_id': 'y-1', 'performer_search': 'Dina Comic'}], {})
        dina = next(p for p in report['comedians'] if p['name'] == 'Dina Comic')
        self.assertEqual(dina['movie_special_records'], 0)
        self.assertEqual(dina['tv_episode_review_leads'], 1)
        self.assertEqual(dina['youtube_review_candidates'], 1)
        self.assertTrue(dina['needs_attention'])


if __name__ == '__main__':
    unittest.main()
