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
from fetch_tmdb import discovery_names, scheduled_names

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3/"
DATA_PATH = ROOT / "data/youtube_candidates.json"
STATE_PATH = ROOT / "data/discovery_state.json"
SPECIALS_PATH = ROOT / "data/specials.json"
CONFIG_PATH = ROOT / "config.json"

GENERAL_QUERIES = (
    "full stand up comedy special", "new stand up comedy special",
    "kill tony comedian stand up set", "don't tell comedy full stand up set",
)
BLOCKED = re.compile(r"(?i)\b(?:reaction|interview|podcast|trailer|teaser|highlights|shorts|best of|compilation|explained|review)\b")
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
    queue_state = {"searched_performers": state.setdefault("youtube_searched", {})}
    due = scheduled_names(names, curated, queue_state, cache, today=today, max_searches=12)
    queries = [(q, "") for q in GENERAL_QUERIES] + [
        (f"{name} full stand up comedy special", name) for name in due
    ] + [(f"{name} stand up comedy set", name) for name in due]

    raw = {}
    for query, performer in queries:
        response = search_fn(key, "search", part="snippet", type="video", maxResults=25,
                             q=query, safeSearch="moderate", order="relevance")
        for item in response.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if video_id and video_id not in raw:
                raw[video_id] = performer
    print(f"YouTube search: {len(raw)} distinct candidates from {len(queries)} queries", flush=True)

    # videos.list supplies actual length, whereas search.list does not.
    new_count = 0
    video_ids = list(raw)
    for start in range(0, len(video_ids), 50):
        response = search_fn(key, "videos", part="snippet,contentDetails,status",
                             id=",".join(video_ids[start:start + 50]), maxResults=50)
        for video in response.get("items", []):
            video_id = video.get("id", "")
            if not video_id or not plausible_video(video, raw.get(video_id, "")):
                continue
            snippet = video.get("snippet") or {}
            performer = raw.get(video_id) or ""
            seconds = iso_duration_seconds((video.get("contentDetails") or {}).get("duration", ""))
            channel = snippet.get("channelTitle", "")
            channel_lower = channel.casefold()
            publisher_match = bool((performer and norm(performer) in norm(channel)) or any(
                source in channel_lower for source in TRUSTED_CHANNEL_TERMS))
            stored[video_id] = {
                "video_id": video_id, "title": snippet.get("title", ""),
                "channel": channel, "channel_id": snippet.get("channelId", ""),
                "performer_search": performer, "seconds": seconds,
                "published_at": snippet.get("publishedAt", ""),
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "publisher_match": publisher_match,
                "review_status": "candidate_only",
                "last_checked": today.isoformat(),
            }
            new_count += 1

    for name in due:
        state["youtube_searched"][norm(name)] = today.isoformat()
    state["youtube_last_run"] = today.isoformat()
    state["youtube_last_discovery"] = {"people_searched": len(due),
                                       "metadata_candidates_checked": len(video_ids),
                                       "video_candidates_passed": new_count}
    write_json(DATA_PATH, sorted(stored.values(), key=lambda r: (r["published_at"], r["video_id"]), reverse=True)[:3000])
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
        print(f"YouTube candidate stage unavailable: {type(exc).__name__}; catalog refresh unaffected")


if __name__ == "__main__":
    main()
