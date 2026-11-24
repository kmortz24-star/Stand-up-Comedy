"""Refresh the stand-up catalog's source list from TMDB.

Requires either TMDB_READ_ACCESS_TOKEN (preferred) or TMDB_API_KEY in the
environment. No secret is stored in generated files. Run build_catalogs.py
after this script. Public TMDB data is used with attribution in README.md.
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from build_catalogs import ROOT, norm, read_json, write_json
from discovery_sources import refresh_wikidata


API_BASE = "https://api.themoviedb.org/3"
DATA_PATH = ROOT / "data" / "specials.json"
USER_ADDITIONS = ROOT / "data" / "manual_additions.json"
STATE_PATH = ROOT / "data" / "discovery_state.json"
CONFIG_PATH = ROOT / "config.json"


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


# These are TMDB *metadata labels*, not a manually maintained comedian list.
KEYWORD_ALIASES = {"standupcomedy", "standupspecial", "comedyspecial"}
TITLE_QUERIES = ("stand-up comedy", "stand up comedy", "comedy special", "roast of", "roast battle")


def normalized_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def keyword_strengths(api: TMDB) -> dict[int, bool]:
    """Map discovered TMDB keyword IDs to whether the tag is stand-up-specific."""
    ids = {}
    for query in ("stand-up comedy", "stand-up special", "comedy special"):
        for row in api.get("/search/keyword", query=query, page=1).get("results", []):
            label = normalized_label(row.get("name", ""))
            if label in KEYWORD_ALIASES:
                ids[int(row["id"])] = ids.get(int(row["id"]), False) or label != "comedyspecial"
    if not ids:
        raise RuntimeError("No recognizable stand-up keywords; refusing generic comedy discovery")
    return ids


def lookup_keywords(api: TMDB) -> set[int]:
    """Compatibility helper: exact stand-up-related TMDB keyword IDs."""
    return set(keyword_strengths(api))


def name_prefix(title: str, name: str) -> bool:
    """A strong title match such as 'Jane Doe: Live'."""
    if not name or len(name) < 4:
        return False
    return bool(re.match(r"^" + re.escape(name) + r"(?=$|\s*[:–—-]\s*|['’]s\b|\s+(?:is|live|stand.?up|special|at|in|on)\b)",
                         title, flags=re.IGNORECASE))


def titled_special(result: dict, performer: str | None = None) -> bool:
    title = str(result.get("title") or result.get("original_title") or "")
    overview = str(result.get("overview") or "")
    if performer and name_prefix(title, performer):
        # Require either distinctive special wording or a description explicitly
        # describing stand-up, so a biopic isn't accepted just by a name match.
        context = title + " " + overview
        # Avoid documentary/actor roles bearing the performer's name. The
        # string "comic" alone is especially unsafe (it may be a surname).
        strong = re.search(r"(?i)stand[ -]?up|comedy special|live (?:at|in|from)|one.man.show|comedian (?:performs|takes|returns|presents|onstage)", context)
        documentary = re.search(r"(?i)\b(?:documentary|biography|behind.the.scenes|making.of|portrait of)\b", context)
        return bool(strong) and not (documentary and not re.search(r"(?i)stand[ -]?up|comedy special", context))
    return bool(re.search(r"(?i)\bstand[ -]?up\b|\bcomedy special\b|\broast (?:battle|of)\b", title)
                and re.search(r"(?i)stand.?up|comedian|comedians|live performance|roast|comedy special", overview))


def search_performer_ids(api: TMDB, performer: str) -> set[int]:
    ids = set()
    # A person's name is searched in the actual TMDB title index. This catches
    # credits without a stand-up keyword, with conservative title/overview checks.
    for query in (performer, f"{performer} stand-up"):
        first = api.get("/search/movie", query=query, page=1, include_adult="false")
        pages = min(2, int(first.get("total_pages", 1)))
        for page in range(1, pages + 1):
            rows = first if page == 1 else api.get("/search/movie", query=query, page=page, include_adult="false")
            ids.update(int(row["id"]) for row in rows.get("results", []) if titled_special(row, performer))
    return ids


def search_performer_credits(api: TMDB, performer: str) -> set[int]:
    """Search a comedian's actual TMDB movie credits rather than just tags.

    The movie must still *look like stand-up*; merely appearing in a comedy
    feature never qualifies. This path can find specials without a keyword or
    without the comedian's name in the indexed title.
    """
    people = api.get('/search/person', query=performer, page=1).get('results', [])
    matching = [person for person in people if norm(person.get('name') or '') == norm(performer)]
    # Ambiguous identical name credits aren't safely attributable.
    if len(matching) != 1:
        return set()
    movie_id = int(matching[0]['id'])
    credits = api.get(f'/person/{movie_id}/movie_credits')
    ids = set()
    for row in credits.get('cast', []):
        if row.get('adult') or not row.get('id'):
            continue
        character = str(row.get('character') or '')
        title = str(row.get('title') or row.get('original_title') or '')
        overview = str(row.get('overview') or '')
        # Performer self-credits and explicitly stand-up descriptions are strong
        # corroboration. A random acting role is not sufficient.
        self_credit = re.search(r'(?i)\bself\b|\bcomedian\b|\bhimself\b|\bherself\b', character)
        strong_context = re.search(r'(?i)stand[ -]?up (?:comedy|special|performance|set)|comedy special|live stand[ -]?up', overview)
        documentary = re.search(r'(?i)\b(?:documentary|biography|behind.the.scenes|making.of|portrait of)\b', overview)
        if ((titled_special(row, performer) and (self_credit or name_prefix(title, performer) or strong_context))
                or (self_credit and strong_context and not documentary)):
            ids.add(int(row['id']))
    return ids


def discovery_names(config: dict, state: dict, cache: dict) -> tuple[list[str], set[str]]:
    # Curate *comedians* for priority, never their special titles. Most search
    # effort goes to established and recognizable B-tier acts. A small, reviewed
    # underrated shortlist comes next. Viral/other unknown acts still enter the
    # broad rotating pool, but do not crowd out the coverage audit.
    priority = config.get("coverage_priority", {})
    curated = set(config.get("legends_comedians", []))
    roulette = config.get("roulette_groups", {})
    for tier in ("well_known", "b_tier", "classic_older"):
        curated.update(roulette.get(tier, []))
    curated.update(priority.get("established_extra", []))
    curated.update(priority.get("select_underrated", []))
    broad = set(config.get("viral_rising_comedians", []))
    for values in roulette.values():
        broad.update(values)
    # Adds people known from existing TMDB metadata and the full Wikidata roster.
    all_names = curated | broad | {r["name"] for r in state.get("roster", []) if r.get("name")}
    all_names |= {r["performer"] for r in cache.values() if r.get("performer")}
    # De-duplicate punctuation/case variants; ignore malformed cast names.
    unique = {}
    for name in sorted(all_names, key=lambda v: (len(v), v.casefold())):
        if 3 <= len(name) <= 80 and len(re.findall(r"[a-z]", name.casefold())) >= 3:
            unique.setdefault(norm(name), name)
    return list(unique.values()), {norm(x) for x in curated}


def scheduled_names(names: list[str], curated: set[str], state: dict, cache: dict,
                    *, today: date, max_searches: int,
                    tv_performers: set[str] | None = None) -> list[str]:
    checked = state.setdefault("searched_performers", {})
    counts = Counter(norm(r["performer"]) for r in cache.values() if r.get("performer"))
    tv_performers = tv_performers or set()
    def score(name: str):
        previous = checked.get(norm(name), "")
        # First recheck existing landmark/featured comics, then people who have
        # separately documented TV sets but few indexed standalone specials.
        # The TV evidence is automatic; this does NOT manually seed missing titles.
        key = norm(name)
        priority = (0 if key in curated else
                    1 if key in tv_performers and counts[key] <= 1 else
                    2 if counts[key] == 0 else 3)
        # Hash-spread names across the full alphabet instead of spending
        # the first several days on A/B/C before reaching M or R.
        spread = hashlib.sha256(norm(name).encode('utf-8')).hexdigest()
        # Coverage priority takes precedence over an older search timestamp:
        # otherwise hundreds of unknown names with old timestamps can crowd
        # established performers out of the current batch indefinitely.
        return priority, previous, spread
    # Only repeat a person's search after 45 days, unless there's no record.
    cutoff = (today - timedelta(days=45)).isoformat()
    due = [name for name in names if checked.get(norm(name), "") <= cutoff]
    return sorted(due, key=score)[:max_searches]


def discover_work_ids(api: TMDB, state: dict, known_ids: set[int], *,
                      today: date, max_checks: int = 120) -> set[int]:
    result = set()
    checked = state.setdefault("checked_works", {})
    deadline = (today - timedelta(days=90)).isoformat()
    works = [r for r in state.get("works", []) if (r.get("tmdb") or r.get("imdb"))
             and checked.get(r["qid"], "") <= deadline]
    works.sort(key=lambda row: (checked.get(row["qid"], ""), row["qid"]))
    for row in works[:max_checks]:
        qid = row["qid"]
        movie_id = int(row["tmdb"]) if row.get("tmdb", "").isdigit() else None
        if movie_id is not None:
            result.add(movie_id)
        elif row.get("imdb"):
            movies = api.get(f"/find/{row['imdb']}", external_source="imdb_id").get("movie_results", [])
            result.update(int(item["id"]) for item in movies)
        checked[qid] = today.isoformat()
    return result - known_ids


def title_search_queue(state: dict, cache: dict, *, today: date, limit: int = 80,
                       priority_performers: set[str] | None = None) -> list[dict]:
    """Rotate title leads independently discovered in Wikidata.

    This is *not* a list of user-provided exceptions. Wikidata often lacks
    movie IDs, and those leads should still get exact title searches.
    """
    candidates = {}
    existing_ids = {r.get("id") for r in cache.values()}
    existing_tmdbs = {str(r.get("tmdb_id")) for r in cache.values() if r.get("tmdb_id")}
    # Use independently discovered Wikidata titles, including those without IDs.
    for work in state.get("works", []):
        title = str(work.get("name") or "").strip()
        if not (5 <= len(title) <= 130):
            continue
        if (work.get("imdb") and work["imdb"] in existing_ids) or (work.get("tmdb") and work["tmdb"] in existing_tmdbs):
            continue
        key = str(work.get("qid") or work.get("imdb") or norm(title))
        source = str(work.get('source') or 'wikidata')
        candidates[key] = {"title": title, "imdb_id": work.get("imdb") or "",
                           "tmdb_id": work.get("tmdb") or "", "performer": work.get("performer") or "",
                           "source": source, "source_id": key}
    checked = state.setdefault("searched_titles", {})
    cutoff = (today - timedelta(days=60)).isoformat()
    # Respect both old normalized-title cursors and new Wikidata-QID cursors
    # during upgrade so previously checked works are not searched again at once.
    def last_checked(row):
        return checked.get(row["source_id"], checked.get(norm(row["title"]), ""))
    due = [row for row in candidates.values() if last_checked(row) <= cutoff]
    # Prioritize new leads without existing IDs as well as known IDs; sorting
    # only ID-bearing works first kept no-ID classics stuck for many cycles.
    preferred = priority_performers or set()
    due.sort(key=lambda row: (
                              0 if norm(row.get('performer') or '') in preferred else 1,
                              last_checked(row),
                              0 if not row["tmdb_id"] and not row["imdb_id"] else 1,
                              0 if row['performer'] else 1,
                              hashlib.sha256(row['source_id'].encode('utf-8')).hexdigest()))
    return due[:limit]


def search_exact_title_ids(api: TMDB, lead: dict) -> set[int]:
    """Exact ID first; fallback to matching title AND stand-up context."""
    found = set()
    imdb = str(lead.get("imdb_id") or "")
    if re.fullmatch(r"tt\d+", imdb):
        response = api.get(f"/find/{imdb}", external_source="imdb_id")
        found.update(int(row["id"]) for row in response.get("movie_results", []))
    tmdb = str(lead.get("tmdb_id") or "")
    if tmdb.isdecimal():
        found.add(int(tmdb))
    if found:
        return found
    title = str(lead.get("title") or "")
    if not title:
        return set()
    performer = str(lead.get('performer') or '').strip()
    searches = [title]
    if performer and norm(performer) not in norm(title):
        searches.append(f"{performer} {title}")
    key = norm(title)
    responses = [api.get("/search/movie", query=q, include_adult="false", page=1)
                 for q in dict.fromkeys(searches)]
    for row in [r for response in responses for r in response.get('results', [])]:
        actual = norm(row.get("title") or row.get("original_title") or "")
        # Many databases prefix the comedian to the work title.
        stripped = actual[len(norm(performer)):].strip() if performer and actual.startswith(norm(performer)) else actual
        if not actual or not (actual == key or stripped == key):
            continue
        overview = str(row.get("overview") or "")
        # The independent title's genre is evidence of a stand-up work, but
        # not proof that a same-named movie is the right one.
        standup_overview = re.search(r"(?i)stand[ -]?up|comedy special|live comedy|comedians? (?:perform|onstage)", overview)
        documentary = re.search(r"(?i)\b(documentary|biopic|portrait of|behind.the.scenes)\b", overview)
        if titled_special(row, lead.get("performer")) or (standup_overview and not documentary):
            found.add(int(row["id"]))
    return found

def likely_performer(title: str, cast: list[dict]) -> str | None:
    """Use explicit solo-comic titles, not generic show titles or roast hosts."""
    if ":" in title:
        prefix, remainder = (part.strip() for part in title.split(":", 1))
        if re.match(r"(?i)^(?:one.night stand|hbo comedy half.hour|comedy central presents)$", prefix):
            if 1 <= len(remainder.split()) <= 4 and len(remainder) <= 55:
                return remainder
        if (1 <= len(prefix.split()) <= 5 and
                not re.search(r"(?i)\b(roast|comedy|stand.?up|festival|special|presents|best of|collection|show|tour|documentary|all.star|one.night|ring)\b", prefix) and
                not prefix.lower().startswith(("the ", "an "))):
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


def fetch_all(api: TMDB, from_year: int, to_year: int, cache: dict, refresh_days: int,
              *, config: dict, state: dict, max_performer_searches: int = 200) -> dict:
    today = date.today()
    state = refresh_wikidata(state, today=today)
    keyword_kinds = keyword_strengths(api)
    ids = set()
    for year in range(from_year, to_year + 1):
        for keyword in sorted(keyword_kinds):
            first = api.get("/discover/movie", with_keywords=keyword, primary_release_year=year,
                            sort_by="primary_release_date.asc", page=1, include_adult="false")
            pages = min(int(first.get("total_pages", 1)), 500)
            ids.update(int(r["id"]) for r in first.get("results", [])
                       if keyword_kinds[keyword] or titled_special(r))
            for page in range(2, pages + 1):
                response = api.get("/discover/movie", with_keywords=keyword, primary_release_year=year,
                                   sort_by="primary_release_date.asc", page=page, include_adult="false")
                ids.update(int(r["id"]) for r in response.get("results", [])
                           if keyword_kinds[keyword] or titled_special(r))
    print(f"TMDB multi-keyword candidates: {len(ids)}", flush=True)

    # Search title text independently, but only accept strong title/description matches.
    for query in TITLE_QUERIES:
        first = api.get("/search/movie", query=query, page=1, include_adult="false")
        pages = min(5, int(first.get("total_pages", 1)))
        for page in range(1, pages + 1):
            rows = first if page == 1 else api.get("/search/movie", query=query, page=page, include_adult="false")
            ids.update(int(r["id"]) for r in rows.get("results", []) if titled_special(r))

    names, curated = discovery_names(config, state, cache)
    tv_rows = read_json(ROOT / 'data' / 'tv_episode_candidates.json', [])
    tv_priority = {norm(row['performer']) for row in tv_rows if row.get('performer')}
    due = scheduled_names(names, curated, state, cache, today=today,
                          max_searches=max_performer_searches, tv_performers=tv_priority)
    performer_hints = {}
    verified_credit_hints = {}
    for index, name in enumerate(due, 1):
        # Two independent routes: textual lookup and actual performer filmography.
        # A special can be in the credits even when its title omits the comedian.
        discovered_ids = search_performer_ids(api, name)
        try:
            credit_ids = search_performer_credits(api, name)
        except HTTPError as exc:
            if exc.code != 404:
                raise
            credit_ids = set()
        for movie_id in discovered_ids | credit_ids:
            ids.add(movie_id)
            performer_hints.setdefault(movie_id, name)
        for movie_id in credit_ids:
            verified_credit_hints.setdefault(movie_id, name)
        state["searched_performers"][norm(name)] = today.isoformat()
        if index % 30 == 0:
            print(f"Searched {index}/{len(due)} individual comedians across the rotating roster", flush=True)

    # Independently cataloged Wikidata works with TMDB/IMDb identifiers.
    ids.update(discover_work_ids(api, state, ids, today=today))
    # Search another rotating batch of *specific special titles*, including
    # Wikidata works absent from TMDB tags (never hand-entered exceptions).
    title_leads = title_search_queue(state, cache, today=today, limit=80,
                                     priority_performers=curated)
    matched_leads = 0
    matched_by_source = {}
    for lead in title_leads:
        matched = search_exact_title_ids(api, lead)
        if matched:
            matched_leads += 1
            source = lead.get('source', 'unknown')
            matched_by_source[source] = matched_by_source.get(source, 0) + 1
        ids.update(matched)
        for movie_id in matched:
            if lead.get('performer'):
                performer_hints.setdefault(movie_id, lead['performer'])
        state['searched_titles'][lead['source_id']] = today.isoformat()
    state["last_discovery_title_searches"] = len(title_leads)
    print(f"Exact-title searches: {len(title_leads)}; TMDB candidate IDs now {len(ids)}", flush=True)
    state["last_run"] = today.isoformat()
    state["last_discovery"] = {"wikidata_people": len(state.get("roster", [])),
                               "wikidata_works": len(state.get("works", [])),
                               "performers_searched": len(due), "total_tmdb_candidates": len(ids),
                               "exact_title_searches": len(title_leads),
                               "exact_title_matches": matched_leads,
                               "matched_by_source": matched_by_source}
    # Preserve existing entries and their tags; refresh metadata periodically.
    old_by_tmdb = {int(r["tmdb_id"]): r for r in cache.values() if r.get("tmdb_id") is not None}
    refreshed = 0
    for index, movie_id in enumerate(sorted(ids)):
        previous = old_by_tmdb.get(movie_id)
        if previous:
            try:
                last_checked = date.fromisoformat(previous.get("last_checked", ""))
            except ValueError:
                last_checked = date(1900, 1, 1)
            interval = 7 if not previous.get("performer") else refresh_days
            if today - last_checked < timedelta(days=interval):
                # Backfill previously unidentified performer only if its title
                # strongly proves the name; no guessing from a random cast member.
                hint = performer_hints.get(movie_id)
                if hint and not previous.get("performer") and (name_prefix(previous.get("title", ""), hint)
                    or verified_credit_hints.get(movie_id) == hint
                    or any(norm(lead['title']) == norm(previous.get('title', '')) and
                           norm(lead.get('performer', '')) == norm(hint) for lead in title_leads)):
                    previous["performer"] = hint
                continue
        try:
            record = movie_record(api, movie_id)
        except HTTPError as exc:
            if exc.code == 404:
                print(f"Skipping missing TMDB movie {movie_id}", flush=True)
                continue
            raise
        hint = performer_hints.get(movie_id)
        if not record.get("performer") and hint and (name_prefix(record["title"], hint) or
              verified_credit_hints.get(movie_id) == hint or
              any(norm(lead['title']) == norm(record['title']) and norm(lead.get('performer', '')) == norm(hint)
                  for lead in title_leads)):
            record["performer"] = hint
        if previous:
            # Don't erase a verified existing comedian credit when an updated
            # TMDB record has incomplete/misleading cast data.
            if not record.get("performer"):
                record["performer"] = previous.get("performer")
            cache.pop(previous["id"], None)
            record = {**previous, **record}
        cache[record["id"]] = record
        refreshed += 1
        if refreshed % 40 == 0:
            print(f"Refreshed {refreshed} movie records ({index + 1}/{len(ids)} candidates)", flush=True)
    print(f"TMDB candidates: {len(ids)}; fetched: {refreshed}; unique: {len(cache)}", flush=True)
    return cache

def backfill_original_languages(api: TMDB, cache: dict, *, state: dict, today: date,
                                limit: int = 350) -> int:
    """Resolve language for legacy movie records over successive refreshes.

    Full TMDB movie metadata is not needed just to learn original_language.
    Prioritize heavily voted titles so Top Rated/Favorites are corrected first.
    Never assume a title is English because the language field is blank.
    """
    if limit < 1:
        return 0
    attempts = state.setdefault("language_backfill_attempts", {})
    queue = sorted((r for r in cache.values()
                    if r.get("tmdb_id") and not r.get("original_language")),
                   key=lambda r: (-int(r.get("vote_count") or 0),
                                  str(r.get("title") or "")))
    done = 0
    for item in queue:
        tmdb_id = str(item["tmdb_id"])
        if tmdb_id in attempts:
            try:
                if today - date.fromisoformat(attempts[tmdb_id]) < timedelta(days=30):
                    continue
            except (TypeError, ValueError):
                pass
        if done >= limit:
            break
        try:
            response = api.get(f"/movie/{tmdb_id}")
        except HTTPError as exc:
            if exc.code != 404:
                raise
            attempts[tmdb_id] = today.isoformat()
            done += 1
            continue
        language = str(response.get("original_language") or "").strip()
        if language:
            item["original_language"] = language
        attempts[tmdb_id] = today.isoformat()
        done += 1
    print(f"Legacy language backfill: checked {done} movie records; "
          f"still missing {sum(not r.get('original_language') for r in cache.values())}", flush=True)
    return done


def merge_manual_additions(api, cache, additions):
    """Seed verified IMDb works and hydrate TMDB metadata when available.

    Never substitute IMDb vote counts for TMDB rankings. A fallback date with
    year precision is only a chronological placeholder until metadata resolves.
    The explicit performer credit and approved ID survive future refreshes.
    """
    for item in additions:
        identifier = item.get("id")
        if not identifier:
            continue
        previous = cache.get(identifier, {})
        enriched = previous
        if not previous.get("tmdb_id") and identifier.startswith("tt"):
            try:
                found = api.get(f"/find/{identifier}", external_source="imdb_id")
                for match in found.get("movie_results", []):
                    candidate = movie_record(api, int(match["id"]))
                    if candidate.get("id") == identifier:
                        enriched = {**previous, **candidate}
                        break
            except (HTTPError, URLError, TimeoutError) as exc:
                print(f"Manual metadata lookup for {identifier}: {exc}; using verified seed")
        merged = {**item, **enriched}
        merged["id"] = identifier
        if item.get("performer"):
            merged["performer"] = item["performer"]
        if not merged.get("release_date"):
            merged["release_date"] = item.get("release_date", "")
        if enriched.get("release_date") and enriched.get("release_date") != item.get("release_date"):
            merged.pop("release_date_precision", None)
        if not merged.get("title"):
            merged["title"] = item.get("title", "")
        if not merged.get("original_language"):
            merged["original_language"] = item.get("original_language", "")
        merged["tags"] = sorted(set(item.get("tags") or []) | set(enriched.get("tags") or []))
        # A resolved TMDB alias for this exact movie is the same work.
        if merged.get("tmdb_id"):
            cache.pop(f'tmdb:{merged["tmdb_id"]}', None)
        cache[identifier] = merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-year", type=int, default=1960)
    parser.add_argument("--to-year", type=int, default=date.today().year)
    parser.add_argument("--refresh-days", type=int, default=30)
    parser.add_argument("--max-comedians", type=int, default=200)
    args = parser.parse_args()
    if args.from_year > args.to_year or args.refresh_days < 1 or args.max_comedians < 0:
        raise SystemExit("Invalid year range")
    existing = {r["id"]: r for r in read_json(DATA_PATH, []) if r.get("id")}
    state = read_json(STATE_PATH, {})
    config = read_json(CONFIG_PATH, {})
    tmdb_api = TMDB()
    fresh = fetch_all(tmdb_api, args.from_year, args.to_year, existing, args.refresh_days,
                      config=config, state=state, max_performer_searches=args.max_comedians)
    if config.get("english_language_only", False):
        backfill_original_languages(tmdb_api, fresh, state=state, today=date.today(),
                                    limit=int(config.get("language_backfill_per_run", 350)))
    merge_manual_additions(tmdb_api, fresh, read_json(USER_ADDITIONS, []))
    write_json(DATA_PATH, sorted(fresh.values(), key=lambda r: (str(r.get("tmdb_id") or ""), r["id"])))
    write_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
