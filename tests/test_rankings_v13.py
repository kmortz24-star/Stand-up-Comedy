"""Regression tests for the existing Top Rated / Fan Favorites rows."""
import unittest
from datetime import date
from build_catalogs import categories, ranked_specials, non_standup_movie


def mk(id, name, title, score, votes):
    return {"id": id, "performer": name, "title": title, "release_date": "2020-01-01",
            "vote_average": score, "vote_count": votes, "original_language": "en"}


class RankV13Tests(unittest.TestCase):
    def setUp(self):
        self.config = {"top_rated_min_votes": 20, "fan_favorites_min_votes": 10,
                       "fan_favorites_min_rating": 6.5, "ranked_list_size": 2,
                       "fan_favorites_size": 3, "rankings_english_only": True,
                       "roulette_groups": {"well_known": ["Well Known"], "b_tier": ["B Tier"]},
                       "non_standup_performers": ["Bruce Springsteen", "Springsteen"],
                       "non_standup_titles": ["Bo Burnham: The Inside Outtakes"],
                       "ranking_excluded_titles": ["George Carlin: 40 Years of Comedy"]}

    def test_non_standup_does_not_remove_music_in_real_standup(self):
        self.assertTrue(non_standup_movie(mk('a','Bruce Springsteen','Springsteen on Broadway',8,40),self.config))
        self.assertTrue(non_standup_movie(mk('b','Bo Burnham','Bo Burnham: The Inside Outtakes',8,40),self.config))
        self.assertFalse(non_standup_movie(mk('c','Bo Burnham','Bo Burnham: Inside',8,40),self.config))
        self.assertFalse(non_standup_movie(mk('d','Bill Bailey','Bill Bailey: Part Troll',8,40),self.config))

    def test_rankings_apply_tier_prior_and_keep_existing_ids(self):
        records = [mk('x','Small Vote','Small Vote: Special',8.9,20),
                   mk('y','Well Known','Well Known: Special',8.3,100),
                   mk('z','B Tier','B Tier: Special',7.9,24),
                   mk('d','Unknown','Unknown: Special',7.4,100),
                   mk('m','Bruce Springsteen','Springsteen on Broadway',9,200),
                   mk('o','Bo Burnham','Bo Burnham: The Inside Outtakes',8.5,200),
                   mk('r','George Carlin','George Carlin: 40 Years of Comedy',8.5,200)]
        rated, favorites = ranked_specials(records,self.config)
        self.assertEqual(len(rated),2)
        self.assertEqual(len(favorites),3)
        self.assertEqual(rated[0]['id'],'y')
        self.assertNotIn('m',{r['id'] for r in rated+favorites})
        self.assertNotIn('o',{r['id'] for r in rated+favorites})
        self.assertNotIn('r',{r['id'] for r in rated+favorites})


if __name__=='__main__':
    unittest.main()
