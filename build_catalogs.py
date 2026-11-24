"""Build static Stremio-compatible catalogs for the Stand-Up Comedy Nuvio folder.

Input records are in data/specials.json. Unknown performers remain in a review
report rather than silently being assigned the wrong letter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from language_filters import movie_allowed, performer_non_english_evidence, language_code


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_INPUT = ROOT / "data" / "specials.json"
DEFAULT_OUTPUT = ROOT / "docs"
PAGE_SIZE = 50


def read_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: str) -> str:
    expanded = str(value).translate(str.maketrans({
        "Æ": "Ae", "æ": "ae", "Ø": "O", "ø": "o", "Ł": "L", "ł": "l",
        "Ð": "D", "ð": "d", "Þ": "Th", "þ": "th",
    }))
    text = unicodedata.normalize("NFKD", expanded)
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in text if not unicodedata.combining(c)).casefold())


def performer_sort_name(performer: str) -> str:
    # The performer goes under the first letter of their displayed/stage name.
    return norm(performer).strip()


def bucket_for(performer: str, groups: list[str]) -> int | None:
    normalized = performer_sort_name(performer)
    first = normalized[:1].upper()
    matches = [i for i, group in enumerate(groups) if first in group]
    return matches[0] if len(matches) == 1 else None


def validate_groups(groups: list[str]):
    letters = "".join(groups)
    if len(groups) < 2 or sorted(letters) != list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        raise ValueError("alphabet_groups must use each letter A-Z exactly once")
    for group in groups:
        if not re.fullmatch("[A-Z]+", group):
            raise ValueError(f"Invalid group {group!r}")


def unique_records(records: list[dict]) -> list[dict]:
    by_id = {}
    for record in records:
        identifier = str(record.get("id", "")).strip()
        if not identifier:
            continue
        original = by_id.get(identifier, {})
        by_id[identifier] = {**original, **record}
    return list(by_id.values())


def dedupe_same_special(records: list[dict]) -> list[dict]:
    """Remove two TMDB records for the exact same performer/title/year.

    Prefer a catalog-compatible IMDb id and the more widely rated record; do
    not merge separate specials merely because their release dates match.
    """
    by_work = {}
    for record in unique_records(records):
        title = norm(record.get("title", ""))
        performer = norm(record.get("performer", ""))
        year = str(record.get("release_date", ""))[:4]
        if not (title and performer and year):
            by_work[("id", record["id"])] = record
            continue
        key = (performer, title, year)
        previous = by_work.get(key)
        def rank(item):
            return (str(item["id"]).startswith("tt"), int(item.get("vote_count") or 0),
                    bool(item.get("poster_path") or item.get("poster")))
        if previous is None or rank(record) > rank(previous):
            by_work[key] = record
    return list(by_work.values())


def too_poorly_rated(record: dict, config: dict) -> bool:
    """Only exclude clearly unpopular entries with a meaningful vote sample.

    Unrated works and classics with just one or two votes stay visible.
    """
    votes = int(record.get("vote_count") or 0)
    rating = float(record.get("vote_average") or 0)
    if not votes or not rating:
        return False
    return ((votes >= int(config.get("alphabet_quality_min_votes", 15)) and
             rating < float(config.get("alphabet_min_rating", 4.0))) or
            (votes >= 5 and rating < 2.5))


def established_unrated_performers(config: dict) -> set[str]:
    """Explicit established A/B roster for preserving zero-vote specials.

    The existing roulette tiers and established coverage priorities are the
    baseline; the short supplemental list closes gaps in those older rosters.
    No title is added or manually removed from the source database.
    """
    rosters = config.get("roulette_groups", {})
    protected = set(config.get("legends_comedians", []))
    for group in ("well_known", "b_tier", "classic_older"):
        protected.update(rosters.get(group, []))
    protected.update(config.get("coverage_priority", {}).get("established_extra", []))
    # These were earlier curated as respected B-tier/underrated performers.
    protected.update(config.get("coverage_priority", {}).get("select_underrated", []))
    protected.update(config.get("unrated_additional_established", []))
    return {norm(name).strip() for name in protected if name}


def exclude_unrated_unknown(record: dict, config: dict, protected=None) -> bool:
    """Hide unvoted specials from non-established comics in movie catalogs.

    A zero-vote special is not 'bad': this is just a leaner-catalog preference.
    Keep source records for future reclassification and reversal. Never apply
    this rule to TV shows or YouTube clips, which have different rating data.
    """
    if not config.get("alphabet_unrated_only_established", False):
        return False
    if int(record.get("vote_count") or 0) > 0:
        return False
    protected = established_unrated_performers(config) if protected is None else protected
    return norm(record.get("performer") or "").strip() not in protected


def established_low_rated_performers(config: dict) -> set[str]:
    """Base A/B roster plus specifically reviewed recognizable/underrated acts."""
    protected = established_unrated_performers(config)
    protected.update(norm(name).strip() for name in config.get("quality_additional_established", []) if name)
    return protected



def exclude_low_rated_unknown(record: dict, config: dict, protected=None) -> bool:
    """Hide weakly reviewed movie specials only for non-established performers.

    A rating is not a universal measure of comedy quality. This preference
    accepts sparse ratings only as a curation signal for unknown acts. A/B,
    respected underrated comics, TV shows, YouTube and ensemble events remain.
    A one-vote rating alone is never treated as reliable proof of bad comedy.
    The source database is always retained for a reversible reclassification.
    """
    if not config.get("alphabet_low_rated_only_established", False):
        return False
    votes = int(record.get("vote_count") or 0)
    score = float(record.get("vote_average") or 0)
    if votes < int(config.get("alphabet_low_rating_min_votes", 5)):
        return False
    if score >= float(config.get("alphabet_low_rating_cutoff", 6.0)):
        return False
    protected = established_low_rated_performers(config) if protected is None else protected
    return norm(record.get("performer") or "").strip() not in protected


def display_title(record: dict) -> str:
    return str(record.get("title", "")).strip() or "Untitled Special"


def release_date(record: dict) -> date:
    value = str(record.get("release_date", ""))
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return date(1900, 1, 1)


def alphabetical_sort_key(record: dict):
    return (performer_sort_name(record["performer"]), release_date(record), norm(display_title(record)))


def take_distinct_performers(records: list[dict], limit: int, salt: str, today: date | None = None) -> list[dict]:
    # Different selection every ISO week, consistent across all devices in that week.
    week = (today or date.today()).isocalendar()
    seed = hashlib.sha256(f"{week.year}-W{week.week}-{salt}".encode()).digest()
    rng = random.Random(int.from_bytes(seed, "big"))
    performers = defaultdict(list)
    for record in records:
        name = performer_sort_name(record.get("performer", ""))
        if name:
            performers[name].append(record)
    names = list(performers)
    rng.shuffle(names)
    chosen = []
    for name in names[:limit]:
        options = performers[name]
        chosen.append(options[rng.randrange(len(options))])
    return chosen


ROULETTE_TIERS = ("well_known", "b_tier", "classic_older", "discovery")


def weekly_roulette(records: list[dict], config: dict, today: date) -> tuple[list[dict], dict]:
    """Pick a balanced 15/15/15/15 weekly mix, then shuffle without tier blocks.

    The first three tier pools are intentionally curated by comedian, not by
    special release year. Discovery pulls from other well-rated performers.
    Missing TMDB performers are reported instead of inventing unavailable titles.
    """
    pools = config.get("roulette_groups")
    if not pools:
        # Backward compatibility for older configurations and test fixtures.
        selected = take_distinct_performers(records, config["weekly_roulette_count"], "roulette", today)
        return selected, {}

    group_size = int(config.get("roulette_group_size", 15))
    requested = int(config.get("weekly_roulette_count", 4 * group_size))
    if group_size < 1 or requested != 4 * group_size:
        raise ValueError("weekly_roulette_count must equal four times roulette_group_size")

    membership = {}
    for tier in ROULETTE_TIERS:
        for performer in pools.get(tier, []):
            name = performer_sort_name(performer)
            if name in membership and membership[name] != tier:
                raise ValueError(f"Comedian {performer!r} appears in two Roulette tiers")
            membership[name] = tier

    by_tier = {tier: [] for tier in ROULETTE_TIERS}
    available_by_tier = {tier: set() for tier in ROULETTE_TIERS}
    for record in records:
        name = performer_sort_name(record.get("performer", ""))
        if not name:
            continue
        tier = membership.get(name)
        if tier is None:
            # New, unreviewed performers are eligible for discovery only when
            # TMDB explicitly identifies the special as English-language.
            # Older cached records without language metadata must be curated.
            if record.get("original_language") != "en":
                continue
            tier = "discovery"
        if tier == "discovery" and (
            float(record.get("vote_average") or 0) < config.get("roulette_discovery_min_rating", 6.5)
            or int(record.get("vote_count") or 0) < config.get("roulette_discovery_min_votes", 5)
        ):
            continue
        by_tier[tier].append(record)
        available_by_tier[tier].add(name)

    chosen = []
    details = {}
    for tier in ROULETTE_TIERS:
        picks = take_distinct_performers(by_tier[tier], group_size, f"roulette-{tier}", today)
        chosen.extend(picks)
        details[tier] = {
            "target": group_size,
            "selected": len(picks),
            "available_comedians": len(available_by_tier[tier]),
            "selected_comedians": [r["performer"] for r in picks],
        }
        if tier != "discovery":
            details[tier]["not_yet_indexed"] = sorted(
                name for name in pools.get(tier, [])
                if performer_sort_name(name) not in available_by_tier[tier]
            )

    week = today.isocalendar()
    seed = hashlib.sha256(f"{week.year}-W{week.week}-roulette-final-shuffle".encode()).digest()
    random.Random(int.from_bytes(seed, "big")).shuffle(chosen)
    return chosen, details



def non_standup_movie(record: dict, config: dict) -> bool:
    """Keep confidently non-stand-up titles out of movie catalogs.

    These conservative, reversible rules are deliberately narrow: a comedy
    special involving music (Bo Burnham, Tim Minchin, Bill Bailey, etc.) is
    NOT excluded just because it includes music. We don't treat absent genre
    metadata as proof that a performance isn't stand-up.
    """
    person = norm(record.get("performer") or "").strip()
    if person in {norm(x).strip() for x in config.get("non_standup_performers", [])}:
        return True
    title = norm(record.get("title") or "").strip()
    return any(title == norm(x).strip() for x in config.get("non_standup_titles", []))


def ranking_extras(record: dict, config: dict) -> bool:
    """Exclude compilations/retrospectives from *rankings*, not alphabeticals."""
    title = norm(record.get("title") or "").strip()
    return any(title == norm(x).strip() for x in config.get("ranking_excluded_titles", []))


def ranked_specials(records: list[dict], config: dict) -> tuple[list[dict], list[dict]]:
    """Top Rated rewards rating consensus; Fan Favorites also values reputation.

    Use Bayesian shrinkage so a very small vote sample doesn't dominate;
    Fan Favorites adds a modest, transparent A/B-comedian prior rather than
    manually forcing in any one performer. This is an editorial proxy, not a
    measurement of social-media followers or a real audience poll.
    """
    rated_limit = int(config.get("ranked_list_size", 150))
    fan_limit = int(config.get("fan_favorites_size", rated_limit))
    min_rated_votes = int(config.get("top_rated_min_votes", 20))
    min_favorite_votes = int(config.get("fan_favorites_min_votes", 10))
    min_favorite_rating = float(config.get("fan_favorites_min_rating", 6.5))
    if min(rated_limit, fan_limit, min_rated_votes, min_favorite_votes) < 1:
        raise ValueError("Ranking sizes and vote thresholds must be positive")

    def valid(record):
        language = record.get("original_language")
        if config.get("rankings_english_only", False) and language and language != "en":
            return False
        if set(record.get("tags") or []) & {"roast", "event"}:
            return False
        if non_standup_movie(record, config) or ranking_extras(record, config):
            return False
        return bool(record.get("performer")) and float(record.get("vote_average") or 0) > 0

    pool = [r for r in records if valid(r)]

    def weighted_rating(record, m, prior):
        votes = int(record.get("vote_count") or 0)
        score = float(record.get("vote_average") or 0)
        return (votes * score + m * prior) / (votes + m)

    top_rated = [r for r in pool if int(r.get("vote_count") or 0) >= min_rated_votes]
    top_rated.sort(key=lambda r: (
        -weighted_rating(r, 25, 6.5),
        -float(r.get("vote_average") or 0),
        -int(r.get("vote_count") or 0),
        norm(display_title(r)),
    ))

    fan_favorites = [r for r in pool if (
        int(r.get("vote_count") or 0) >= min_favorite_votes
        and float(r.get("vote_average") or 0) >= min_favorite_rating
    )]
    tiers = config.get("roulette_groups", {})
    tier_bonuses = {}
    for group, bonus in (("well_known", 0.45), ("b_tier", 0.30), ("classic_older", 0.30)):
        for name in tiers.get(group, []):
            tier_bonuses[norm(name)] = max(tier_bonuses.get(norm(name), 0), bonus)
    for name in config.get("coverage_priority", {}).get("established_extra", []):
        tier_bonuses[norm(name)] = max(tier_bonuses.get(norm(name), 0), 0.25)

    def fan_score(record):
        vote_count = int(record.get("vote_count") or 0)
        performer_bonus = tier_bonuses.get(norm(record.get("performer") or ""), 0)
        return (weighted_rating(record, 25, 6.6)
                + 0.11 * math.log10(vote_count + 1) + performer_bonus)

    fan_favorites.sort(key=lambda r: (
        -fan_score(r),
        -float(r.get("vote_average") or 0),
        -int(r.get("vote_count") or 0),
        norm(display_title(r)),
    ))
    return top_rated[:rated_limit], fan_favorites[:fan_limit]


def month_window_start(today: date, months: int) -> date:
    year = today.year
    month = today.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(today.day, 28)
    return date(year, month, day)


def known_performer_names(records: list[dict], config: dict, roster_names=()) -> list[str]:
    """Use existing performer credits, curated acts and (when available) Wikidata.

    This allows unnamed titles to be attributed without treating every title
    prefix or show host as the comedian. Longest names are tested first.
    """
    names = set(config.get("legends_comedians", [])) | set(config.get("viral_rising_comedians", []))
    for roster in config.get("roulette_groups", {}).values():
        names.update(roster)
    names.update(r.get("performer") for r in records if r.get("performer"))
    names.update(roster_names)
    by_normalized = {}
    for name in names:
        if not isinstance(name, str) or not (3 <= len(name.strip()) <= 80):
            continue
        key = norm(name).strip()
        if key:
            by_normalized.setdefault(key, name.strip())
    return sorted(by_normalized.values(), key=lambda x: (-len(x), norm(x)))


def recognizable_performer(title: str, config: dict, known_names=(), *,
                           name_lookup=None, prefix_index=None) -> str | None:
    """Recover only performers whose names are clearly stated in the title.

    Avoid inferring from a generic prefix like 'One-Night Stand' or from the
    presenter of a different comedian's special.
    """
    names = known_names or known_performer_names([], config)
    names_by_key = name_lookup if name_lookup is not None else {norm(name).strip(): name for name in names}
    text = title.strip()

    # Series with an explicit featured act after the series title.
    match = re.match(
        r"(?i)^(?:comedy central presents|hbo comedy half.hour|one.night stand):\s*(.+)$", text
    )
    if match:
        featured = match.group(1).strip()
        known = names_by_key.get(norm(featured).strip())
        if known:
            return known
        # Series episode names can be the full performer credit even if the
        # comedian is absent from our existing roster (e.g. Earthquake).
        # Accept only plausible proper names, never 'Episode 6' / 'Best Of'.
        words = featured.split()
        if (1 <= len(words) <= 4 and len(featured) <= 60 and
                all(re.match(r"^[A-ZÀ-Ý][\wÀ-ÿ.'’\-]*$", word) for word in words) and
                not any(norm(word) in {'episode', 'season', 'special', 'best', 'of', 'show'} for word in words)):
            return featured
        return None

    # 'Gabriel Iglesias Presents Rick Gutierrez: ...' is Rick's set, NOT
    # Gabriel's; similarly with 'The Gentleman Jerry Rocha'. Require a known
    # presenting performer and a capitalized 2-4 word guest name.
    match = re.match(r"(?i)^(.{3,80}?)\s+presents\s+(?:the gentleman\s+)?([^:]+?)(?::|$)", text)
    if match and norm(match.group(1)).strip() in names_by_key:
        guest = match.group(2).strip()
        if (2 <= len(guest.split()) <= 4 and
                all(word[:1].isupper() for word in guest.split())):
            return names_by_key.get(norm(guest).strip(), guest)

    # Normal title prefixes only need names beginning with the same character.
    # The full normalized lookup remains available for TV showcases and the
    # 'presents <performer>' pattern. This keeps daily 3,000-title builds fast.
    candidate_names = (prefix_index.get(text[:1].casefold(), ())
                       if prefix_index is not None else
                       (n for n in names if n[:1].casefold() == text[:1].casefold()))
    for name in candidate_names:
        # Exact full-name prefix only. Punctuation or common performance-title
        # separators must immediately follow; avoid matching 'Dave Attellton'.
        if text[:len(name)].casefold() != name.casefold():
            continue
        suffix = text[len(name):]
        if not suffix or re.match(
            r"(?i)^(?:\s*[:–—-]\s*|['’]s\b|\s+(?:is|live|at|in|on|won.t|stand.?up|comedy|special)\b|\?\s+)",
            suffix,
        ):
            return name
    return None


def is_event_record(record: dict, config: dict) -> bool:
    title = display_title(record).casefold()
    terms = tuple(config.get("roast_title_terms", []))
    return bool(set(record.get("tags") or []) & {"roast", "event"} or
                any(term.casefold() in title for term in terms))


def categories(records: list[dict], config: dict, today: date | None = None, *, roster_names=()):
    today = today or date.today()
    groups = config["alphabet_groups"]
    validate_groups(groups)
    excluded = set(config.get("excluded_ids", []))
    overrides = config.get("performer_overrides", {})
    tag_overrides = config.get("tag_overrides", {})
    accepted, unassigned = [], []
    known_names = known_performer_names(records, config, roster_names)
    name_lookup = {norm(name).strip(): name for name in known_names}
    prefix_index = defaultdict(list)
    for name in known_names:
        prefix_index[name[:1].casefold()].append(name)
    protected_unrated = established_unrated_performers(config)
    protected_low_rated = established_low_rated_performers(config)
    english_only = bool(config.get("english_language_only", False))
    non_english_people = performer_non_english_evidence(records) if english_only else set()

    # Resolve high-confidence credits before duplicate detection. Do not
    # rewrite data/specials.json; questionable titles remain in review.
    prepared = []
    for source in records:
        record = dict(source)
        if record.get("id") in overrides:
            record["performer"] = overrides[record["id"]]
        else:
            corrected = recognizable_performer(display_title(record), config, known_names,
                                               name_lookup=name_lookup, prefix_index=prefix_index)
            if corrected:
                record["performer"] = corrected
        record["tags"] = sorted(set(record.get("tags") or []) | set(tag_overrides.get(record.get("id"), [])))
        prepared.append(record)
    deduped = dedupe_same_special(prepared)
    for record in deduped:
        if (record["id"] in excluded or release_date(record) > today
                or too_poorly_rated(record, config)
                or non_standup_movie(record, config)
                or not movie_allowed(record, english_only, non_english_people)):
            continue
        if is_event_record(record, config):
            continue
        if not record.get("performer") or bucket_for(record["performer"], groups) is None:
            # Preserve the independent unmatched-title review pool unchanged.
            unassigned.append(record)
        elif (not exclude_unrated_unknown(record, config, protected_unrated)
              and not exclude_low_rated_unknown(record, config, protected_low_rated)):
            accepted.append(record)

    accepted.sort(key=alphabetical_sort_key)
    alphabetical = [[] for _ in groups]
    for record in accepted:
        if record["id"] not in set(config.get("alphabet_duplicate_movie_ids", [])):
            alphabetical[bucket_for(record["performer"], groups)].append(record)

    fresh_start = month_window_start(today, config["new_specials_months"])
    new = [r for r in accepted if release_date(r) >= fresh_start]
    new.sort(key=lambda r: (release_date(r), display_title(r)), reverse=True)

    # A hand-picked early stand-up generation. Their newer specials belong here
    # too; career era matters, not the date on the individual special.
    legend_names = {norm(n) for n in config.get("legends_comedians", [])}
    legends = [r for r in accepted if norm(r["performer"]) in legend_names]

    # Less famous, reasonably rated works. Tune after we see real title counts.
    gems = [
        r for r in accepted
        if float(r.get("popularity", 999)) <= config["hidden_gems_max_popularity"]
        and float(r.get("vote_average", 0)) >= config["hidden_gems_min_rating"]
        and int(r.get("vote_count", 0)) >= config["hidden_gems_min_votes"]
    ]
    roulette, _ = weekly_roulette(accepted, config, today)
    hidden = take_distinct_performers(gems, config["weekly_hidden_gems_count"], "hidden", today)

    # Seeded rising performers include Kill Tony alumni and comics discovered
    # through social media. Refresh picks weekly as the source catalog grows.
    viral_names = {norm(n) for n in config.get("viral_rising_comedians", [])}
    viral_candidates = [r for r in accepted if norm(r["performer"]) in viral_names]
    viral = take_distinct_performers(
        viral_candidates, config.get("weekly_viral_rising_count", 30), "viral-rising", today
    )
    roasts = [
        r for r in deduped
        if r.get("id") not in excluded and release_date(r) <= today
        and not non_standup_movie(r, config)
        and movie_allowed(r, english_only, non_english_people)
        and is_event_record(r, config)
    ]
    roasts.sort(key=lambda r: (release_date(r), display_title(r)), reverse=True)

    # Backward compatible with the existing offline test fixtures; only the
    # actual installed addon's config enables the new catalogs and ordering.
    if config.get("enable_ranked_150", False):
        rated, favorites = ranked_specials(accepted, config)
        outputs = [
            ("new-specials", "New Specials", new),
            ("top-150-rated", "Top Rated", rated),
            ("fan-favorites-150", "Fan Favorites", favorites),
            ("comedy-roulette", "Comedy Roulette", roulette),
            ("hidden-gems", "Hidden Gems", hidden),
            ("comedy-legends", "Comedy Legends", legends),
            ("viral-and-rising", "Viral & Rising Comedians", viral),
            ("roasts-events", "Roasts & Comedy Events", roasts),
        ]
        for index, group in enumerate(groups):
            outputs.append((f"comedians-{index + 1:02d}",
                            f"Comedians {group}" if index == 0 else group, alphabetical[index]))
        return outputs, unassigned

    outputs = [
        ("comedy-roulette", "Comedy Roulette", roulette),
        ("new-specials", "New Specials", new),
        ("hidden-gems", "Hidden Gems", hidden),
        ("comedy-legends", "Comedy Legends", legends),
        ("viral-and-rising", "Viral & Rising Comedians", viral),
    ]
    for index, group in enumerate(groups):
        outputs.append((f"comedians-{index + 1:02d}", f"Comedians {group}" if index == 0 else group, alphabetical[index]))
    outputs += [
        ("roasts-events", "Roasts & Comedy Events", roasts),
    ]
    return outputs, unassigned


def meta_preview(record: dict) -> dict:
    preview = {"id": record["id"], "type": "movie", "name": display_title(record)}
    if record.get("poster"):
        preview["poster"] = record["poster"]
    elif record.get("poster_path"):
        preview["poster"] = "https://image.tmdb.org/t/p/w500" + record["poster_path"]
    if release_date(record).year > 1900:
        preview["releaseInfo"] = str(release_date(record).year)
    return preview


def build(records: list[dict], config: dict, out_dir: Path, today: date | None = None) -> dict:
    # Wikidata roster is a discovery source, not a required runtime dependency.
    # The data file is saved by GitHub Actions on successful refreshes.
    state = read_json(ROOT / "data" / "discovery_state.json", {})
    roster_names = [entry["name"] for entry in state.get("roster", []) if entry.get("name")]
    groups, unassigned = categories(records, config, today, roster_names=roster_names)
    if out_dir.exists():
        # Scoped replacement only, never remove a workspace/repository root.
        catalog_dir = out_dir / "catalog"
        if catalog_dir.exists():
            shutil.rmtree(catalog_dir)
        for resource_dir in (out_dir / "meta", out_dir / "stream"):
            if resource_dir.exists():
                shutil.rmtree(resource_dir)

    # YouStream exposes media type ``youtube``. The primary catalogs are movie
    # type, so mixing its youtube-typed previews directly into movie rows would
    # cause unreliable navigation. In merged mode, wrap each selected video in
    # a movie-type card with static metadata and direct YouTube stream choices.
    youtube_rows = {}
    merged_youtube = {}
    youtube_resources = {}
    if config.get("enable_youtube_preview_catalogs", False):
        videos = read_json(ROOT / "data/youtube_candidates.json", [])
        if config.get("merge_youtube_into_existing_catalogs", False):
            from youtube_catalogs import merged_movie_previews
            merged_youtube, youtube_resources = merged_movie_previews(videos, config, today)
        else:
            from youtube_catalogs import preview_rows
            youtube_rows = preview_rows(videos, config, today)
    # Publish anthology performances as a proper series/episode catalog. Native
    # TMDB show/episode IDs let other addons resolve streams; no playback is
    # implied by our catalog metadata and no fake movie IDs are used.
    tv_previews, tv_metadatas, tv_counts = [], {}, {}
    if config.get("enable_tv_series_catalog", False):
        from tv_catalogs import build_tv_series
        tv_previews, tv_metadatas, tv_counts = build_tv_series(
            read_json(ROOT / "data/tv_episode_candidates.json", []),
            english_only=bool(config.get("english_language_only", False)),
            exclude_multilingual=config.get("exclude_multilingual_tv_shows", []),
            priority_order=config.get("tv_show_priority_order", []))
    resources = ["catalog"]
    if merged_youtube:
        resources.extend([
            {"name": "meta", "types": ["movie"], "idPrefixes": ["standupyt_"]},
            {"name": "stream", "types": ["movie"], "idPrefixes": ["standupyt_"]},
        ])
    if tv_metadatas:
        # Restrict the declared namespace to known TV shows; don't intercept
        # unrelated `tmdb:` metadata requests in other installed addons.
        resources.append({"name": "meta", "types": ["series"],
                          "idPrefixes": sorted(tv_metadatas.keys())})
    manifest = {
        "id": config["addon_id"],
        "version": "1.3.0" if merged_youtube else ("1.2.0" if youtube_rows else "1.1.0"),
        "name": config["addon_name"],
        "description": "Automatically organized stand-up comedy catalogs; YouTube previews may open externally.",
        "resources": resources,
        "types": (["movie", "youtube"] if youtube_rows else ["movie"]) + (["series"] if tv_metadatas else []),
        "catalogs": [],
        "behaviorHints": {"configurable": False, "configurationRequired": False},
    }
    counts = {}
    # A single existing category now contains BOTH verified TMDB movies and
    # candidate YouTube cards; there are no extra YouTube home-screen rows.
    # Full YouTube specials go into the proper first-name alphabetical section,
    # after that performer's dated movies (upload year is not release year).
    full_by_bucket = defaultdict(list)
    if merged_youtube:
        for entry in merged_youtube.get("youtube-full-specials", []):
            if (entry["meta"]["id"] in set(config.get("excluded_youtube_ids", []))
                    or norm(entry["performer"]) in {norm(x) for x in config.get("non_standup_performers", [])}):
                continue
            index = bucket_for(entry["performer"], config["alphabet_groups"])
            if index is not None:
                full_by_bucket[f"comedians-{index + 1:02d}"].append(entry)

    for identifier, title, records_in_catalog in groups:
        movie_items = [meta_preview(r) for r in records_in_catalog]
        if merged_youtube:
            if identifier == "viral-and-rising":
                movie_items.extend(e["meta"] for e in merged_youtube["youtube-viral-rising"])
            elif identifier == "hidden-gems":
                movie_items.extend(e["meta"] for e in merged_youtube["youtube-hidden-gems"])
            elif identifier in full_by_bucket:
                extras = full_by_bucket[identifier]
                # Keep first-name order, and each comedian's chronological
                # movie specials ahead of their YouTube-upload candidates.
                tuples = [(performer_sort_name(r["performer"]), 0, release_date(r).isoformat(),
                           norm(display_title(r)), meta_preview(r))
                          for r in records_in_catalog]
                tuples.extend((performer_sort_name(e["performer"]), 1, e["uploaded"],
                               norm(e["meta"]["name"]), e["meta"]) for e in extras)
                tuples.sort(key=lambda t: t[:4])
                movie_items = [t[4] for t in tuples]
        manifest["catalogs"].append({
            "id": identifier,
            "type": "movie",
            "name": title,
            "pageSize": PAGE_SIZE,
            "extra": [{"name": "skip", "isRequired": False}],
        })
        counts[title] = len(movie_items)
        catalog_path = out_dir / "catalog" / "movie"
        for skip in range(0, max(1, len(movie_items)), PAGE_SIZE):
            items = movie_items[skip:skip + PAGE_SIZE]
            name = f"{identifier}.json" if skip == 0 else f"{identifier}/skip={skip}.json"
            write_json(catalog_path / name, {"metas": items})
        # Some clients explicitly ask for skip=0.
        write_json(catalog_path / identifier / "skip=0.json", {"metas": movie_items[:PAGE_SIZE]})
        # Explicit end-of-catalog page: some clients continue requesting the
        # next skip even after the last partial page. Return an empty list,
        # not a GitHub Pages 404 (which can leave a spinner retrying).
        terminal_skip = ((len(movie_items) + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        if terminal_skip:
            write_json(catalog_path / identifier / f"skip={terminal_skip}.json", {"metas": []})
    if youtube_rows:
        # Put the preview rows into the *same* addon without replacing the
        # existing movie categories or modifying the Nuvio collection JSON.
        names = {
            "youtube-viral-rising": "Viral & Rising — YouTube Sets (Preview)",
            "youtube-hidden-gems": "Hidden Gems — YouTube Sets (Preview)",
            "youtube-full-specials": "Full Stand-Up Specials — YouTube (Preview)",
        }
        for identifier, label in names.items():
            previews = youtube_rows.get(identifier, [])
            if not previews:
                continue
            manifest["catalogs"].append({
                "id": identifier, "type": "youtube", "name": label,
                "pageSize": PAGE_SIZE,
                "extra": [{"name": "skip", "isRequired": False}],
            })
            counts[label] = len(previews)
            folder = out_dir / "catalog" / "youtube"
            for skip in range(0, len(previews), PAGE_SIZE):
                file = f"{identifier}.json" if skip == 0 else f"{identifier}/skip={skip}.json"
                write_json(folder / file, {"metas": previews[skip:skip + PAGE_SIZE]})
            write_json(folder / identifier / "skip=0.json", {"metas": previews[:PAGE_SIZE]})
            end = ((len(previews) + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
            write_json(folder / identifier / f"skip={end}.json", {"metas": []})
    if tv_metadatas:
        title = "Stand-Up TV Shows"
        identifier = "standup-tv-series"
        manifest["catalogs"].append({
            "id": identifier, "type": "series", "name": title,
            "pageSize": PAGE_SIZE,
            "extra": [{"name": "skip", "isRequired": False}],
        })
        counts[title] = len(tv_previews)
        folder = out_dir / "catalog" / "series"
        for skip in range(0, len(tv_previews), PAGE_SIZE):
            name = f"{identifier}.json" if skip == 0 else f"{identifier}/skip={skip}.json"
            write_json(folder / name, {"metas": tv_previews[skip:skip + PAGE_SIZE]})
        write_json(folder / identifier / "skip=0.json", {"metas": tv_previews[:PAGE_SIZE]})
        terminal = ((len(tv_previews) + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        write_json(folder / identifier / f"skip={terminal}.json", {"metas": []})
        for show_id, metadata in tv_metadatas.items():
            write_json(out_dir / "meta" / "series" / f"{show_id}.json", {"meta": metadata})
    if youtube_resources:
        for alias, entry in youtube_resources.items():
            vid = entry["video_id"]
            # Static GitHub Pages routes can serve Stremio meta/stream resources.
            # The in-app option is experimental on Nuvio TV; the external link
            # should let the TV offer its browser/YouTube-app choice.
            write_json(out_dir / "meta" / "movie" / f"{alias}.json", {"meta": entry["meta"]})
            write_json(out_dir / "stream" / "movie" / f"{alias}.json", {
                "streams": [
                    {"name": "YouTube (try in app)", "title": "YouTube · Experimental in-app playback", "ytId": vid},
                    {"name": "YouTube (open externally)", "title": "YouTube · Browser / YouTube app", "externalUrl": f"https://www.youtube.com/watch?v={vid}"},
                ]
            })
    write_json(out_dir / "manifest.json", manifest)
    report = {"counts": counts, "total_unique_records": len(unique_records(records)), "needs_review": unassigned}
    if config.get("alphabet_unrated_only_established", False):
        # Compare the same build with the preference disabled, so this report
        # lists exactly what the unrated rule hides, not unrelated quality cuts.
        original_config = {**config, "alphabet_unrated_only_established": False}
        before, _ = categories(records, original_config, today, roster_names=roster_names)
        before_entries = {r["id"]: r for key, _, rows in before
                          if key.startswith("comedians-") for r in rows}
        after_entries = {r["id"]: r for key, _, rows in groups
                         if key.startswith("comedians-") for r in rows}
        hidden = sorted((r for rid, r in before_entries.items() if rid not in after_entries),
                        key=alphabetical_sort_key)
        kept_unrated = sorted((r for r in after_entries.values()
                               if int(r.get("vote_count") or 0) == 0),
                              key=alphabetical_sort_key)
        summary = {
            "policy": "Hide zero-vote movies by comics outside the curated A/B roster",
            "applies_to": "All movie catalogs built from the accepted performer pool; not TV or YouTube",
            "reversible": True,
            "original_alphabetical_movies": len(before_entries),
            "remaining_alphabetical_movies": len(after_entries),
            "unrated_movies_hidden": len(hidden),
            "unrated_established_movies_kept": len(kept_unrated),
        }
        report["unrated_cleanup"] = summary
        write_json(out_dir / "unrated_cleanup_report.json", {
            "summary": summary,
            "hidden": [{"id": r["id"], "performer": r["performer"],
                        "title": r["title"], "release_date": r.get("release_date", "")}
                       for r in hidden],
            "kept_unrated": [{"id": r["id"], "performer": r["performer"],
                              "title": r["title"]} for r in kept_unrated],
        })
    if config.get("alphabet_low_rated_only_established", False):
        # Isolate the low-rating policy: unrated cleanup and earlier exclusions
        # remain enabled in both comparisons, so the counts cannot overlap.
        before_config = {**config, "alphabet_low_rated_only_established": False}
        before, _ = categories(records, before_config, today, roster_names=roster_names)
        before_entries = {r["id"]: r for key, _, rows in before
                          if key.startswith("comedians-") for r in rows}
        after_entries = {r["id"]: r for key, _, rows in groups
                         if key.startswith("comedians-") for r in rows}
        hidden = sorted((r for ident, r in before_entries.items() if ident not in after_entries),
                        key=alphabetical_sort_key)
        protected = established_low_rated_performers(config)
        kept = sorted((r for r in after_entries.values()
                       if int(r.get("vote_count") or 0) >= int(config.get("alphabet_low_rating_min_votes", 5))
                       and float(r.get("vote_average") or 0) < float(config.get("alphabet_low_rating_cutoff", 6.0))
                       and norm(r.get("performer", "")).strip() in protected),
                      key=alphabetical_sort_key)
        summary = {
            "policy": "Hide weakly reviewed movies by non-established performers",
            "min_votes": int(config.get("alphabet_low_rating_min_votes", 5)),
            "rating_below": float(config.get("alphabet_low_rating_cutoff", 6.0)),
            "low_rated_movies_hidden": len(hidden),
            "hidden_low_sample_1_to_4_votes": sum(1 for r in hidden if 1 <= int(r.get("vote_count") or 0) <= 4),
            "hidden_5_plus_votes": sum(1 for r in hidden if int(r.get("vote_count") or 0) >= 5),
            "low_rated_established_movies_kept": len(kept),
            "reversible": True,
            "tv_series_untouched": True,
        }
        report["quality_cleanup"] = summary
        write_json(out_dir / "quality_cleanup_report.json", {
            "summary": summary,
            "hidden": [{"id": r["id"], "performer": r["performer"],
                        "title": r["title"], "votes": r.get("vote_count"),
                        "rating": r.get("vote_average")} for r in hidden],
            "kept_established": [{"id": r["id"], "performer": r["performer"],
                                   "title": r["title"], "votes": r.get("vote_count"),
                                   "rating": r.get("vote_average")} for r in kept],
        })
    if tv_metadatas:
        report["tv_series"] = {
            "series_count": len(tv_metadatas), "episode_count": sum(tv_counts.values()),
            "episodes_by_show": tv_counts, "playback_verified": False,
            "stream_source": "Other installed Nuvio stream addons; not hosted by this addon",
        }
    if merged_youtube:
        report["youtube_merged"] = {
            "unverified_playback": True, "fallback": "YouTube external link",
            "counts": {"viral_and_rising_added": len(merged_youtube["youtube-viral-rising"]),
                       "hidden_gems_added": len(merged_youtube["youtube-hidden-gems"]),
                       "alphabetical_full_specials_added": sum(len(v) for v in full_by_bucket.values())},
        }
    if youtube_rows:
        report["youtube_preview"] = {"type": "youtube", "requires": "YouStream addon", "unverified_playback": True,
                                     "counts": {k: len(v) for k, v in youtube_rows.items()}}
    if config.get("enable_ranked_150", False):
        report["rankings"] = {
            "source": "TMDB audience vote_average + vote_count",
            "top_rated": f"Bayesian-weighted TMDB average (25-vote prior of 6.5), minimum {config.get('top_rated_min_votes', 20)} votes; top {config.get('ranked_list_size', 150)}",
            "fan_favorites": f"Bayesian-weighted TMDB ratings plus participation and modest A/B-roster bonus; top {config.get('fan_favorites_size', config.get('ranked_list_size', 150))}; editorial proxy, not a dedicated audience poll",
            "overlap_allowed": True,
            "language_filter": "Exclude explicitly non-English metadata; records missing original_language remain eligible until refreshed" if config.get("rankings_english_only", False) else "All languages",
        }
    if config.get("roulette_groups"):
        # Every alphabet row already contains validated, eligible performers.
        eligible = [record for identifier, _, items in groups
                    if identifier.startswith("comedians-") for record in items]
        _, breakdown = weekly_roulette(eligible, config, today or date.today())
        report["roulette_mix"] = breakdown
    if config.get("english_language_only", False):
        source_with_language = [r for r in records if language_code(r.get("original_language"))]
        published_ids = {r["id"] for identifier, _, items in groups for r in items}
        published_movie_records = {r["id"]: r for identifier, _, items in groups
                                   for r in items if identifier.startswith("comedians-")}
        source_unknown = [r for r in records if not language_code(r.get("original_language"))]
        report["english_language_policy"] = {
            "status": "Known non-English excluded; unknown language needs confirmation",
            "known_non_english_source_records": sum(
                language_code(r.get("original_language")) not in {"en", "eng"}
                for r in source_with_language),
            "unknown_language_source_records": len(source_unknown),
            "unknown_language_alphabetical_records": sum(
                not language_code(r.get("original_language"))
                for r in published_movie_records.values()),
            "known_non_english_published_movie_records": sum(
                language_code(r.get("original_language")) not in {"", "en", "eng"}
                for r in published_movie_records.values()),
            "multilingual_tv_shows_excluded": config.get("exclude_multilingual_tv_shows", []),
            "note": "TMDB original_language is production metadata, not verified spoken audio. "
                    "Unknowns remain eligible pending automated metadata backfill; "
                    "YouTube uploads without audio-language metadata require review.",
        }
    write_json(out_dir / "build_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records = read_json(args.input, [])
    config = read_json(args.config)
    report = build(records, config, args.output)
    # GitHub already runs build_catalogs.py on every refresh. Produce a
    # coverage report here so users never need to edit refresh.yml again.
    if args.output.resolve() == DEFAULT_OUTPUT.resolve():
        from audit_coverage import coverage_report
        audit = coverage_report(config, records,
                                read_json(ROOT / 'data/tv_episode_candidates.json', []),
                                read_json(ROOT / 'data/youtube_candidates.json', []),
                                read_json(ROOT / 'data/discovery_state.json', {}))
        write_json(args.output / 'coverage_report.json', audit)
        print(f"Priority coverage: {audit['summary']['priority_comedians_total']} comedians; "
              f"{audit['summary']['priority_comedians_without_movie_records']} have no standalone movie record; "
              f"{audit['summary']['unmatched_work_leads']} independent metadata leads need review")
    for label, count in report["counts"].items():
        print(f"{label}: {count}")
    print(f"Unassigned for review: {len(report['needs_review'])}")


if __name__ == "__main__":
    main()
