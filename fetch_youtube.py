"""Collect promising YouTube stand-up video leads (not yet Nuvio catalog items).

Stremio-compatible movie metas cannot be assumed to play a YouTube ID. Videos
are stored separately until a compatible stream route has been verified.
Only public video metadata is stored; never the API key.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
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

DAILY_SEARCH_BUDGET = 6  # YouTube search.list costs 100 quota units per call.

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
    # Interview/podcast channels can mention stand-up in descriptions without
    # showing a stage performance. Keep these out of the review queue.
    if re.search(r"(?i)\bpodcast\b|\binterviews?\b", channel) and not re.search(
        r"(?i)full (?:stand[ -]?up )?(?:comedy )?special|stand[ -]?up (?:comedy )?(?:special|set)", title
    ):
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


def candidate_kind(title: str, seconds: int) -> tuple[str, str]:
    """Only suggest where a *reviewed* video may belong; do not publish it.

    Avoid the temptation to categorize a 10-minute set as a full special just
    because the creator calls it a 'special'. Video playback and authorization
    still need separate verification.
    """
    if seconds >= 2100 and re.search(r"(?i)\bfull (?:stand[ -]?up )?(?:comedy )?special\b|\bfull show\b", title):
        return "full_special", "Comedian alphabeticals"
    if seconds >= 2400:
        return "long_form", "Comedian alphabeticals"
    return "standup_set", "Hidden Gems"


def gather_youtube(key: str, *, search_fn=youtube_get, today: date | None = None):
    """Accumulate candidates under a DAILY API budget, saving partial successes.

    The old 32-query batch could consume >3,200 search quota units *per run*,
    and a late quota error discarded the whole batch's work. Cap queries per
    calendar day, validate immediately, and checkpoint each successful query.
    """
    today = today or date.today()
    day = today.isoformat()
    state = read_json(STATE_PATH, {})
    config = read_json(CONFIG_PATH, {})
    stored = {r["video_id"]: r for r in read_json(DATA_PATH, []) if r.get("video_id")}
    # Classify already-discovered 10+ minute sets as review leads too; no
    # second API call, and no assumption that their YouStream links will play.
    for old in stored.values():
        kind, suggested = candidate_kind(str(old.get("title") or ""), int(old.get("seconds") or 0))
        old.setdefault("candidate_kind", kind)
        old.setdefault("suggested_catalog_after_review", suggested)
        old["review_status"] = "candidate_only"
    cache = {r["id"]: r for r in read_json(SPECIALS_PATH, []) if r.get("id")}
    if state.get("youtube_daily_date") != day:
        state["youtube_daily_date"] = day
        state["youtube_daily_queries"] = 0
    budget = max(0, DAILY_SEARCH_BUDGET - int(state.get("youtube_daily_queries", 0)))

    names, curated = discovery_names(config, state, cache)
    tv_rows = read_json(ROOT / "data" / "tv_episode_candidates.json", [])
    tv_priority = {norm(row["performer"]) for row in tv_rows if row.get("performer")}

    people_state = {"searched_performers": state.setdefault("youtube_searched", {})}
    set_state = {"searched_performers": state.setdefault("youtube_set_searched", {})}
    title_state = {"searched_titles": state.setdefault("youtube_searched_titles", {}),
                   "works": state.get("works", [])}
    # Favor recognizable comics, but rotate; these are comedian names, not a
    # manually inserted list of special titles or YouTube URLs.
    due_people = scheduled_names(names, curated, people_state, cache, today=today,
                                 max_searches=5, tv_performers=tv_priority)
    due_sets = scheduled_names(names, curated, set_state, cache, today=today,
                               max_searches=5, tv_performers=tv_priority)
    due_titles = title_search_queue(title_state, cache, today=today, limit=3,
                                    priority_performers=curated)
    general_due = not state.get("youtube_general_searched") or state["youtube_general_searched"] < (
        today - timedelta(days=14)).isoformat()

    # Search all sources gradually instead of flooding YouTube for 21 people at
    # once. Exact titles get a slot, and 10+ minute stand-up sets get regular
    # searches even when the comedian has no TMDB movie special.
    queries = []
    if general_due:
        general_index = int(state.get("youtube_general_rotation", 0)) % len(GENERAL_QUERIES)
        queries.append(("general", GENERAL_QUERIES[general_index], "", "", ""))
    for row in due_titles[:2]:
        queries.append(("title", f"{row['title']} {row.get('performer', '')} full stand up",
                        row.get("performer", ""), row["title"], row["source_id"]))
    for name in due_people[:4]:
        queries.append(("person", f"{name} full stand up comedy special", name, "", norm(name)))
    for name in due_sets[:4]:
        queries.append(("set", f"{name} stand up comedy set", name, "", norm(name)))
    # Interleave established names and short sets. Avoid repeatedly searching
    # the same comedian in one run when there are other names available.
    if len(queries) > budget:
        first = [q for q in queries if q[0] in {"general", "title"}]
        full = [q for q in queries if q[0] == "person"]
        sets = [q for q in queries if q[0] == "set"]
        ordered = first + [x for pair in zip(full, sets) for x in pair] + full[len(sets):] + sets[len(full):]
        queries = ordered[:budget]

    total_new = 0
    checked_videos = 0
    successful_searches = 0
    quota_blocked = False
    channel_count = 0

    def ingest(video: dict, metadata: dict) -> int:
        nonlocal checked_videos
        checked_videos += 1
        video_id = str(video.get("id") or "")
        if not video_id or not plausible_video(video, metadata.get("performer", "")):
            return 0
        status = video.get("status") or {}
        if status.get("privacyStatus", "public") != "public":
            return 0
        snippet = video.get("snippet") or {}
        seconds = iso_duration_seconds((video.get("contentDetails") or {}).get("duration", ""))
        channel = snippet.get("channelTitle", "")
        performer = metadata.get("performer", "")
        publisher_match = bool((performer and norm(performer) in norm(channel)) or any(
            term in channel.casefold() for term in TRUSTED_CHANNEL_TERMS))
        kind, suggested = candidate_kind(snippet.get("title", ""), seconds)
        previous = stored.get(video_id, {})
        stored[video_id] = {
            **previous,
            "video_id": video_id, "title": snippet.get("title", ""),
            "channel": channel, "channel_id": snippet.get("channelId", ""),
            "performer_search": performer or previous.get("performer_search", ""),
            "matched_special_title": metadata.get("special_title", "") or previous.get("matched_special_title", ""),
            "seconds": seconds, "published_at": snippet.get("publishedAt", ""),
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "publisher_match": publisher_match or bool(previous.get("publisher_match")),
            "review_status": "candidate_only", "candidate_kind": kind,
            "suggested_catalog_after_review": suggested,
            "discovered_by": metadata.get("discovered_by", "search"),
            "embeddable": status.get("embeddable"), "last_checked": day,
        }
        return int(not previous)

    def resolve(raw: dict[str, dict]):
        nonlocal total_new
        if not raw:
            return
        video_ids = list(raw)
        for start in range(0, len(video_ids), 50):
            response = search_fn(key, "videos", part="snippet,contentDetails,status",
                                 id=",".join(video_ids[start:start + 50]), maxResults=50)
            for video in response.get("items", []):
                total_new += ingest(video, raw.get(video.get("id", ""), {}))

    try:
        for kind, query, performer, special_title, label in queries:
            try:
                response = search_fn(key, "search", part="snippet", type="video", maxResults=50,
                                     q=query, safeSearch="moderate", order="relevance")
                # Search calls cost quota even if videos.list then fails. Record
                # them against today's budget so manual reruns don't multiply
                # quota use. Incomplete searches are retried next day.
                state["youtube_daily_queries"] += 1
                raw = {}
                for item in response.get("items", []):
                    video_id = (item.get("id") or {}).get("videoId")
                    if video_id:
                        raw[video_id] = {"performer": performer, "special_title": special_title,
                                         "discovered_by": "search"}
                resolve(raw)
            except (HTTPError, URLError, TimeoutError) as exc:
                if isinstance(exc, HTTPError) and exc.code not in (403, 429):
                    raise
                print(f"YouTube partial refresh stopped ({type(exc).__name__}); previous results retained", flush=True)
                quota_blocked = True
                break
            # Advance only the cursor actually searched; a failed query should
            # never skip that person's remaining work for 45 days.
            successful_searches += 1
            if kind == "person":
                state["youtube_searched"][label] = day
            elif kind == "set":
                state["youtube_set_searched"][label] = day
            elif kind == "title":
                state["youtube_searched_titles"][label] = day
            elif kind == "general":
                state["youtube_general_searched"] = day
                state["youtube_general_rotation"] = int(state.get("youtube_general_rotation", 0)) + 1

        # Channel uploads require very little quota and naturally expose
        # unknown and underrated comics. Scan once per day only, and keep
        # advancing archival cursors rather than re-scanning at every rerun.
        if not quota_blocked and state.get("youtube_channel_scan_date") != day:
            cursor = state.setdefault("youtube_channel_cursors", {})
            channel_ids = sorted({r.get("channel_id", "") for r in stored.values()
                if r.get("publisher_match") and r.get("channel_id") and any(
                    term in str(r.get("channel", "")).casefold() for term in TRUSTED_CHANNEL_TERMS)})
            channel_ids.sort(key=lambda cid: (cursor.get(cid, {}).get("checked", ""), cid))
            chosen = channel_ids[:6]
            if chosen:
                response = search_fn(key, "channels", part="contentDetails", id=",".join(chosen))
                playlists = {r["id"]: ((r.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
                             for r in response.get("items", []) if r.get("id")}
                for cid in chosen:
                    playlist_id = playlists.get(cid)
                    if not playlist_id:
                        continue
                    newest = search_fn(key, "playlistItems", part="snippet", playlistId=playlist_id, maxResults=50)
                    token = (cursor.get(cid) or {}).get("page") or newest.get("nextPageToken", "")
                    batches = [newest]
                    if token:
                        try:
                            older = search_fn(key, "playlistItems", part="snippet", playlistId=playlist_id,
                                              maxResults=50, pageToken=token)
                        except HTTPError as exc:
                            if exc.code != 400:
                                raise
                            older = {"items": [], "nextPageToken": ""}
                        batches.append(older)
                        token = older.get("nextPageToken", "")
                    raw = {}
                    for batch in batches:
                        for item in batch.get("items", []):
                            vid = ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId")
                            if vid:
                                raw[vid] = {"performer": "", "special_title": "", "discovered_by": "channel_uploads"}
                    resolve(raw)
                    cursor[cid] = {"page": token, "checked": day}
                    channel_count += 1
            state["youtube_channel_scan_date"] = day
    except (HTTPError, URLError, TimeoutError) as exc:
        # Retain discoveries and search progress even if the channel scan
        # encounters rate limits or network problems late in the run.
        quota_blocked = True
        print(f"YouTube channel scan stopped ({type(exc).__name__}); previous discoveries retained", flush=True)
    finally:
        state["youtube_last_run"] = day
        state["youtube_last_discovery"] = {
            "queries_completed": successful_searches, "daily_queries_used": state["youtube_daily_queries"],
            "daily_query_budget": DAILY_SEARCH_BUDGET, "videos_checked": checked_videos,
            "new_candidates": total_new, "channels_scanned": channel_count,
            "quota_or_connection_blocked": quota_blocked,
        }
        write_json(DATA_PATH, sorted(stored.values(),
                   key=lambda r: (r.get("published_at", ""), r["video_id"]), reverse=True)[:30000])
        write_json(STATE_PATH, state)
    print(f"YouTube: {total_new} new filtered candidates, {len(stored)} stored; "
          f"{successful_searches} successful searches (today's budget {DAILY_SEARCH_BUDGET})", flush=True)


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
