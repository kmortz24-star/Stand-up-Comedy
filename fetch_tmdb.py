"""Refresh the stand-up catalog's source list from TMDB.

Requires either TMDB_READ_ACCESS_TOKEN (preferred) or TMDB_API_KEY in the
environment. No secret is stored in generated files. Run build_catalogs.py
after this script. Public TMDB data is used with attribution in README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from build_catalogs import ROOT, read_json, write_json


API_BASE = "https://api.themoviedb.org/3"
DATA_PATH = ROOT / "data" / "specials.json"
USER_ADDITIONS = ROOT / "data" / "manual_additions.json"


class TMDB:
    def __init__(self):
        self.token = os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip()
        self.key = os.getenv("TMDB_API_KEY", "").strip()
        if not (self.token or self.key):
            raise SystemExit("Set TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY in your environment (GitHub Actions secret).")
        self.last_request = 0.0

    def get(self, route: str, **params) -> dict:
        params = {key: value for key, value in params.items() if value is not None}
        if not self.token:
            params["api_key"] = self.key
        url = API_BASE + route + ("?" + urlencode(params) if params else "")
        headers = {"accept": "application/json", "user-agent": "StandupAutoCatalog/1.0"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(6):
            since_last = time.monotonic() - self.last_request
            if since_last < 0.15:
                time.sleep(0.15 - since_last)
            self.last_request = time.monotonic()
            try:
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise SystemExit(f"TMDB rejected API credentials (HTTP {exc.code}).") from exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
                time.sleep(min(30, 2 ** attempt))
            except (URLError, TimeoutError):
                if attempt == 5:
                    raise
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError("Unreachable API retry path")


def lookup_keyword(api: TMDB) -> int:
    found = api.get("/search/keyword", query="stand-up comedy", page=1).get("results", [])
    for result in found:
        if result.get("name", "").lower().replace(" ", "-") in ("stand-up-comedy", "standup-comedy"):
            return int(result["id"])
    raise RuntimeError("TMDB has no recognizable stand-up comedy keyword; stop instead of loading generic comedies.")


def likely_performer(title: str, cast: list[dict]) -> str | None:
    """Prefer explicit 'Comedian: Special' title; otherwise credited self performer."""
    if ":" in title:
        prefix = title.split(":", 1)[0].strip()
        if 1 <= len(prefix.split()) <= 5 and not re.search(
            r"(?i)\b(roast|comedy|stand.?up|festival|special|presents|best of|collection)\b", prefix
        ):
            return prefix
    for person in cast[:6]:
        character = str(person.get("character") or "")
        if re.search(r"(?i)\b(self|himself|herself|themself|comedian)\b", character):
            return str(person.get("name") or "").strip() or None
    return None


def movie_record(api: TMDB, movie_id: int) -> dict:
    movie = api.get(f"/movie/{movie_id}", append_to_response="credits,external_ids")
    external = movie.get("external_ids") or {}
    imdb_id = external.get("imdb_id")
    title = movie.get("title") or movie.get("original_title") or ""
    cast = (movie.get("credits") or {}).get("cast", [])
    record = {
        "id": imdb_id or f"tmdb:{movie_id}",
        "tmdb_id": movie_id,
        "title": title,
        "performer": likely_performer(title, cast),
        "release_date": movie.get("release_date", ""),
        "poster_path": movie.get("poster_path"),
        "popularity": movie.get("popularity", 0),
        "original_language": movie.get("original_language", ""),
        "vote_average": movie.get("vote_average", 0),
        "vote_count": movie.get("vote_count", 0),
        "tags": [],
        "last_checked": date.today().isoformat(),
    }
    return record


def fetch_all(api: TMDB, from_year: int, to_year: int, cache: dict, refresh_days: int) -> dict:
    keyword = lookup_keyword(api)
    ids = set()
    for year in range(from_year, to_year + 1):
        first = api.get("/discover/movie", with_keywords=keyword, primary_release_year=year,
                        sort_by="primary_release_date.asc", page=1, include_adult="false")
        pages = min(int(first.get("total_pages", 1)), 500)
        for result in first.get("results", []):
            ids.add(int(result["id"]))
        for page in range(2, pages + 1):
            response = api.get("/discover/movie", with_keywords=keyword, primary_release_year=year,
                               sort_by="primary_release_date.asc", page=page, include_adult="false")
            for result in response.get("results", []):
                ids.add(int(result["id"]))
        print(f"{year}: {len(first.get('results', []))} first-page items, {pages} pages", flush=True)

    # Cache existing records; new TMDB entries are enriched with cast and IMDb IDs.
    old_by_tmdb = {int(r["tmdb_id"]): r for r in cache.values() if r.get("tmdb_id") is not None}
    refreshed = 0
    for index, movie_id in enumerate(sorted(ids)):
        previous = old_by_tmdb.get(movie_id)
        if previous:
            try:
                last_checked = date.fromisoformat(previous.get("last_checked", ""))
            except ValueError:
                last_checked = date(1900, 1, 1)
            # Titles with uncertain performer metadata get retried more often.
            interval = 7 if not previous.get("performer") else refresh_days
            if date.today() - last_checked < timedelta(days=interval):
                continue
        record = movie_record(api, movie_id)
        if previous:
            cache.pop(previous["id"], None)
            record = {**previous, **record}
        cache[record["id"]] = record
        refreshed += 1
        if refreshed % 25 == 0:
            print(f"Checked metadata: {refreshed} titles ({index + 1}/{len(ids)} candidates)", flush=True)
    print(f"TMDB candidates: {len(ids)}; metadata fetched: {refreshed}; cached unique records: {len(cache)}", flush=True)
    return cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-year", type=int, default=1960)
    parser.add_argument("--to-year", type=int, default=date.today().year)
    parser.add_argument("--refresh-days", type=int, default=30)
    args = parser.parse_args()
    if args.from_year > args.to_year or args.refresh_days < 1:
        raise SystemExit("Invalid year range")
    existing = {r["id"]: r for r in read_json(DATA_PATH, []) if r.get("id")}
    fresh = fetch_all(TMDB(), args.from_year, args.to_year, existing, args.refresh_days)
    for item in read_json(USER_ADDITIONS, []):
        if item.get("id"):
            fresh[item["id"]] = {**fresh.get(item["id"], {}), **item}
    write_json(DATA_PATH, list(fresh.values()))


if __name__ == "__main__":
    main()
