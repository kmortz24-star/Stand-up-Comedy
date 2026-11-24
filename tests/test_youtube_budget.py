"""Offline tests: daily API budget and durable small-batch YouTube discovery."""
import unittest
from datetime import date
from urllib.error import HTTPError
from unittest.mock import patch

import fetch_youtube


class YoutubeBudgetTests(unittest.TestCase):
    def run_with_fake_api(self, state, api, existing=None, on_saved=None):
        existing = existing or []
        saved = {}
        def read(path, default):
            if path == fetch_youtube.STATE_PATH: return state
            if path == fetch_youtube.DATA_PATH: return existing
            if path == fetch_youtube.CONFIG_PATH:
                return {"coverage_priority": {"established_extra": ["Ada Comic", "Ben Comic", "Chris Comic", "Dara Comic"]}}
            return []
        def write(path, value):
            saved[str(path)] = value
            if on_saved: on_saved(path, value)
        with patch.object(fetch_youtube, 'read_json', side_effect=read), patch.object(
                fetch_youtube, 'write_json', side_effect=write):
            fetch_youtube.gather_youtube('test-key', search_fn=api, today=date(2026, 11, 24))
        return saved[str(fetch_youtube.DATA_PATH)], saved[str(fetch_youtube.STATE_PATH)]

    def test_partial_success_survives_quota_failure_and_does_not_skip_unsearched_person(self):
        state = {'roster': [], 'works': [], 'youtube_general_searched': '2026-11-24'}
        searches = []
        def api(key, endpoint, **params):
            if endpoint == 'search':
                searches.append(params['q'])
                if len(searches) == 2:
                    raise HTTPError('https://example.test', 403, 'quotaExceeded', {}, None)
                return {'items': [{'id': {'videoId': 'comedyspecial1'}}]}
            if endpoint == 'videos':
                return {'items': [{'id': 'comedyspecial1', 'snippet': {
                    'title': 'Ada Comic — FULL COMEDY SPECIAL', 'channelTitle': 'Ada Comic',
                    'channelId': 'UCada', 'publishedAt': '2026-01-01T00:00:00Z',
                    'description': 'Full live stand-up'}, 'status': {'privacyStatus': 'public'},
                    'contentDetails': {'duration': 'PT50M'}}]}
            return {'items': []}
        results, updated = self.run_with_fake_api(state, api)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['candidate_kind'], 'full_special')
        self.assertEqual(results[0]['review_status'], 'candidate_only')
        self.assertTrue(updated['youtube_last_discovery']['quota_or_connection_blocked'])
        self.assertEqual(updated['youtube_last_discovery']['queries_completed'], 1)
        self.assertEqual(updated['youtube_daily_queries'], 1)
        self.assertEqual(len(updated['youtube_searched']), 1)

    def test_daily_search_limit_survives_manual_reruns(self):
        state = {'roster': [], 'works': [], 'youtube_general_searched': '2026-11-24'}
        searched = []
        def api(key, endpoint, **params):
            if endpoint == 'search':
                searched.append(params['q'])
            return {'items': []}
        _, first = self.run_with_fake_api(state, api)
        self.assertLessEqual(len(searched), fetch_youtube.DAILY_SEARCH_BUDGET)
        self.assertEqual(first['youtube_daily_queries'], len(searched))
        before = len(searched)
        self.run_with_fake_api(first, api)
        self.assertEqual(len(searched), before)

    def test_short_sets_suggest_gems_not_viral_and_remain_unpublished(self):
        self.assertEqual(fetch_youtube.candidate_kind('Nice Standup Set', 645), ('standup_set', 'Hidden Gems'))
        self.assertEqual(fetch_youtube.candidate_kind('FULL COMEDY SPECIAL', 3100),
                         ('full_special', 'Comedian alphabeticals'))

    def test_podcast_channel_without_explicit_standup_set_is_rejected(self):
        podcast = {'snippet': {'title': 'A comedian on fame and life',
                               'channelTitle': 'Show Podcast',
                               'description': 'This week: stand-up comedy, lives and jokes'},
                   'contentDetails': {'duration': 'PT90M'}}
        self.assertFalse(fetch_youtube.plausible_video(podcast))

if __name__ == '__main__':
    unittest.main()
