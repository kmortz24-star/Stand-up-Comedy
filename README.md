# Stand-Up Comedy — Nuvio catalog

A GitHub Pages-hosted, Stremio-compatible **metadata catalog** for Nuvio. It does **not** provide streams, replace Meteor/Comet, or change the Nuvio collection order.

## Current rows (14)

1. New Specials
2. Top Rated — up to 150 TMDB-rated specials
3. Fan Favorites — up to 150 audience favorites; overlap with Top Rated is allowed
4. Comedy Roulette — 60 weekly picks, targeting 15 different comedians per tier (well known / B-tier / classic / discovery)
5. Hidden Gems — 30 weekly picks
6. Comedy Legends
7. Viral & Rising Comedians
8. Roasts & Comedy Events
9–14. Six alphabetical rows, with names sorted by **first / stage name** and specials from **oldest to newest**

The six alphabet IDs stay stable when we rebalance letter groups. They are currently AB / CDEFG / HIJ / KLM / NOPQR / STUVWXYZ, based on actual catalog counts. **No Nuvio JSON import is needed** for updates to these GitHub-hosted catalogs.

## How automatic discovery works (new)

`fetch_tmdb.py` discovers leads from several independent paths:

- Multiple TMDB stand-up-specific **keywords** rather than a single tag.
- TMDB **title search** for stand-up, specials, and roasts, with cautious title/description matching.
- A rotating **Wikidata stand-up comedian roster**, obtained by *occupation*, not by a fixed list of names. Up to 120 comedians are searched by name per daily run, and each is retried after 45 days. The rotating roster also includes existing/curated performers as a fallback.
- **Wikidata stand-up genre titles**, matched to TMDB using their published TMDB movie IDs or IMDb identifiers via TMDB's `/find/{id}` endpoint. This is cross-referencing, not unauthorized IMDb site scraping.

Wikidata sources are cached in `data/discovery_state.json`. The script refreshes the roster/works at most weekly and keeps the previous cached results when Wikidata is unavailable. Existing `data/specials.json` titles are never discarded just because a third-party service is down.

This will not find *every* special in every catalog, and some sources may lack person credits. Each daily run expands or refreshes the searchable data over time. New matches need the configured TMDB token for the GitHub Actions run; the ZIP alone cannot perform a live refresh without that secret.

## Clean-up safeguards

`build_catalogs.py`:

- Removes exact same-performer/title/year duplicates, preferring IMDb-compatible IDs and stronger ratings metadata.
- Keeps unrated titles and older classics with very small vote samples. Entries with reliable, very poor ratings are excluded from the published alphabeticals.
- Repairs explicit performer labels such as `Comedy Central Presents: Dave Attell`, and names that appear before a clear title separator; known names come from cached specials, configured comedians and the Wikidata roster.
- Keeps the presenting host separate from the featured comedian when the title explicitly names both (such as Gabriel Iglesias presenting Rick Gutierrez).
- Places roasts/group events in their dedicated row, not automatically into a comedian's solo alphabetical list.
- Preserves the 60-item weekly Roulette layout, 150 Top Rated and 150 Fan Favorites rows and stable alphabet/catalog IDs.

The underlying TMDB data remains available in `data/specials.json` for reconsideration; low ratings do not permanently delete it.

## Comedy Central Presents and HBO showcases: episode discovery (new)

`fetch_tv_sets.py` searches TMDB's **TV series and episode index**, independently of the movie-special search. It checks **Comedy Central Presents**, **HBO Comedy Half-Hour** and **One Night Stand**, and records each episode's show, season, episode number, featured comedian (when identifiable), and TMDB episode ID.

TV candidates are saved to **`data/tv_episode_candidates.json`** on the scheduled workflow. They are **not currently placed into the alphabetical movie catalogs**. TV episodes have different metadata and playback identifiers, and mixing them into `movie` entries before Nuvio/stream compatibility is tested could produce an unplayable catalog. Once we verify a working episode route, we can merge these performers into navigable Nuvio listings. No additional API key is needed; TV lookups reuse TMDB's existing secret.

Our existing independent TMDB movie records such as `Comedy Central Presents: Dave Attell` remain in the collection and can be assigned to their featured comedians.

## YouTube: candidate discovery, not playback (new)

`fetch_youtube.py` optionally uses `YOUTUBE_API_KEY` in GitHub Actions to find promising public **full specials and sets at least 10 minutes long**. It searches broad comedy-related phrases plus a rotating set of comedian names, uses `videos.list` to check the actual length, and removes obvious trailers, podcasts, reactions and interviews. A publisher/channel clue is recorded but cannot prove an upload is official.

Candidates go into **`data/youtube_candidates.json` only**. YouTube IDs are **not yet added to the installed Nuvio catalogs**: their playback needs to be tested with an appropriate stream provider first. This avoids a folder full of unplayable entries. If the API key is absent, the YouTube stage simply skips, and TMDB catalogs continue to publish. Do **not** store the key in this repository or in any JSON; add it to GitHub's **Settings → Secrets and variables → Actions** with the name `YOUTUBE_API_KEY`.

## GitHub Actions and publishing

`.github/workflows/refresh.yml` runs each day and can also be triggered manually. It commits the discovery state and YouTube review candidates so each daily run can advance to *new* comedians rather than restarting at the same names:

1. Offline tests (no key required).
2. Multi-source TMDB / Wikidata discovery (requires existing `TMDB_READ_ACCESS_TOKEN` Actions secret).
3. TV comedy-show episode discovery for review (same TMDB secret).
4. Optional YouTube candidate collection (`YOUTUBE_API_KEY` Actions secret).
5. Generate and publish the static catalog in `docs/` to GitHub Pages.
6. Save the rotating discovery history to the repository, with workflow concurrency controls to minimize push conflicts.

The already installed addon address stays the same: `https://kmortz24-star.github.io/Stand-up-Comedy/manifest.json`.

If creating the repo from scratch: make a public GitHub repository, preserve the `.github/workflows` directory, configure both Actions secrets (TMDB required, YouTube optional), and select **GitHub Actions** as the Pages publishing source.

## Files

- `config.json`: category settings, exclusion/tag/performer overrides, alphabetical boundaries, Roulette tiers, rating floors.
- `fetch_tmdb.py`: TMDB metadata fetcher and rolling search scheduler.
- `discovery_sources.py`: independently retrieved Wikidata people/works.
- `fetch_youtube.py`: optional YouTube **candidate-only** retrieval.
- `fetch_tv_sets.py`: Comedy Central Presents / HBO stand-up TV episode metadata discovery (review only).
- `data/specials.json`: existing indexed TMDB/IMDb records (updated by Action).
- `data/manual_additions.json`: hand corrections and extra entries. **Never place API keys here.**
- `data/discovery_state.json`: generated, scheduled discovery cache; created at first run.
- `data/youtube_candidates.json`: generated YouTube review leads; not in Nuvio catalogs.
- `data/tv_episode_candidates.json`: generated TV episode review leads; not in Nuvio catalogs.
- `docs/build_report.json`: catalog sizes and unidentified performers for review.
- `docs/`: generated manifest and paginated catalogs.

Python 3.10+ with no third-party packages:

```sh
python3 -m unittest discover -s tests -v
TMDB_READ_ACCESS_TOKEN=YOUR_TOKEN python3 fetch_tmdb.py
python3 fetch_tv_sets.py  # same TMDB token
YOUTUBE_API_KEY=YOUR_KEY python3 fetch_youtube.py  # optional
python3 build_catalogs.py
```

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Movie metadata and poster art: [TMDB](https://www.themoviedb.org). Other discovery leads: [Wikidata](https://www.wikidata.org) (CC0). Video metadata: [YouTube Data API](https://developers.google.com/youtube/v3). A stream provider is a separate component from the metadata catalog. Verify applicable API terms before broader distribution.
