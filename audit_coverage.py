"""Evidence-based comedian coverage audit; never inserts specials.

'Catalogued' means the project has a movie metadata record, *not* that all
known performances have been found or any source can play them. Unmatched
independently discovered titles and TV/YouTube review leads remain visible.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from build_catalogs import ROOT, norm, read_json, write_json


def comedian_key(name: str) -> str:
    return " ".join(norm(name).split())


def roster_tiers(config: dict) -> dict[str, dict]:
    """Prioritize recognizable A/B performers and a *short* underrated list.

    This is a search scheduling policy, not a claim about artistic merit.
    All entries are comedian names, never special titles/IDs.
    """
    result = {}
    def add(names: Iterable[str], tier: str):
        for name in names:
            key = comedian_key(name)
            if key and key not in result:
                result[key] = {"name": name, "priority": tier}
    add(config.get("legends_comedians", []), "established")
    groups = config.get("roulette_groups", {})
    for tier in ("well_known", "b_tier", "classic_older"):
        add(groups.get(tier, []), "established")
    priority = config.get("coverage_priority", {})
    add(priority.get("established_extra", []), "established")
    add(priority.get("select_underrated", []), "select_underrated")
    return result


def work_in_catalog(work: dict, by_imdb: set[str], by_tmdb: set[str],
                    by_performer_title: set[tuple[str, str]]) -> bool:
    imdb = str(work.get("imdb") or "")
    tmdb = str(work.get("tmdb") or "")
    if imdb and imdb in by_imdb or tmdb and tmdb in by_tmdb:
        return True
    performer, title = comedian_key(work.get("performer") or ""), norm(work.get("name") or "")
    return bool(performer and title and (performer, title) in by_performer_title)


def coverage_report(config: dict, movies: list[dict], tv: list[dict],
                    youtube: list[dict], state: dict) -> dict:
    """Return evidence and actionable gaps, never an unearned 'complete' flag."""
    tiers = roster_tiers(config)
    movie_titles = defaultdict(set)
    tv_episodes = defaultdict(set)
    yt_videos = defaultdict(set)
    found_ids = set()
    found_tmdb = set()
    matched_title = set()
    for item in movies:
        key = comedian_key(item.get("performer") or "")
        title = norm(item.get("title") or "")
        if key and title:
            movie_titles[key].add((title, str(item.get("release_date") or "")[:4]))
            matched_title.add((key, title))
        rid = str(item.get("id") or "")
        if rid.startswith("tt"):
            found_ids.add(rid)
        if item.get("tmdb_id"):
            found_tmdb.add(str(item["tmdb_id"]))
    for episode in tv:
        key = comedian_key(episode.get("performer") or "")
        if key:
            tv_episodes[key].add(str(episode.get("id") or ""))
    for video in youtube:
        # Name must have been recorded by *name search*, not guessed from text.
        key = comedian_key(video.get("performer_search") or "")
        if key and video.get("video_id"):
            yt_videos[key].add(str(video["video_id"]))

    independent_works = defaultdict(list)
    for lead in state.get("works", []):
        key = comedian_key(lead.get("performer") or "")
        if key in tiers and lead.get("name"):
            if not work_in_catalog(lead, found_ids, found_tmdb, matched_title):
                independent_works[key].append({
                    "title": lead["name"],
                    "source": str(lead.get("source") or "wikidata"),
                    "source_id": str(lead.get("qid") or ""),
                    "imdb_id": str(lead.get("imdb") or ""),
                    "tmdb_id": str(lead.get("tmdb") or ""),
                    "status": "independent_metadata_lead_not_catalogued",
                })

    people = []
    for key, info in tiers.items():
        uncovered = independent_works.get(key, [])
        entry = {
            **info,
            "movie_special_records": len(movie_titles[key]),
            "tv_episode_review_leads": len(tv_episodes[key]),
            "youtube_review_candidates": len(yt_videos[key]),
            "independent_unmatched_works": uncovered,
            "needs_attention": bool(not movie_titles[key] or uncovered),
            "coverage_claim": "incomplete_evidence_only",
        }
        people.append(entry)
    people.sort(key=lambda r: (0 if r["priority"] == "established" else 1,
                               -int(r["needs_attention"]),
                               r["movie_special_records"], r["name"].casefold()))
    summary = {
        "established_comedians": sum(p["priority"] == "established" for p in people),
        "selected_underrated_comedians": sum(p["priority"] == "select_underrated" for p in people),
        "priority_comedians_total": len(people),
        "priority_comedians_without_movie_records": sum(not p["movie_special_records"] for p in people),
        "priority_comedians_with_unmatched_works": sum(bool(p["independent_unmatched_works"]) for p in people),
        "unmatched_work_leads": sum(len(p["independent_unmatched_works"]) for p in people),
        "catalog_movie_records": len(movies),
        "tv_review_leads": len(tv),
        "youtube_review_candidates": len(youtube),
    }
    return {
        "description": "Evidence-only coverage audit. Zero records does not prove a comedian has no special. Nonzero records do not prove their filmography is complete or that playback works.",
        "summary": summary,
        "comedians": people,
    }


def main() -> None:
    config = read_json(ROOT / 'config.json', {})
    report = coverage_report(config,
                             read_json(ROOT / 'data/specials.json', []),
                             read_json(ROOT / 'data/tv_episode_candidates.json', []),
                             read_json(ROOT / 'data/youtube_candidates.json', []),
                             read_json(ROOT / 'data/discovery_state.json', {}))
    output = ROOT / 'docs/coverage_report.json'
    write_json(output, report)
    print('Coverage audit: ' + ', '.join(f'{key}={value}' for key,value in report['summary'].items()), flush=True)
    print(f'Detailed report: {output}', flush=True)


if __name__ == '__main__':
    main()
