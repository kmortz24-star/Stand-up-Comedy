"""Publish independently discovered stand-up showcases as *series*, not movies.

This is metadata only: it exposes episodes under the real TMDB show ID
(`tmdb:1234:season:episode`) so compatible Nuvio stream addons can attempt
normal episode resolution.  We do not claim to host or verify any playback.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from language_filters import explicitly_non_english


def _positive_int(value: Any) -> int | None:
    try:
        val = int(value)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _tmdb_image(path: Any, *, backdrop: bool = False) -> str | None:
    if not isinstance(path, str) or not path.startswith('/') or '//' in path:
        return None
    return 'https://image.tmdb.org/t/p/' + ('w780' if backdrop else 'w500') + path


def _release_year(value: str) -> str:
    try:
        return str(date.fromisoformat(value).year)
    except (ValueError, TypeError):
        return ''


def build_tv_series(candidates: list[dict], *, english_only=False,
                    exclude_multilingual=()) -> tuple[list[dict], dict[str, dict], dict]:
    """Return (catalog previews, show-id keyed full series meta, audit counts).

    Keep only unambiguous TV IDs and positive episode identifiers. No fictitious
    films, TV episodes, or streaming sources are generated.
    """
    by_show: dict[int, dict[tuple[int, int], dict]] = defaultdict(dict)
    show_info: dict[int, dict] = {}
    excluded_names = {str(n).strip().casefold() for n in exclude_multilingual}
    for row in candidates:
        if not isinstance(row, dict) or row.get('source') != 'tmdb-tv-episode':
            continue
        show_id = _positive_int(row.get('tmdb_show_id'))
        season = _positive_int(row.get('season_number'))
        episode = _positive_int(row.get('episode_number'))
        if not show_id or not season or not episode:
            continue
        title = str(row.get('show_title') or '').strip()
        if not title:
            continue
        if english_only:
            if title.casefold() in excluded_names:
                continue
            if explicitly_non_english(row, fields=("episode_audio_language", "show_original_language")):
                continue
        info = show_info.setdefault(show_id, row)
        # Prefer records that have visual metadata from a newer TMDB refresh.
        if row.get('show_poster_path') and not info.get('show_poster_path'):
            show_info[show_id] = row
        key = (season, episode)
        old = by_show[show_id].get(key)
        if old is None or (row.get('performer') and not old.get('performer')):
            by_show[show_id][key] = row

    previews: list[dict] = []
    details: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for show_id, episode_map in sorted(by_show.items(), key=lambda pair: str(show_info[pair[0]]['show_title']).casefold()):
        info = show_info[show_id]
        show_name = str(info['show_title']).strip()
        show_key = f'tmdb:{show_id}'
        episodes = []
        for (season, episode_number), row in sorted(episode_map.items()):
            person = str(row.get('performer') or '').strip()
            episode_title = str(row.get('episode_title') or '').strip()
            label = episode_title or person or f'Episode {episode_number}'
            item = {'id': f'{show_key}:{season}:{episode_number}',
                    'title': label, 'season': season, 'episode': episode_number}
            aired = row.get('air_date') or ''
            if _release_year(aired):
                item['released'] = aired + 'T00:00:00.000Z'
            if person:
                item['overview'] = f'Stand-up performance featuring {person}.'
            thumb = _tmdb_image(row.get('still_path'), backdrop=True)
            if thumb:
                item['thumbnail'] = thumb
            episodes.append(item)
        if not episodes:
            continue
        start = min((i['released'][:4] for i in episodes if i.get('released')), default='')
        preview = {'id': show_key, 'type': 'series', 'name': show_name}
        if start:
            preview['releaseInfo'] = start
        poster = _tmdb_image(info.get('show_poster_path'))
        if poster:
            preview['poster'] = poster
        background = _tmdb_image(info.get('show_background_path'), backdrop=True)
        if background:
            preview['background'] = background
        summary = str(info.get('show_overview') or '').strip()
        meta = {**preview, 'description': summary or
                f'{show_name}: {len(episodes)} indexed stand-up episodes. '
                'Episode availability depends on installed streaming addons.',
                'videos': episodes}
        previews.append(preview)
        details[show_key] = meta
        counts[show_name] = len(episodes)
    return previews, details, counts
