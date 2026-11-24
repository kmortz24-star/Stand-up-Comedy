# Stand-Up Comedy — Nuvio catalog

A GitHub Pages-hosted, Stremio-compatible catalog for Nuvio. TMDB movie specials still use your installed playback providers (Meteor/Comet); selected YouTube preview cards offer their own experimental in-app playback and an external YouTube link. The three TV showcases appear as **series with episodes** (metadata-only: playback depends on other addons). This does **not** change the Nuvio collection order.

## Current rows (14 original movie rows plus one TV series row)

1. New Specials
2. Top Rated — up to 150 TMDB-rated specials
3. Fan Favorites — up to 200 audience favorites; overlap with Top Rated is allowed
4. Comedy Roulette — 60 weekly picks, targeting 15 different comedians per tier (well known / B-tier / classic / discovery)
5. Hidden Gems — 30 weekly picks
6. Comedy Legends
7. Viral & Rising Comedians
8. Roasts & Comedy Events
9–14. Six alphabetical rows, with names sorted by **first / stage name** and specials from **oldest to newest**
15. **Stand-Up TV Series** — Comedy Central Presents, HBO Comedy Half Hour and One Night Stand; browse the seasons and individual comedian episodes within each show

The six alphabet IDs stay stable when we rebalance letter groups. They are currently AB / CDEFG / HIJ / KLM / NOPQR / STUVWXYZ, based on actual catalog counts. **No Nuvio JSON import is needed** for updates to these GitHub-hosted catalogs.

## How automatic discovery works (new)

`fetch_tmdb.py` discovers leads from several independent paths:

- Multiple TMDB stand-up-specific **keywords** rather than a single tag.
- TMDB **title search** for stand-up, specials, and roasts, with cautious title/description matching.
- A rotating **Wikidata stand-up comedian roster**, obtained by *occupation*, not by a fixed list of names. Up to 200 comedians are searched by name per daily run, and each is retried after 45 days. The rotating roster also includes existing/curated performers as a fallback.
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
- Preserves the 60-item weekly Roulette layout, 150 Top Rated and 200 Fan Favorites rows and stable alphabet/catalog IDs.

The underlying TMDB data remains available in `data/specials.json` for reconsideration; low ratings do not permanently delete it.

### Manually verified YouTube exception

Mitch Fatel's *Bad Girls* is included as a **YouTube-backed candidate** in the
alphabeticals because the artist's own website embeds that exact public upload.
This is the one requested manual exception. It is not treated as a TMDB film,
and YouTube playback in Nuvio remains unverified (external link available).
The verification flag requires artist-site evidence and a matching comedian name.

## Comedy Central Presents and HBO showcases: TV series catalog (v8)

`fetch_tv_sets.py` searches TMDB's **TV series and episode index** for **Comedy Central Presents**, **HBO Comedy Half Hour**, and **One Night Stand**, storing each episode's season, number, title and featured comedian (when identifiable) in `data/tv_episode_candidates.json`.

`tv_catalogs.py` publishes a new **Stand-Up TV Series** *series-type* row with these three shows. Opening a show presents all discovered seasons and episodes under **real TMDB show IDs**, for example `tmdb:4787:11:19` for the Mitch Fatel episode of Comedy Central Presents. It publishes `/meta/series/tmdb:4787.json` and similar metadata endpoints and adds a `series` catalog to the manifest. It does not create fake standalone movies or host any video streams. **Playback is unverified** and depends on separately installed providers (Meteor/Comet/YouStream as appropriate) resolving each TMDB episode; some older episodes may have no playable sources. A GitHub workflow refresh is required to publish the new row.

No additional API key is needed. Future TMDB refreshes will also store show poster/backdrop paths for better Nuvio artwork. Existing independent TMDB movie records remain in their alphabetical categories. Toggle `enable_tv_series_catalog` off in `config.json` to hide the TV row.

## YouTube discovery and optional catalog integration (v7)

`fetch_youtube.py` optionally uses `YOUTUBE_API_KEY` in GitHub Actions to find promising public **full specials and sets at least 10 minutes long**. It searches broad comedy-related phrases plus a rotating set of comedian names, uses `videos.list` to check the actual length, and removes obvious trailers, podcasts, reactions and interviews. A publisher/channel clue is recorded but cannot prove an upload is official.

Candidates accumulate in **`data/youtube_candidates.json`**. With both `enable_youtube_preview_catalogs` and `merge_youtube_into_existing_catalogs` enabled, selected YouTube cards join the corresponding Viral & Rising, Hidden Gems and alphabetical movie rows. They are **unverified previews**, clearly marked `[YouTube]`, with a fallback link to the actual YouTube upload; playback may be in-app, external or unavailable depending on the Nuvio device and YouTube upload. The older separate YouTube preview rows can be restored by disabling `merge_youtube_into_existing_catalogs`. Turn previews off entirely by setting `enable_youtube_preview_catalogs` to false.

If the API key is absent, new YouTube discovery skips and TMDB catalogs continue. **Never put API keys in the repository**; add `YOUTUBE_API_KEY` in GitHub **Settings → Secrets and variables → Actions**.

## GitHub Actions and publishing

`.github/workflows/refresh.yml` runs each day and can also be triggered manually. It commits the discovery state and YouTube review candidates so each daily run can advance to *new* comedians rather than restarting at the same names:

1. Offline tests (no key required).
2. Multi-source TMDB / Wikidata discovery (requires existing `TMDB_READ_ACCESS_TOKEN` Actions secret).
3. TV comedy-show episode discovery and native series/episode catalog metadata (same TMDB secret).
4. Optional YouTube candidate collection (`YOUTUBE_API_KEY` Actions secret).
5. Generate and publish the static catalog in `docs/` to GitHub Pages.
6. Save the rotating discovery history to the repository, with workflow concurrency controls to minimize push conflicts.

The already installed addon address stays the same: `https://kmortz24-star.github.io/Stand-up-Comedy/manifest.json`.

If creating the repo from scratch: make a public GitHub repository, preserve the `.github/workflows` directory, configure both Actions secrets (TMDB required, YouTube optional), and select **GitHub Actions** as the Pages publishing source.

## Files

- `config.json`: category settings, exclusion/tag/performer overrides, alphabetical boundaries, Roulette tiers, rating floors.
- `fetch_tmdb.py`: TMDB metadata fetcher and rolling search scheduler.
- `discovery_sources.py`: independently retrieved Wikidata people/works.
- `fetch_youtube.py`: optional YouTube candidate retrieval and daily API-budget handling.
- `youtube_catalogs.py`: conservative YouTube classification and optional movie-type preview cards with static playback links.
- `fetch_tv_sets.py`: Comedy Central Presents / HBO stand-up TV episode metadata discovery.
- `tv_catalogs.py`: publish the three shows as proper `series` with episode lists using TMDB IDs; no hosted playback.
- `data/specials.json`: existing indexed TMDB/IMDb records (updated by Action).
- `data/manual_additions.json`: hand corrections and extra entries. **Never place API keys here.**
- `data/discovery_state.json`: generated, scheduled discovery cache; created at first run.
- `data/youtube_candidates.json`: generated YouTube review leads; eligible candidates can appear in the original comedy categories as labeled previews.
- `data/tv_episode_candidates.json`: generated TV episode metadata; grouped into the Nuvio Stand-Up TV Series row by the build step.
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
- YouTube searches up to six rotating queries **per day across manual and scheduled runs**,
  checking full specials and 10+ minute sets by name/title. It also scans
  reputable comedy channel uploads (at most once daily) using inexpensive APIs. It
  preserves public videos as *review candidates*, including embed eligibility;
  v7 optionally publishes explicitly labeled candidate cards in existing Nuvio **movie** catalogs with a direct link to YouTube; this is a preview, not a verified playable special.
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
specific special titles. To avoid exhausting the default quota, the workflow now makes at most **six
`search.list` calls per calendar day in total**, including manual reruns, rather
than dozens per run. It checks results and saves them incrementally, so later
quota or connection errors do not erase earlier discoveries. It also scans
trusted channel upload playlists once daily. Ten-plus-minute stand-up sets
receive a *Hidden Gems* suggestion; long-form shows receive a comedian-row
suggestion. These are **review labels only** until deliberately published as preview cards;
actual YouTube availability and playback remain unverified.

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

The Roulette groups and existing Nuvio catalog names do not change. Each refresh
generates `docs/coverage_report.json` via `build_catalogs.py` with each
priority comedian's number of standalone movie records, separately discovered
TV and YouTube review leads, and unmatched independent metadata titles.
A **zero** means the catalog is missing a matching movie record; it doesn't
prove the comedian has no specials. A **nonzero** does not guarantee a complete
filmography or working playback. The coverage audit never manually inserts titles. Optional YouTube cards are
unverified previews, not a guarantee of availability or playback; TV episodes
are now published as series metadata, not standalone movies, with playback still unverified. No video files are hosted or distributed.

### v7: YouTube sets in the existing comedy categories

When `merge_youtube_into_existing_catalogs` is true, the addon no longer adds
separate **Viral & Rising — YouTube**, **Hidden Gems — YouTube** or **Full Specials
— YouTube** rows. Instead it shows:

- 10+ minute rising-comedian sets in **Viral & Rising Comedians**, with the
  existing TMDB specials.
- Other short stand-up sets in **Hidden Gems**.
- Long-form YouTube specials in the appropriate **alphabetical Comedians** row,
  grouped by the performer's first name. Movie specials retain their original
  chronological order; YouTube uploads follow that performer's movies because
  upload year may differ from the performance's release year.

Each new item has `[YouTube]` in the title and is a `movie`-type card backed
by this addon's static `meta/movie/standupyt_*.json` and
`stream/movie/standupyt_*.json` files. The stream offers an **experimental
in-app YouTube** choice and a **browser/YouTube-app link**; support varies by
Nuvio version. These are unverified review candidates and are not part of the
curated Top 150, Fan Favorites or Roulette rankings. YouStream is no longer
needed to resolve these merged entries (though users may keep it installed).
The original `youtube`-type preview rows are removed from the manifest.

To revert, set `merge_youtube_into_existing_catalogs` to false and rebuild;
the older separate YouTube preview rows remain available as a fallback.


### Stand-Up TV Shows (after alphabeticals)

The existing TV category now searches a wider roster of real stand-up showcase
series and comedy competitions. It preserves the shows as **TV series**, including
seasons and episodes, rather than inserting episode cards into the movie
alphabeticals. Examples: Comedy Central Presents, HBO Comedy Half-Hour, One
Night Stand, Def Comedy Jam, Premium Blend, Live at Gotham, Gotham Comedy Live,
Live at the Apollo, ComicView, Comedy Now!, Just for Laughs: All Access,
Comedy Central Stand-Up Presents, Netflix stand-up anthologies, and Last Comic
Standing. The refresh automatically **skips** shows that cannot be confidently
matched to a TMDB series, and retains previously indexed episodes if a source
lookup temporarily fails. Browse/show metadata does not ensure playable streams
from installed source addons. No changes to Nuvio's external JSON are needed.

### English-language-only catalog policy

`english_language_only` applies across standalone movie catalogs (including
Top Rated, Fan Favorites, Roulette, alphabeticals, Roasts & Events), YouTube
preview candidates, and TV episode metadata. Known non-English records are
omitted from published catalogs, **not deleted** from `data/`.

- TMDB `original_language` is used as a practical indicator, **not a verified
  transcript of spoken audio**. Legacy source records with no language tag are
  kept pending verification; an explicit non-English code is excluded. If
  other works by the same comedian are tagged non-English and no works are
  tagged English, the missing-language items are conservatively held out.
- Each TMDB refresh backfills missing language fields for up to
  `language_backfill_per_run` older films, starting with the most-voted titles.
  This reduces unknown-language items over successive daily runs.
- YouTube videos with a non-English audio-language tag are excluded. Many
  uploads provide **no** audio-language metadata, so those remain unverified
  previews; playback is not guaranteed.
- TV episodes with a known non-English language are excluded. The multilingual
  *COMEDIANS of the world* anthology is held out in full until individual
  English-language episodes can be verified; other existing English-language
  series remain intact.

The generated `docs/build_report.json` contains an `english_language_policy`
section that reports how many source movies still lack language metadata.
Filtering by spoken audio with zero unknowns would require an additional
verified source, and should not be claimed from TMDB alone.

### Ranking refinements (v13)

- **Top Rated:** 150 entries; Bayesian-weighted TMDB average with a 25-vote prior,
  still requiring at least 20 TMDB votes.
- **Fan Favorites:** 200 entries in the *existing* category and ID (no Nuvio
  JSON import). Audience approval and sample size plus a small editorial
  established-comedian bonus; not a follower-count metric.
- Clearly non-stand-up items and outtake releases are filtered before the
  rankings and movie catalogs are generated. Retrospectives like
  *George Carlin: 40 Years of Comedy* stay in alphabeticals but not rankings.
- Exclusions are rules in `config.json`, not deletions from `data/specials.json`.
