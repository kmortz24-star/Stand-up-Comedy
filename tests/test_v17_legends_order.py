"""Original legends first; approved expansion without alphabetizing the row."""
import json
import unittest
from datetime import date
from pathlib import Path
from build_catalogs import categories

ROOT = Path(__file__).resolve().parents[1]
class LegendsOrder(unittest.TestCase):
    def test_priority_and_membership(self):
        c = json.loads((ROOT / 'config.json').read_text())
        records = json.loads((ROOT / 'data/specials.json').read_text())
        rows, _ = categories(records, c, date(2026, 11, 24))
        legends = next(r for k, _, r in rows if k == 'comedy-legends')
        names = list(dict.fromkeys(r['performer'] for r in legends))
        self.assertEqual(names, [n for n in c['legends_comedians'] if n in names])
        self.assertEqual(names[:4], ['George Carlin', 'Richard Pryor', 'Eddie Murphy', 'Robin Williams'])
        self.assertTrue(set(c['legends_comedians'][13:]) <= set(names))
        self.assertFalse(set(names) & {'Joan Rivers','Bernie Mac','Jerry Seinfeld','Doug Stanhope','Dave Chappelle','Chris Rock'})
        self.assertFalse({r['id'] for r in legends} & set(c['legends_excluded_ids']))
