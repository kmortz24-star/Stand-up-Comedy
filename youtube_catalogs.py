"""Conservative YouTube *preview* catalogs using YouStream's `youtube` media type.

Only presents previously discovered videos for optional playback via a separately
installed YouStream addon. These are NOT verified playable or editorially approved.
No direct video URLs, torrents, downloaded content, or API secrets are published.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REJECT_TITLE = re.compile(
    r"(?i)\b(?:reaction|interviews?|podcast|trailer|teaser|compilation|"
    r"highlights|best of|mashup|classic bits|funniest jokes|top \d+|full episode of a podcast|"
    r"full set performances|stand.?up clips|sizzle reel|dr\.? phil live|"
    r"roast battle|outtakes|behind the scenes|reuploaded|commentary)\b"
)
STAGE = re.compile(
    r"(?i)stand[ -]?up|comedy (?:special|set)|full special|"
    r"half.hour (?:stand.up )?comedy|\bsecret sets\b"
)
TRUSTED_CHANNELS = (
    "don't tell comedy", "dry bar comedy", "comedy central stand-up",
    "800 pound gorilla", "netflix is a joke", "stand-up on the spot",
    "new york comedy club", "just for laughs", "laugh factory",
)
BANNED_NAME = re.compile(r"(?i)\b(?:comedy|stand.?up|full|special|episode|shorts?|"
                         r"live|official|presented|hour|minutes?|202\d|funniest)\b")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c if c.isalnum() else " " for c in value.casefold()
                    if not unicodedata.combining(c)).split())


def name_in_title(name: str, title: str) -> bool:
    needle, hay = normalize(name), normalize(title)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", hay))


def valid_person_name(s: str) -> bool:
    s = s.strip(" -—|.:!()[]\"'")
    words = s.split()
    return bool(2 <= len(words) <= 4 and 4 <= len(s) <= 50
                and not BANNED_NAME.search(s)
                and all(any(c.isalpha() for c in w) for w in words))


def identify_performer(video: dict, config: dict) -> str:
    """Never trust old `performer_search` without confirming title or channel.

    Past searches accidentally attributed many videos to Bobby Lee, to the year
    '2020', or to a different guest. Strong title/channel evidence is required.
    """
    title, channel = str(video.get("title") or ""), str(video.get("channel") or "")
    people = list(config.get("viral_rising_comedians") or [])
    for group in (config.get("roulette_groups") or {}).values():
        people.extend(group)
    people.extend(config.get("legends_comedians") or [])
    prior = str(video.get("performer_search") or "").strip()
    if valid_person_name(prior):
        people.insert(0, prior)
    unique_names = sorted({n for n in people if valid_person_name(n)}, key=len, reverse=True)
    for person in unique_names:
        if name_in_title(person, title):
            return person
    if (valid_person_name(channel) and name_in_title(channel, title)
            and not any(key in channel.casefold() for key in TRUSTED_CHANNELS)):
        return channel.strip()
    # Some publishers use 'Performer | Special title' and others
    # 'Special title | Performer | Full Special'.
    first = title.split("|")[0].strip()
    if len(title.split("|")) == 2 and valid_person_name(first):
        return first
    # Don't Tell formats its stage video titles as 'Joke | First Last | Stand Up Comedy'.
    # A generic first segment or show title must not count as a performer.
    parts = [x.strip() for x in title.split("|")]
    if len(parts) >= 3:
        for segment in parts[1:-1]:
            if valid_person_name(segment):
                return segment
    # 'Special title - First Last - Full Special' (Comedy Central uploads).
    mid = re.search(r"\s[-—]\s([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})\s[-—]\s", title)
    if mid and valid_person_name(mid.group(1)):
        return mid.group(1)
    # 'First Last: special title' and 'First Last - FULL COMEDY SPECIAL'.
    match = re.match(r"^([^:|—]{4,50})\s*:\s*", title)
    if match and valid_person_name(match.group(1)):
        return match.group(1).strip()
    return ""


def classify(video: dict, config: dict, today: date | None = None) -> tuple[str, str] | None:
    """Return (row id, verified performer) for plausible *review* candidates.

    Not a guarantee of copyright authorization, upload availability, player
    support, or relevance. Everything still needs real-world user verification.
    """
    title = str(video.get("title") or "")
    channel = str(video.get("channel") or "")
    video_id = str(video.get("video_id") or "")
    seconds = int(video.get("seconds") or 0)
    if not ID_RE.fullmatch(video_id) or not 600 <= seconds <= 7200:
        return None
    if REJECT_TITLE.search(title) or not STAGE.search(title):
        return None
    # A complete improvisational show episode is not one comedian's special.
    if re.search(r"(?i)\b(?:sots:|ep(?:isode)?\.?\s*\d+|\d+\s*year\s*special)\b", title):
        return None
    if video.get("embeddable") is False:
        return None
    performer = identify_performer(video, config)
    if not performer:
        return None
    trusted = any(key in channel.casefold() for key in TRUSTED_CHANNELS)
    creator_channel = name_in_title(performer, channel)
    if not (trusted or creator_channel):
        return None
    if seconds >= 35 * 60:
        return ("youtube-full-specials", performer)
    # Only 'viral' if source is a new-talent platform, or person belongs to
    # the existing short-list of rising comics. Old legends go to Gems.
    viral_names = {normalize(p) for p in config.get("viral_rising_comedians", [])}
    established = {normalize(p) for label, people in config.get("roulette_groups", {}).items()
                   if label in {"well_known", "b_tier", "classic_older"} for p in people}
    established |= {normalize(p) for p in config.get("legends_comedians", [])}
    newcomer_platform = any(x in channel.casefold() for x in
                            ("don't tell comedy", "stand-up on the spot"))
    if normalize(performer) in viral_names or (newcomer_platform and normalize(performer) not in established):
        return ("youtube-viral-rising", performer)
    return ("youtube-hidden-gems", performer)


def preview_rows(videos: list[dict], config: dict, today: date | None = None):
    """Sorted, duplicate-free metadata-only rows, for YouStream cross-addon use."""
    groups = {
        "youtube-viral-rising": [],
        "youtube-hidden-gems": [],
        "youtube-full-specials": [],
    }
    seen = set()
    for video in videos:
        if not isinstance(video, dict):
            continue
        vid = str(video.get("video_id") or "")
        if vid in seen:
            continue
        classification = classify(video, config, today)
        if classification is None:
            continue
        row, performer = classification
        seen.add(vid)
        title = str(video.get("title") or "").strip()
        groups[row].append({
            "id": "yt_id:" + vid,
            "type": "youtube",
            "name": title,
            "poster": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "background": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "description": f"{performer} · {int(video.get('seconds') or 0) // 60} min · "
                           f"YouTube preview · Playback may open externally",
            "releaseInfo": str(video.get("published_at", "")[:4]),
        })
    # Most recently published first; source order is published_at descending.
    return groups


def merged_movie_previews(videos: list[dict], config: dict, today: date | None = None):
    """Convert reviewed *candidates* into conventional movie-type cards.

    YouStream uses media type ``youtube``. A movie catalog cannot reliably
    contain that type, so a unique local ID lets this static addon provide its
    own movie metadata and external/built-in-YouTube stream choices instead.
    Only selected candidates qualify. No YouTube bytes are hosted here.

    Returns (category -> entries, id -> {meta, video_id}). Entries contain
    internal sorting metadata; only their ``meta`` is published.
    """
    groups = {"youtube-viral-rising": [], "youtube-hidden-gems": [],
              "youtube-full-specials": []}
    resources = {}
    seen = set()
    for video in videos:
        if not isinstance(video, dict):
            continue
        video_id = str(video.get("video_id") or "")
        if video_id in seen:
            continue
        classification = classify(video, config, today)
        if not classification:
            continue
        group, performer = classification
        seen.add(video_id)
        alias = "standupyt_" + video_id
        title = str(video.get("title") or "").strip()
        year = str(video.get("published_at") or "")[:4]
        meta = {
            "id": alias,
            "type": "movie",
            "name": title + " [YouTube]",
            "poster": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "background": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "description": (f"{performer} · {int(video.get('seconds') or 0) // 60} minute YouTube upload. "
                            "Preview candidate: availability and playback are not guaranteed; "
                            "may open YouTube externally."),
        }
        # This reflects upload date, not necessarily the performance's date.
        if year.isdigit() and len(year) == 4:
            meta["releaseInfo"] = year
        entry = {"meta": meta, "performer": performer,
                 "uploaded": str(video.get("published_at") or "")}
        groups[group].append(entry)
        resources[alias] = {"meta": meta, "video_id": video_id}
    return groups, resources
