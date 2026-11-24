"""Discover episodes from long-running stand-up showcase television series.

Episode records are metadata candidates, not standalone movies. The builder
publishes them as episodes of real TMDB series with normal episode IDs. This
never asserts that a playable streaming source exists.

Uses the same TMDB token configured for the movie refresh; no new credentials.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from build_catalogs import ROOT, read_json, write_json

OUTPUT = ROOT / 'data' / 'tv_episode_candidates.json'

# Search by *series*, not by a manually-maintained list of comedians.
# Alternative names may be added as TMDB's metadata naming varies.
# Curated SHOW titles, not curated comedian/episode records. These are all real
# stand-up showcases, multi-comedian performance series, or comedy competitions.
# Match a TMDB *TV series* by its full name, then index its published seasons.
# Alternate names are for spelling/network branding, NOT extra fake TV series.
SHOWS = (
    ('Comedy Central Presents', ('Comedy Central Presents',)),
    ('HBO Comedy Half-Hour', ('HBO Comedy Half-Hour', 'HBO Comedy Half Hour', 'Comedy Half Hour')),
    ('One Night Stand', ('One Night Stand', 'HBO One Night Stand')),
    ('Def Comedy Jam', ('Def Comedy Jam', 'Russell Simmons\' Def Comedy Jam')),
    ('Premium Blend', ('Premium Blend',)),
    ('Comedy Central Stand-Up Presents', ('Comedy Central Stand-Up Presents', 'Comedy Central Stand Up Presents')),
    ('The Half Hour', ('The Half Hour',)),
    ('Live at Gotham', ('Live at Gotham',)),
    ('Gotham Comedy Live', ('Gotham Comedy Live',)),
    ('Live at the Apollo', ('Live at the Apollo',)),
    ('ComicView', ('ComicView', 'BET ComicView')),
    ('Comedy Now!', ('Comedy Now!',)),
    ('Comedians of the World', ('Comedians of the World', 'COMEDIANS of the world')),
    ('The Standups', ('The Standups',)),
    ('The Comedy Lineup', ('The Comedy Lineup',)),
    ('The Degenerates', ('The Degenerates',)),
    ('Just for Laughs: All Access', ('Just for Laughs: All Access', 'Just For Laughs All Access')),
    ('Live from the BBC', ('Live from the BBC',)),
    ('Gabriel Iglesias Presents Stand-Up Revolution',
     ('Gabriel Iglesias Presents Stand-Up Revolution', 'Gabriel Iglesias Presents Stand Up Revolution')),
    ("John Oliver's New York Stand-Up Show", ("John Oliver's New York Stand-Up Show",)),
    ('Comedy Underground with Dave Attell', ('Comedy Underground with Dave Attell',)),
    ('Tiffany Haddish Presents: They Ready', ('Tiffany Haddish Presents: They Ready',)),
    ('The New Negroes with Baron Vaughn and Open Mike Eagle',
     ('The New Negroes with Baron Vaughn and Open Mike Eagle', 'The New Negroes')),
    ('This Is Not Happening', ('This Is Not Happening',)),
    ('Last Comic Standing', ('Last Comic Standing',)),
    ('Roast Battle', ('Roast Battle', 'Jeff Ross Presents Roast Battle')),
)

# Safeguards for short/ambiguous search names: TMDB occasionally has an
# unrelated drama/reality show with the exact same name. Years are reference
# dates of the ACTUAL stand-up shows, not invented episode dates.
SHOW_FIRST_YEARS = {
    'Comedy Central Presents': 1998,
    'HBO Comedy Half-Hour': 1994,
    'One Night Stand': 1989,
    'Def Comedy Jam': 1992,
    'Premium Blend': 1997,
    'The Half Hour': 2012,
    'Live at Gotham': 2006,
    'Gotham Comedy Live': 2012,
    'Live at the Apollo': 2004,
    'Comedy Now!': 1997,
    'The Standups': 2017,
    'The Comedy Lineup': 2018,
    'Comedians of the World': 2019,
    'The Degenerates': 2018,
    'Live from the BBC': 2016,
    'Last Comic Standing': 2003,
}
AMBIGUOUS_SHOWS = {'One Night Stand', 'The Half Hour', 'Comedy Now!', 'Roast Battle'}
COMEDY_CONTEXT = re.compile(r'(?i)stand.?up|comedi(?:an|ans|y)|comic|hbo|comedy central|roast')

GENERIC_EPISODE = re.compile(
    r'(?i)^(?:episode\s*\d+|show\s*\d+|season\s*\d+|special\s*\d*|'
    r'best\s+of\b.*|highlights?\b.*|pilot|part\s*\d+|tba|untitled|'
    r'comedy central presents|one night stand|hbo comedy half.hour)$'
)
NAME_WORD = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ.'’\-]*$")


def normalized(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(text).casefold())


def find_show(api, variants: tuple[str, ...], display_name: str | None = None) -> dict | None:
    """Resolve exact title aliases; reject wrong same-name series by era/context.

    Do not turn nearby text searches into arbitrary series. If an exact title
    cannot be confidently resolved, skip it and log it for a future refresh.
    """
    display_name = display_name or variants[0]
    expected = SHOW_FIRST_YEARS.get(display_name)
    allowed = {normalized(alias) for alias in variants}
    matches = {}
    for query in variants:
        for row in api.get('/search/tv', query=query, page=1).get('results', []):
            if normalized(row.get('name', '')) not in allowed:
                continue
            year_text = str(row.get('first_air_date') or '')[:4]
            year = int(year_text) if year_text.isdecimal() else None
            if expected and year and abs(year - expected) > 4:
                continue
            overview = str(row.get('overview') or '')
            if display_name in AMBIGUOUS_SHOWS and not COMEDY_CONTEXT.search(overview):
                # A useful year alone does not prove which "One Night Stand"
                # or "Roast Battle" program TMDB means. Verify after detail.
                if not (expected and year and abs(year - expected) <= 1):
                    continue
            matches[row.get('id')] = row
    if not matches:
        return None
    def rank(row):
        year_text = str(row.get('first_air_date') or '')[:4]
        year = int(year_text) if year_text.isdecimal() else None
        era_score = 2 if expected and year and abs(year - expected) <= 1 else 0
        return (era_score, bool(COMEDY_CONTEXT.search(row.get('overview') or '')),
                row.get('vote_count') or 0, row.get('popularity') or 0)
    return max(matches.values(), key=rank)

def episode_performer(episode: dict) -> tuple[str | None, str]:
    """Infer cautiously from a named episode or one explicitly self-credited guest."""
    title = (episode.get('name') or '').strip()
    title = re.sub(r'(?i)^(?:comedy central presents|hbo comedy half.hour|one night stand)\s*[:\-–]\s*', '', title).strip()
    if title and not GENERIC_EPISODE.fullmatch(title):
        # Many anthology series have a standalone comedian name as episode title.
        # Accept only a short proper-name phrase, not generic descriptions.
        main = title.split(':', 1)[0].strip()
        words = main.split()
        if 1 <= len(words) <= 4 and len(main) <= 65 and all(NAME_WORD.fullmatch(w) for w in words):
            # Reject generic titles like "Comedy Night" / "The Finale".
            not_a_name = {'comedy', 'night', 'standup', 'finale', 'highlights', 'special', 'the'}
            if not any(normalized(w) in not_a_name for w in words):
                return main, 'episode_title'
    guest_stars = episode.get('guest_stars') or []
    self_guests = [str(g.get('name') or '').strip() for g in guest_stars
                   if re.search(r'(?i)\b(?:self|himself|herself|comedian)\b', str(g.get('character') or ''))
                   and g.get('name')]
    if len(set(self_guests)) == 1:
        return self_guests[0], 'self_credit'
    return None, 'unidentified'


def fetch_tv_candidates(api, series=SHOWS) -> list[dict]:
    """Collect unique episodes with series/season/episode IDs and credited act."""
    found = {}
    for display_name, variants in series:
        try:
            show = find_show(api, variants, display_name)
            if not show:
                print(f'TV showcase not found in TMDB: {display_name}', flush=True)
                continue
            show_id = int(show['id'])
            details = api.get(f'/tv/{show_id}')
            title = details.get('name') or show.get('name') or display_name
            if display_name in AMBIGUOUS_SHOWS:
                network_names = ' '.join(n.get('name', '') for n in details.get('networks', []))
                if not COMEDY_CONTEXT.search(network_names + ' ' + (details.get('overview') or '')):
                    print(f'Skipping ambiguous series match: {display_name}', flush=True)
                    continue
            # Season 0 is usually trailers/specials; keep regular episodes.
            seasons = sorted(set(int(s['season_number']) for s in details.get('seasons', [])
                                 if s.get('season_number') is not None and int(s['season_number']) > 0))
            count = 0
            for season in seasons:
                try:
                    response = api.get(f'/tv/{show_id}/season/{season}')
                except Exception as exc:
                    print(f'Unable to retrieve {title} season {season}: {type(exc).__name__}', flush=True)
                    continue
                for episode in response.get('episodes', []):
                    number = episode.get('episode_number')
                    if number is None:
                        continue
                    number = int(number)
                    if number <= 0:
                        continue
                    performer, attribution = episode_performer(episode)
                    identifier = f'tmdb-tv:{show_id}:{season}:{number}'
                    found[identifier] = {
                        'id': identifier,
                        'source': 'tmdb-tv-episode',
                        'show_title': title,
                        'show_poster_path': details.get('poster_path'),
                        'show_background_path': details.get('backdrop_path'),
                        'show_overview': details.get('overview') or '',
                        'show_original_language': details.get('original_language') or '',
                        'show_spoken_languages': [x.get('iso_639_1') for x in
                                                  details.get('spoken_languages', []) if x.get('iso_639_1')],
                        'episode_audio_language': episode.get('original_language') or '',
                        'tmdb_show_id': show_id,
                        'tmdb_episode_id': episode.get('id'),
                        'season_number': season,
                        'episode_number': number,
                        'episode_title': (episode.get('name') or '').strip(),
                        'performer': performer,
                        'performer_source': attribution,
                        'air_date': episode.get('air_date') or '',
                        'still_path': episode.get('still_path'),
                        'runtime': episode.get('runtime'),
                        'last_checked': date.today().isoformat(),
                        'status': 'series_episode_metadata_candidate_playback_unverified',
                    }
                    count += 1
            print(f'TV showcase {title}: {count} episodes indexed for review', flush=True)
        except Exception as exc:
            # One optional series must not stop daily catalog publishing.
            print(f'TV showcase lookup failed for {display_name}: {type(exc).__name__}: {exc}', flush=True)
    return sorted(found.values(), key=lambda x: (x['show_title'], x['season_number'], x['episode_number']))


def main():
    # Import here so offline tests can use fake APIs without a credential.
    from fetch_tmdb import TMDB
    candidates = fetch_tv_candidates(TMDB())
    # Don't erase old results if the service temporarily fails or returns zero.
    if not candidates:
        previous = read_json(OUTPUT, [])
        print(f'No new TV episodes returned; preserving {len(previous)} previous candidates', flush=True)
        return
    # When TMDB rate limits one show, preserve its previously found episodes.
    # New pages override stale metadata for the same true show/episode ID.
    previous = read_json(OUTPUT, [])
    by_id = {r['id']: r for r in previous
             if isinstance(r, dict) and r.get('source') == 'tmdb-tv-episode' and r.get('id')}
    by_id.update({r['id']: r for r in candidates})
    candidates = sorted(by_id.values(),
                        key=lambda r: (r.get('show_title', ''),
                                       r.get('season_number', 0), r.get('episode_number', 0)))
    write_json(OUTPUT, candidates)
    counts = {}
    for r in candidates:
        counts[r['show_title']] = counts.get(r['show_title'], 0) + 1
    print(f'TV episode candidates: {len(candidates)}, shows: {json.dumps(counts, ensure_ascii=False)}', flush=True)


if __name__ == '__main__':
    main()
