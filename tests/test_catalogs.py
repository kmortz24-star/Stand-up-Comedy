"""Offline sorting tests; these test records are not published content."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from build_catalogs import alphabetical_sort_key, bucket_for, build, categories, validate_groups


def sample(identifier, performer, date_value, *, title=None, **kwargs):
    return {
        "id": identifier, "performer": performer,
        "title": title or f"{performer}: Example", "release_date": date_value,
        "popularity": 3, "vote_average": 8, "vote_count": 20, **kwargs,
    }


CONFIG = {
    "addon_id": "com.example.test", "addon_name": "Test Stand Up",
    "alphabet_groups": ["ABCD", "EFGH", "IJKL", "MNOP", "QRST", "UVWXYZ"],
    "weekly_roulette_count": 3, "weekly_hidden_gems_count": 3,
    "weekly_viral_rising_count": 3,
    "new_specials_months": 18, "hidden_gems_max_popularity": 15,
    "hidden_gems_min_rating": 6.5, "hidden_gems_min_votes": 3,
    "legends_comedians": ["Bill Burr"],
    "viral_rising_comedians": ["Kam Patterson", "Emily Catalano"],
    "roast_title_terms": ["roast"],
}


class TestCatalogs(unittest.TestCase):
    def setUp(self):
        self.records = [
            sample("test:1", "Tom Segura", "2021-01-01", title="Tom Segura: Earlier"),
            sample("test:2", "Tom Segura", "2023-01-01", title="Tom Segura: Later"),
            sample("test:3", "Bill Burr", "2024-01-01"),
            sample("test:4", "Shane Gillis", "2025-09-01"),
            sample("test:5", "Adam Ray", "2026-10-01"),
            sample("test:6", "Xavier Example", "2026-09-01"),
            sample("test:7", None, "2024-01-01", title="Unidentified Special"),
            sample("test:8", "Kam Patterson", "2025-01-01"),
            sample("test:9", "Emily Catalano", "2025-03-01"),
        ]

    def test_first_name_bucket_and_release_date(self):
        outputs, unassigned = categories(self.records, CONFIG, date(2026, 11, 18))
        by_name = {name: items for _, name, items in outputs}
        self.assertEqual([r["id"] for r in by_name["QRST"]], ["test:4", "test:1", "test:2"])
        self.assertEqual([r["id"] for r in by_name["Comedians ABCD"]], ["test:5", "test:3"])
        self.assertEqual(len(unassigned), 1)

    def test_rebalance_without_changing_ids(self):
        modified = {**CONFIG, "alphabet_groups": ["ABC", "DEFGH", "IJKL", "MNOP", "QRST", "UVWXYZ"]}
        old, _ = categories(self.records, CONFIG)
        new, _ = categories(self.records, modified)
        self.assertEqual([id for id, _, _ in old], [id for id, _, _ in new])
        self.assertEqual(new[5][1], "Comedians ABC")

    def test_viral_rising_category_follows_legends(self):
        outputs, _ = categories(self.records, CONFIG, date(2026, 11, 18))
        self.assertEqual(outputs[3][1], "Comedy Legends")
        self.assertEqual(outputs[4][:2], ("viral-and-rising", "Viral & Rising Comedians"))
        viral = outputs[4][2]
        self.assertEqual({r["id"] for r in viral}, {"test:8", "test:9"})
        self.assertTrue(all(r["performer"] not in ("Shane Gillis", "Adam Ray") for r in viral))

    def test_catalog_manifest_pages_and_no_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            report = build(self.records, CONFIG, target, date(2026, 11, 18))
            manifest = json.loads((target / "manifest.json").read_text())
            self.assertEqual(len(manifest["catalogs"]), 12)
            self.assertEqual(manifest["resources"], ["catalog"])
            self.assertEqual(report["counts"]["QRST"], 3)
            self.assertEqual(report["counts"]["Comedy Legends"], 1)
            self.assertEqual(report["counts"]["Viral & Rising Comedians"], 2)
            qrst = json.loads((target / "catalog/movie/comedians-05.json").read_text())
            self.assertEqual([item["id"] for item in qrst["metas"]], ["test:4", "test:1", "test:2"])

    def test_pagination_beyond_fifty_entries(self):
        many = [sample(f"test:{i}", f"Adam Comic {i:03d}", "2025-01-01") for i in range(55)]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            build(many, CONFIG, target, date(2026, 11, 18))
            first = json.loads((target / "catalog/movie/comedians-01.json").read_text())
            second = json.loads((target / "catalog/movie/comedians-01/skip=50.json").read_text())
            self.assertEqual(len(first["metas"]), 50)
            self.assertEqual(len(second["metas"]), 5)

    def test_weekly_picks_keep_one_title_per_comedian(self):
        rows, _ = categories(self.records, CONFIG, date(2026, 11, 18))
        selected = next(items for _, name, items in rows if name == "Comedy Roulette")
        self.assertEqual(len(selected), len({r["performer"] for r in selected}))
        again, _ = categories(self.records, CONFIG, date(2026, 11, 18))
        self.assertEqual([r["id"] for r in selected], [r["id"] for r in again[0][2]])

    def test_duplicate_ids_and_unknown_performer(self):
        repeated = [*self.records, {**self.records[1]}]
        output, unassigned = categories(repeated, CONFIG, date(2026, 11, 18))
        qrst = next(entries for id, name, entries in output if name == "QRST")
        self.assertEqual(len(qrst), 3)
        self.assertEqual(len(unassigned), 1)

    def test_letters_cover_alphabet(self):
        validate_groups(CONFIG["alphabet_groups"])
        self.assertEqual(bucket_for("Æ Example", CONFIG["alphabet_groups"]), 0)
        with self.assertRaises(ValueError):
            validate_groups(["ABCD", "DEFG", "HIJKLMNOPQRSTUVWXYZ"])


if __name__ == "__main__":
    unittest.main()
