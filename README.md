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

### Discovery (v2)

Discovery is no longer limited to TMDB stand-up keywords. The scheduled job
rotates through a Wikidata comedian roster, searches each person's TMDB film
credits, checks Wikidata works via their IMDb IDs (`/find/{imdb_id}`), and
searches an independent rotating queue of *exact special titles*. Title leads
are in `Wikidata-discovered title leads`, including historically verified items
that keyword search has missed. The YouTube step searches those same titles and
keeps results in `data/youtube_candidates.json` for review.

**Important:** IMDb-only titles remain *discovery targets*, not catalog records,
until a TMDB match is confirmed. YouStream is an independent playback addon,
not an API for looking up an IMDb title or guaranteeing in-app playback. A
GitHub Actions green check confirms metadata discovery, **not** playability.
IMDb official bulk datasets are not downloaded by this pipeline: they're very
large and have separate non-commercial-use restrictions. Those can be
considered for a future weekly index after verifying permitted use.

### Discovery audit principle

Missing titles (e.g. fan-reported gaps) are **checks**, not forced imports. The fetcher builds its candidate list from metadata discovery and comedian filmographies; it does not insert example IMDb or YouTube IDs just to make test titles appear. After each live GitHub refresh, compare the generated output against those known missing titles. Offline unit tests cannot prove that an external API supplies a particular missing special.

### Discovery coverage update (automatic; no hand-seeded specials)

- Wikidata now supplies independently indexed *stand-up works even if neither a
  TMDB ID nor an IMDb ID is attached*. This metadata is used as a lead, not as
  automatic evidence that a random movie or YouTube video is playable.
- Existing Wikidata IMDb identifiers are resolved using TMDB's `/find/{id}` API.
  Titles with no IDs are searched exactly and require stand-up evidence.
- Performer filmographies and movie title searches remain complementary inputs.
- YouTube rotates through up to 48 comedians and 20 independent titles a day,
  searches up to 50 results per query, and scans uploads from
  reputable comedy channels it discovers, using channel/playlist APIs. It
  preserves public videos as *review candidates*, including embed eligibility;
  it does not publish speculative YouTube streams into Nuvio's movie catalog.
- Discovery rotates and stores cursors in `data/discovery_state.json`. GitHub
  Actions persists this file, so an ordinary run continues where the prior one
  stopped.

**Not an IMDb scraper:** IMDb's bulk data is licensed for limited personal and
noncommercial use and cannot simply be republished as a public movie database.
Our public addon gets IMDb IDs from independently sourced Wikidata records and
TMDB public metadata, not scraped IMDb pages or bulk-dataset republishing.

**Proof standard:** An offline test only verifies program behavior. To confirm
that a previously missing real special is actually found, inspect the live
results after GitHub Actions runs. No example titles or IDs are forcibly
inserted to produce a pass.



### Cross-source discovery improvements

Independent comedian/stand-up leads come from Wikidata (CC0) and from TMDB
filmographies and movie titles. This includes Wikidata works without external
IDs and works credited to stand-up comedians, even when they lack a stand-up
genre tag. Independently found IMDb title IDs are matched through TMDB's
`/find/{imdb_id}` endpoint; **there is no bulk IMDb dataset republishing**.
Any record without a matching Nuvio movie identity stays out of published movie
catalogs. There are no manually seeded exceptions for particular specials.

YouTube discovery rotates through the automatically discovered roster and
specific special titles. To avoid exhausting the default quota, each refresh
uses at most 32 `search.list` calls (previously 84), plus inexpensive metadata
and upload-playlist requests. It refreshes new channel uploads and rotates into
older videos. YouTube candidates remain separate from Nuvio movie catalogs
until playback and matching are verified.

The diagnostics in `data/discovery_state.json` report number of names searched,
independent titles searched, and source-specific exact-title matches.

### Priority comedian coverage audit

The additional `coverage_priority` entries in `config.json` are **comedian
names only**, not manually seeded specials or ID exceptions. Search priority is:

1. Existing well-known, B-tier, and classic/legends groups plus recognizable
   established performers missing from those groups.
2. A deliberately small `select_underrated` list of recognized club/online
   stand-ups worth extra attention.
3. Other performers with evidence of a TV stand-up appearance and few records,
   then the rest of the Wikidata/metadata roster over time.

The Roulette groups and Nuvio catalog categories do not change. Each refresh
runs `audit_coverage.py`, publishing `docs/coverage_report.json` with each
priority comedian's number of standalone movie records, separately discovered
TV and YouTube review leads, and unmatched independent metadata titles.
A **zero** means the catalog is missing a matching movie record; it doesn't
prove the comedian has no specials. A **nonzero** does not guarantee a complete
filmography or working playback. The audit never inserts titles, and it never
publishes unverified YouTube or TV sources to the movie catalogs.
