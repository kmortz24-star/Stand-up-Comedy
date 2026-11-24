"""Offline-only tests for credit, IMDb-ID and exact-title discovery."""
import unittest
from unittest.mock import patch
from datetime import date

from discovery_sources import parse_works
import fetch_youtube
from fetch_tmdb import (
    search_performer_credits, search_exact_title_ids, title_search_queue,
    search_performer_ids,
)


class FakeTMDB:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, route, **params):
        self.calls.append((route, params))
        return self.responses.get(route, {})


class DiscoveryTests(unittest.TestCase):
    def test_wikidata_no_id_special_is_not_dropped(self):
        row = {'work': {'value': 'https://www.wikidata.org/entity/Q90442'},
               'name': {'value': 'Original Comedy Event'}}
        works = parse_works([row])
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]['imdb'], '')
        self.assertEqual(works[0]['tmdb'], '')
        leads = title_search_queue({'works': works}, {}, today=date(2026, 11, 23))
        self.assertEqual([r['title'] for r in leads], ['Original Comedy Event'])

    def test_exact_title_requires_comedy_context_even_for_known_work(self):
        api = FakeTMDB({'/search/movie': {'results': [
            {'id': 1, 'title': 'Original Comedy Event', 'overview': 'A documentary about a theater'},
            {'id': 2, 'title': 'Original Comedy Event', 'overview': 'A comedian performs a live stand-up performance'},
        ]}})
        self.assertEqual(search_exact_title_ids(api, {'title': 'Original Comedy Event'}), {2})

    def test_imdb_id_lookup_works_without_keyword(self):
        api = FakeTMDB({'/find/tt12345678': {'movie_results': [{'id': 832}]}})
        matches = search_exact_title_ids(api, {'title': 'An Oddly Named Special', 'imdb_id': 'tt12345678'})
        self.assertEqual(matches, {832})
        self.assertEqual(api.calls[0][1]['external_source'], 'imdb_id')

    def test_exact_title_fallback_is_not_loose_keyword_matching(self):
        api = FakeTMDB({'/search/movie': {'results': [
            {'id': 10, 'title': 'Comedy Night: A Special', 'overview': 'The making of a comedy film'},
            {'id': 11, 'title': 'Comedy Night', 'overview': 'A live stand-up comedy show'},
        ]}})
        self.assertEqual(search_exact_title_ids(api, {'title': 'Comedy Night', 'performer': 'Unknown Comic'}), {11})

    def test_credits_require_standup_context_and_comic_name(self):
        api = FakeTMDB({
            '/search/person': {'results': [{'id': 101, 'name': 'Alex Comic'},
                                           {'id': 102, 'name': 'Alex Smith'}]},
            '/person/101/movie_credits': {'cast': [
                {'id': 20, 'title': 'Alex Comic: One Hour',
                 'overview': 'A stand-up comedian performs for a crowd', 'character': 'Self'},
                {'id': 21, 'title': 'The Bank Heist',
                 'overview': 'A silly comedy film', 'character': 'Lead Actor'},
                {'id': 22, 'title': 'Alex Comic: Portrait',
                 'overview': 'A documentary biography', 'character': 'Self'},
                {'id': 23, 'title': 'An Unusual Name',
                 'overview': 'A stand-up comedy special performed before a live crowd',
                 'character': 'Self'},
            ]}
        })
        self.assertEqual(search_performer_credits(api, 'Alex Comic'), {20, 23})

    def test_ambiguous_person_names_are_not_guessed(self):
        api = FakeTMDB({'/search/person': {'results': [
            {'id': 2, 'name': 'Pat Lee'}, {'id': 3, 'name': 'Pat Lee'}]}})
        self.assertEqual(search_performer_credits(api, 'Pat Lee'), set())
        self.assertEqual(len(api.calls), 1)

    def test_title_queue_rotates_many_sources(self):
        state = {'works': [
            {'qid': 'Q1', 'name': 'A Very Specific Standup Special', 'imdb': 'tt54321', 'tmdb': ''},
            {'qid': 'Q2', 'name': 'A Different Special', 'imdb': 'tt65432', 'tmdb': ''},
        ]}
        result = title_search_queue(state, {}, today=date(2026, 11, 23), limit=3)
        self.assertEqual(len(result), 2)
        self.assertEqual({r['title'] for r in result}, {'A Very Specific Standup Special', 'A Different Special'})
        state['searched_titles']['Q1'] = '2026-11-23'
        result2 = title_search_queue(state, {}, today=date(2026, 11, 24), limit=3)
        self.assertEqual([r['title'] for r in result2], ['A Different Special'])


class YoutubeChannelTests(unittest.TestCase):
    def test_trusted_channel_uploads_discover_unsearched_long_specials(self):
        # Fake API verifies that independently found channel uploads become
        # review candidates without typing a comedian or special into code.
        existing = [{'video_id': 'old123', 'channel_id': 'UCtrusted',
                     'channel': 'Dry Bar Comedy', 'publisher_match': True}]
        state = {'roster': [], 'works': []}
        saved = {}
        def read(path, default):
            if path == fetch_youtube.DATA_PATH: return existing
            if path == fetch_youtube.STATE_PATH: return state
            if path == fetch_youtube.CONFIG_PATH: return {}
            return []
        def write(path, obj):
            saved[str(path)] = obj
        calls = []
        def youtube_api(key, endpoint, **params):
            calls.append(endpoint)
            if endpoint == 'search': return {'items': []}
            if endpoint == 'channels':
                return {'items': [{'id': 'UCtrusted', 'contentDetails': {
                    'relatedPlaylists': {'uploads': 'UUtrusted'}}}]}
            if endpoint == 'playlistItems':
                return {'items': [{'snippet': {'resourceId': {'videoId': 'newvideo123'}}}]}
            if endpoint == 'videos':
                return {'items': [{'id': 'newvideo123', 'snippet': {
                    'title': 'A comedian - full stand-up comedy special',
                    'description': 'A full special',
                    'channelTitle': 'Dry Bar Comedy', 'channelId': 'UCtrusted',
                    'publishedAt': '2026-01-01T00:00:00Z'},
                    'contentDetails': {'duration': 'PT42M'},
                    'status': {'privacyStatus': 'public', 'embeddable': True}}]}
            raise AssertionError(endpoint)
        with patch.object(fetch_youtube, 'read_json', side_effect=read), patch.object(
                fetch_youtube, 'write_json', side_effect=write):
            fetch_youtube.gather_youtube('fakekey', search_fn=youtube_api,
                                         today=date(2026, 11, 23))
        self.assertIn('playlistItems', calls)
        rows = saved[str(fetch_youtube.DATA_PATH)]
        newly_discovered = next(r for r in rows if r.get('video_id') == 'newvideo123')
        self.assertEqual(newly_discovered['discovered_by'], 'channel_uploads')
        self.assertEqual(newly_discovered['review_status'], 'candidate_only')
        self.assertTrue(newly_discovered['embeddable'])


if __name__ == '__main__':
    unittest.main()



class WiderSourceDiscoveryTests(unittest.TestCase):
    def test_id_free_credit_special_reaches_title_search_queue(self):
        state = {'works': [{'qid':'Q8822', 'name': 'A Night at the Met',
                            'performer': 'Alex Comic', 'imdb': '', 'tmdb': ''}]}
        selected = title_search_queue(state, {}, today=date(2026, 11, 24))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['source'], 'wikidata')
        self.assertEqual(selected[0]['performer'], 'Alex Comic')

    def test_full_alphabet_performer_search_rotation(self):
        from fetch_tmdb import scheduled_names
        names = ['Adam Comic', 'Bob Comic', 'Fred Comic', 'Max Comic',
                 'Robin Comic', 'Zoe Comic']
        selected = scheduled_names(names, set(), {}, {},
                                   today=date(2026, 11, 24), max_searches=6)
        self.assertCountEqual(selected, names)
        self.assertNotEqual(selected, sorted(names))

    def test_television_evidence_prioritizes_names_without_adding_specials(self):
        from fetch_tmdb import scheduled_names
        cache = {'x': {'id': 'x', 'title': 'A Standup Special', 'performer': 'Alex Comic'}}
        selected = scheduled_names(['Alex Comic', 'Bill Comic', 'Chris Comic'],
                                   set(), {}, cache, today=date(2026, 11, 24),
                                   max_searches=1, tv_performers={'alex comic'})
        self.assertEqual(selected, ['Alex Comic'])

    def test_exact_title_comedian_prefix_and_unrelated_movie(self):
        api = FakeTMDB({'/search/movie': {'results': [
            {'id': 44, 'title': 'Alex Comic: A Night at The Met',
             'overview': 'Alex Comic performs a live stand-up set'},
            {'id': 45, 'title': 'A Night at The Met',
             'overview': 'A musical documentary'},
        ]}})
        found = search_exact_title_ids(api, {'title': 'A Night at The Met',
                                            'performer': 'Alex Comic'})
        self.assertEqual(found, {44})

    def test_wikidata_credited_works_merge(self):
        from discovery_sources import parse_works, merge_works
        direct = parse_works([{'work':{'value':'http://www.wikidata.org/entity/Q100'},
                               'name':{'value':'Alex Comic: Live'}}])
        credited = parse_works([{'work':{'value':'http://www.wikidata.org/entity/Q100'},
                                 'name':{'value':'Alex Comic: Live'},
                                 'performerName':{'value':'Alex Comic'}}])
        combined = merge_works(direct, credited)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]['performer'], 'Alex Comic')

if __name__ == '__main__':
    unittest.main()
