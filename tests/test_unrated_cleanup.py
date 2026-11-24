"""Check the user's deliberate zero-vote trimming preference (no deleting)."""
import tempfile
import json
import unittest
from datetime import date
from pathlib import Path
from build_catalogs import categories, build, exclude_unrated_unknown

BASE = {
    "addon_id": "example.test", "addon_name": "Stand Up",
    "alphabet_groups": ["AB", "CDEFG", "HIJ", "KLM", "NOPQR", "STUVWXYZ"],
    "alphabet_unrated_only_established": True,
    "roulette_groups": {
        "well_known": ["Robin Williams"], "b_tier": ["Doug Stanhope"],
        "classic_older": []
    },
    "coverage_priority": {"established_extra": ["Louie Anderson"]},
    "unrated_additional_established": ["Ross Noble"],
    "weekly_roulette_count": 4, "roulette_group_size": 1,
    "weekly_hidden_gems_count": 3, "weekly_viral_rising_count": 3,
    "new_specials_months": 18, "hidden_gems_max_popularity": 15,
    "hidden_gems_min_rating": 6.5, "hidden_gems_min_votes": 3,
    "roast_title_terms": ["roast"],
}

def rec(id, performer, votes=0, score=0):
    return {"id": id,"title": f"{performer}: Live {id}", "performer": performer,
            "release_date": "2017-01-01", "vote_count": votes,
            "vote_average": score, "popularity": 1, "tags": []}

class UnratedCleanupTests(unittest.TestCase):
    def test_unrated_known_and_unknown(self):
        items = [rec("a", "Robin Williams"), rec("b", "Doug Stanhope"),
                 rec("c", "Louie Anderson"), rec("d", "Ross Noble"),
                 rec("e", "Unknown Comic"), rec("f", "Unknown Comic", 1, 3.0),
                 rec("g", "Z Newcomer"), rec("h", None)]
        grouped, review = categories(items, BASE, date(2026,11,23))
        ids = {row["id"] for key,_,records in grouped if key.startswith('comedians-') for row in records}
        self.assertEqual(ids, {'a','b','c','d','f'})
        self.assertEqual({r['id'] for r in review}, {'h'})
        self.assertFalse(exclude_unrated_unknown(rec('b','Doug Stanhope'), BASE))
        self.assertTrue(exclude_unrated_unknown(rec('e','Unknown Comic'), BASE))

    def test_preference_is_disabled_for_old_fixture_and_reversible(self):
        item = rec('e','Unknown Comic')
        self.assertFalse(exclude_unrated_unknown(item, {**BASE, 'alphabet_unrated_only_established':False}))

    def test_build_generates_exact_audit_and_leaves_input_untouched(self):
        items=[rec('a','Robin Williams'), rec('e','Unknown Comic'), rec('f','Unknown Comic',1,8.0)]
        snapshot=json.dumps(items)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            report=build(items, BASE, out, date(2026,11,23))
            self.assertEqual(report['unrated_cleanup']['unrated_movies_hidden'],1)
            self.assertEqual(report['unrated_cleanup']['unrated_established_movies_kept'],1)
            audit=json.loads((out/'unrated_cleanup_report.json').read_text())
            self.assertEqual(audit['hidden'][0]['id'],'e')
            self.assertEqual(json.dumps(items),snapshot)

if __name__=='__main__': unittest.main()
