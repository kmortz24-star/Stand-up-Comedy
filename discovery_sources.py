"""Independent Wikidata discovery of comedians and stand-up specials.

Wikidata is used for *leads*, not as proof that an arbitrary TMDB movie is a
special. A TMDB movie match must be found before catalog publication. The cache
makes public SPARQL requests weekly, not hundreds of times per daily build.
"""
from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "NuvioStandupCatalog/1.2 (https://github.com/kmortz24-star/Stand-up-Comedy; metadata discovery)"
DISCOVERY_SCHEMA_VERSION = 2

# Exact occupational and genre identifiers, NOT a search for a few names.
PEOPLE_QUERY = """
SELECT DISTINCT ?person ?name WHERE {
  ?person wdt:P106 wd:Q18545066 ; rdfs:label ?name .
  FILTER(LANG(?name) = "en")
} LIMIT 6000
"""
# A useful special may have a title but no IMDb/TMDB ID. Do not discard it.
# Include stand-up genres attached either as genre or as type, and surface
# named performers when Wikidata has that metadata.
WORKS_QUERY = """
SELECT DISTINCT ?work ?name ?imdb ?tmdb ?performerName WHERE {
  VALUES ?genre { wd:Q145806 wd:Q140299056 }
  { ?work wdt:P136 ?genre . } UNION { ?work wdt:P31 ?genre . }
  ?work rdfs:label ?name .
  FILTER(LANG(?name) = "en")
  OPTIONAL { ?work wdt:P345 ?imdb . }
  OPTIONAL { ?work wdt:P4947 ?tmdb . }
  OPTIONAL {
    { ?work wdt:P175 ?performer . } UNION { ?work wdt:P371 ?performer . }
    ?performer rdfs:label ?performerName .
    FILTER(LANG(?performerName) = "en")
  }
} LIMIT 6000
"""


def sparql(query: str, opener=urlopen) -> list[dict]:
    url = WIKIDATA_ENDPOINT + "?" + urlencode({"query": query, "format": "json"})
    headers = {"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            with opener(Request(url, headers=headers), timeout=45) as response:
                return json.load(response)["results"]["bindings"]
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    return []


def binding(row: dict, key: str) -> str:
    return str((row.get(key) or {}).get("value") or "").strip()


def entity_id(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def parse_people(rows: list[dict]) -> list[dict]:
    people = {}
    for row in rows:
        name, qid = binding(row, "name"), entity_id(binding(row, "person"))
        if name and qid.startswith("Q") and len(name) <= 80:
            people[qid] = {"qid": qid, "name": name}
    return sorted(people.values(), key=lambda row: (row["name"].casefold(), row["qid"]))


def parse_works(rows: list[dict]) -> list[dict]:
    works = {}
    for row in rows:
        qid = entity_id(binding(row, "work"))
        name = binding(row, "name")
        imdb, tmdb = binding(row, "imdb"), binding(row, "tmdb")
        if not (qid.startswith("Q") and 5 <= len(name) <= 160):
            continue
        # Invalid IDs are not treated as proof of a movie match, but the title
        # remains a legitimate metadata lead worth searching exactly.
        imdb = imdb if imdb.startswith("tt") and imdb[2:].isdigit() else ""
        tmdb = tmdb if tmdb.isdecimal() else ""
        existing = works.get(qid, {})
        performer = binding(row, "performerName") or existing.get("performer", "")
        works[qid] = {"qid": qid, "name": name,
                      "imdb": imdb or existing.get("imdb", ""),
                      "tmdb": tmdb or existing.get("tmdb", ""),
                      "performer": performer}
    return sorted(works.values(), key=lambda row: row["qid"])



def refresh_wikidata(state: dict, *, today, max_age_days: int = 7, query_fn=sparql) -> dict:
    """Keep last successful cache if Wikidata is down or rate-limited."""
    from datetime import date, timedelta
    try:
        last = date.fromisoformat(state.get("wikidata_refreshed", ""))
    except ValueError:
        last = date(1900, 1, 1)
    if (last >= today - timedelta(days=max_age_days) and state.get("roster")
            and state.get("wikidata_schema") == DISCOVERY_SCHEMA_VERSION):
        return state
    updated = False
    for key, query, parser in (("roster", PEOPLE_QUERY, parse_people), ("works", WORKS_QUERY, parse_works)):
        try:
            parsed = parser(query_fn(query))
            if parsed:
                state[key] = parsed
                print(f"Wikidata {key}: {len(parsed)} leads", flush=True)
                updated = True
            else:
                print(f"Wikidata {key}: no leads; preserving cached records", flush=True)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
            print(f"Wikidata {key} unavailable ({type(exc).__name__}); cached discovery continues", flush=True)
    if updated:
        state["wikidata_refreshed"] = today.isoformat()
        # Failed sources can retain their older cache, but a new schema is
        # considered active only after the expanded works query succeeds.
        if state.get('works') and any('performer' in w for w in state['works']):
            state["wikidata_schema"] = DISCOVERY_SCHEMA_VERSION
    return state
