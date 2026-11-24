"""Collect promising YouTube stand-up video leads (not yet Nuvio catalog items).

Stremio-compatible movie metas cannot be assumed to play a YouTube ID. Videos
are stored separately until a compatible stream route has been verified.
Only public video metadata is stored; never the API key.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from build_catalogs import ROOT, norm, read_json, write_json
from fetch_tmdb import discovery_names, scheduled_names, title_search_queue

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3/"
DATA_PATH = ROOT / "data/youtube_candidates.json"
STATE_PATH = ROOT / "data/discovery_state.json"
SPECIALS_PATH = ROOT / "data/specials.json"
CONFIG_PATH = ROOT / "config.json"

GENERAL_QUERIES = (
    "full stand up comedy special", "new stand up comedy special",
    "kill tony comedian stand up set", "don't tell comedy full stand up set",
)
BLOCKED = re.compile(r"(?i)\b(?:reaction|interview|podcast|trailer|teaser|highlights|shorts|best of|compilation|explained|review|behind the scenes|stream clip|commentary)\b")
STANDUP_TERMS = re.compile(r"(?i)stand[ -]?up|comedy special|full special|comedy set|live comedy|roast battle|full set")
TRUSTED_CHANNEL_TERMS = (
    "dry bar comedy", "don't tell comedy", "comedy central stand-up",
    "800 pound gorilla", "netflix is a joke", "kill tony",
    "laugh factory", "the comedy store", "all things comedy",
)


def iso_duration_seconds(value: str) -> int:
    parts = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not parts:
        return 0
    d, h, m, s = (int(p or 0) for p in parts.groups())
    return d * 86400 + h * 3600 + m * 60 + s


def plausible_video(video: dict, searched_for: str = "") -> bool:
    title = (video.get("snippet") or {}).get("title", "")
    description = (video.get("snippet") or {}).get("description", "")
    channel = (video.get("snippet") or {}).get("channelTitle", "")
    seconds = iso_duration_seconds((video.get("contentDetails") or {}).get("duration", ""))
    if seconds < 600 or BLOCKED.search(title):
        return False
    if not (STANDUP_TERMS.search(title) or (STANDUP_TERMS.search(description) and
                                           re.search(r"(?i)\b(?:special|set|live|comedy)\b", title))):
        return False
    # A video on an unverified channel remains a review lead, not a presumed
    # official upload; all records remain unpublished until playback is tested.
    return True


def youtube_get(key: str, endpoint: str, **params):
    url = YOUTUBE_BASE + endpoint + "?" + urlencode({**params, "key": key})
    with urlopen(Request(url, headers={"User-Agent": "NuvioStandupCatalog/1.1"}), timeout=30) as response:
        return json.load(response)


def gather_youtube(key: str, *, search_fn=youtube_get, today: date | None = None):
    today = today or date.today()
    state = read_json(STATE_PATH, {})
    config = read_json(CONFIG_PATH, {})
    stored = {r["video_id"]: r for r in read_json(DATA_PATH, []) if r.get("video_id")}
    cache = {r["id"]: r for r in read_json(SPECIALS_PATH, []) if r.get("id")}
    names, curated = discovery_names(config, state, cache)
    tv_rows = read_json(ROOT / 'data' / 'tv_episode_candidates.json', [])
    tv_priority = {norm(row['performer']) for row in tv_rows if row.get('performer')}
    queue_state = {"searched_performers": state.setdefault("youtube_searched", {})}
    # 2 spotlight searches plus broad low-coverage searches. Independent TV
    # credits help uncover missing standalone specials automatically; we never
    # insert the special titles manually. The roster still rotates on every run.
    spotlight = scheduled_names(names, curated, queue_state, cache, today=today,
                                max_searches=2, tv_performers=tv_priority)
    coverage = scheduled_names(names, set(), queue_state, cache, today=today,
                               max_searches=26, tv_performers=tv_priority)
    due = (spotlight + [name for name in coverage if name not in spotlight])[:21]
    # A separate rotating queue catches named specials that never appear in
    # generic comedian searches, including older TV specials.
    title_state = {'searched_titles': state.setdefault('youtube_searched_titles', {}),
                   'works': state.get('works', [])}
    title_leads = title_search_queue(title_state, cache, today=today, limit=8)
    # A query has its own performer/title label, used for later audit.
    general_checked = state.get('youtube_general_searched', '')
    general_due = (not general_checked or general_checked <=
                   (today.replace(day=1)).isoformat())
    general = [(q, '', '') for q in GENERAL_QUERIES[:2]] if general_due else []
    queries = general + [
        (f"{name} full stand up comedy special", name, '') for name in due
    ] + [(f"{name} stand up comedy set", name, '') for name in due[:1]] + [
        (f"{item['title']} {item.get('performer', '')} full stand up", item.get('performer', ''), item['title'])
        for item in title_leads
    ]
    # Up to 2 general + 21 comedian + 1 alternate set + 8 exact title = 32.
    assert len(queries) <= 32, 'Exceeded the per-run YouTube search budget' 
    raw = {}
    for query, performer, special_title in queries:
        response = search_fn(key, "search", part="snippet", type="video", maxResults=50,
                             q=query, safeSearch="moderate", order="relevance")
        for item in response.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if video_id and video_id not in raw:
                raw[video_id] = {'performer': performer, 'special_title': special_title,
                                 'discovered_by': 'search'}

    # Scanning upload playlists is cheap compared with a search query and
    # exposes specials not ranked by YouTube's textual search. Use only
    # channels independently discovered and labeled as trusted publishers.
    channel_ids = sorted({row.get('channel_id', '') for row in stored.values()
                          if row.get('publisher_match') and any(
                              term in str(row.get('channel', '')).casefold()
                              for term in TRUSTED_CHANNEL_TERMS) and row.get('channel_id')})
    cursor = state.setdefault('youtube_channel_cursors', {})
    # Rotate through established comedy channels rather than always starting
    # with one: maximum six per refresh; two pages (up to 100 uploads) each.
    channel_ids.sort(key=lambda cid: (cursor.get(cid, {}).get('checked', ''), cid))
    chosen = channel_ids[:6]
    if chosen:
        details = search_fn(key, 'channels', part='contentDetails', id=','.join(chosen))
        uploads = {row['id']: ((row.get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads')
                   for row in details.get('items', []) if row.get('id')}
        for channel_id in chosen:
            playlist_id = uploads.get(channel_id)
            if not playlist_id:
                continue
            # First scan newest uploads EVERY run, then advance a separate
            # cursor through archival pages to catch older channel specials.
            archive_token = (cursor.get(channel_id) or {}).get('page', '')
            newest = search_fn(key, 'playlistItems', part='snippet',
                               playlistId=playlist_id, maxResults=50)
            batches = [newest]
            archive_token = archive_token or newest.get('nextPageToken', '')
            if archive_token:
                try:
                    archive = search_fn(key, 'playlistItems', part='snippet',
                                        playlistId=playlist_id, maxResults=50,
                                        pageToken=archive_token)
                except HTTPError as exc:
                    if exc.code != 400:
                        raise
                    # Playlist changed; archive cursor resets safely.
                    archive = {'items': [], 'nextPageToken': ''}
                batches.append(archive)
                archive_token = archive.get('nextPageToken', '')
            for batch in batches:
                for item in batch.get('items', []):
                    vid = ((item.get('snippet') or {}).get('resourceId') or {}).get('videoId')
                    if vid:
                        raw.setdefault(vid, {'performer': '', 'special_title': '',
                                             'discovered_by': 'channel_uploads'})
            cursor[channel_id] = {'page': archive_token, 'checked': today.isoformat()}
    print(f"YouTube search and channel scanning: {len(raw)} video leads from {len(queries)} queries and {len(chosen)} channels", flush=True)

    # videos.list supplies actual length, whereas search.list does not.
    new_count = 0
    video_ids = list(raw)
    for start in range(0, len(video_ids), 50):
        response = search_fn(key, "videos", part="snippet,contentDetails,status",
                             id=",".join(video_ids[start:start + 50]), maxResults=50)
        for video in response.get("items", []):
            video_id = video.get("id", "")
            if not video_id or not plausible_video(video, raw.get(video_id, {}).get('performer', '')):
                continue
            status = video.get('status') or {}
            if status.get('privacyStatus', 'public') != 'public':
                continue
            snippet = video.get("snippet") or {}
            matched = raw.get(video_id) or {}
            performer = matched.get('performer', '')
            seconds = iso_duration_seconds((video.get("contentDetails") or {}).get("duration", ""))
            channel = snippet.get("channelTitle", "")
            channel_lower = channel.casefold()
            publisher_match = bool((performer and norm(performer) in norm(channel)) or any(
                source in channel_lower for source in TRUSTED_CHANNEL_TERMS))
            stored[video_id] = {
                "video_id": video_id, "title": snippet.get("title", ""),
                "channel": channel, "channel_id": snippet.get("channelId", ""),
                "performer_search": performer, "matched_special_title": matched.get('special_title', ''),
                "seconds": seconds,
                "published_at": snippet.get("publishedAt", ""),
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "publisher_match": publisher_match,
                "review_status": "candidate_only",
                "discovered_by": matched.get('discovered_by', 'search'),
                "embeddable": status.get('embeddable'),
                "last_checked": today.isoformat(),
            }
            new_count += 1

    for name in due:
        state["youtube_searched"][norm(name)] = today.isoformat()
    for item in title_leads:
        state['youtube_searched_titles'][item['source_id']] = today.isoformat()
    state["youtube_last_run"] = today.isoformat()
    if general_due:
        state['youtube_general_searched'] = today.isoformat()
    state["youtube_last_discovery"] = {"people_searched": len(due), "special_titles_searched": len(title_leads),
                                       "metadata_candidates_checked": len(video_ids),
                                       "video_candidates_passed": new_count, "channels_scanned": len(chosen)}
    write_json(DATA_PATH, sorted(stored.values(), key=lambda r: (r.get("published_at", ""), r["video_id"]), reverse=True)[:30000])
    write_json(STATE_PATH, state)
    print(f"YouTube: {new_count} 10+ minute candidates; stored total {len(stored)} (not published yet)", flush=True)


def main():
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("YouTube stage skipped (YOUTUBE_API_KEY GitHub Actions secret not configured).")
        return
    try:
        gather_youtube(key)
    except (HTTPError, URLError, TimeoutError) as exc:
        # A quota/API hiccup shouldn't block a working TMDB catalog refresh.
        reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        print(f"YouTube candidate stage unavailable ({reason}); catalog refresh unaffected")


if __name__ == "__main__":
    main()
