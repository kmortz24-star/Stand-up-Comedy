"""Discover episodes from long-running stand-up showcase television series.

Episode records are metadata *review candidates* only. A single episode is not
necessarily a movie and should not be published as a movie in Nuvio until an
appropriate series/episode metadata and playback path has been verified.

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
SHOWS = (
    ('Comedy Central Presents', ('Comedy Central Presents',)),
    ('HBO Comedy Half-Hour', ('HBO Comedy Half-Hour', 'HBO Comedy Half Hour', 'Comedy Half Hour')),
    ('One Night Stand', ('One Night Stand', 'HBO One Night Stand')),
)

GENERIC_EPISODE = re.compile(
    r'(?i)^(?:episode\s*\d+|show\s*\d+|season\s*\d+|special\s*\d*|'
    r'best\s+of\b.*|highlights?\b.*|pilot|part\s*\d+|tba|untitled|'
    r'comedy central presents|one night stand|hbo comedy half.hour)$'
)
NAME_WORD = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ.'’\-]*$")


def normalized(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(text).casefold())


def find_show(api, variants: tuple[str, ...]) -> dict | None:
    """Only accept exact title aliases, avoiding same-name unrelated programs."""
    for query in variants:
        rows = api.get('/search/tv', query=query, page=1).get('results', [])
        allowed = {normalized(alias) for alias in variants}
        candidates = [r for r in rows if normalized(r.get('name', '')) in allowed]
        # 'One Night Stand' is an ambiguous name used by unrelated programs.
        # Require comedy/stand-up context rather than guessing from popularity.
        if normalized(variants[0]) == 'onenightstand':
            candidates = [r for r in candidates if re.search(
                r'(?i)stand.?up|comedi(?:an|ans|y)|hbo', r.get('overview') or '')]
        if candidates:
            return max(candidates, key=lambda r: (r.get('popularity') or 0, r.get('vote_count') or 0))
    return None


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
            show = find_show(api, variants)
            if not show:
                print(f'TV showcase not found in TMDB: {display_name}', flush=True)
                continue
            show_id = int(show['id'])
            details = api.get(f'/tv/{show_id}')
            title = details.get('name') or show.get('name') or display_name
            if display_name == 'One Night Stand':
                network_names = ' '.join(n.get('name', '') for n in details.get('networks', []))
                if not re.search(r'(?i)hbo|stand.?up|comedi(?:an|ans|y)',
                                 network_names + ' ' + (details.get('overview') or '')):
                    print('Skipping ambiguous One Night Stand program', flush=True)
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
                        'status': 'review_only_not_published',
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
    write_json(OUTPUT, candidates)
    counts = {}
    for r in candidates:
        counts[r['show_title']] = counts.get(r['show_title'], 0) + 1
    print(f'TV episode candidates: {len(candidates)}, shows: {json.dumps(counts, ensure_ascii=False)}', flush=True)


if __name__ == '__main__':
    main()
