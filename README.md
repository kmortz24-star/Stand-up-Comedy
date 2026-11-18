# Stand-Up Comedy — Nuvio / BingeCat catalog prototype

An automatically refreshed catalog of stand-up comedy specials, with the section layout Kevin chose. This is a **catalog only**, not a streaming source: it does **not** replace Comet, Meteor, TorBox, or anyone's playback settings.

## The sections

1. **Comedy Roulette** — 35 weekly rotating picks; at most one per comedian
2. **New Specials** — last 18 months, newest first
3. **Hidden Gems** — 30 weekly rotating lower-popularity, well-rated specials
4. **Comedy Legends** — initially Carlin, Pryor, Dice, Murphy, Kinison, and the earlier stand-up generation
5. **Viral & Rising Comedians** — weekly rotating picks from a curated roster of Kill Tony standouts and comics who broke through online
6. **Comedians ABCD**
7. **EFGH**
8. **IJKL**
9. **MNOP**
10. **QRST**
11. **UVWXYZ**
12. **Roasts & Comedy Events**

The alphabet uses a comic's **first/stage name**. Inside each alphabet section, each comedian's specials appear **oldest to newest**. Legends is a manually chosen generation of comics, but each selected comic's new specials appear there automatically when indexed. The Original Kings of Comedy and Blue Collar Comedy Tour are not in Legends by default; their group specials can appear under Comedy Events. After the first real data import, inspect `docs/build_report.json` to rebalance `alphabet_groups` in `config.json` if one section is much larger than another. IDs are stable, so changing the letter boundaries won't break the catalogs.

## What updates by itself?

The GitHub Actions task checks TMDB daily for newly indexed stand-up titles, updates existing records periodically, chooses weekly Roulette/Hidden Gems, builds 12 catalog endpoints, and publishes them to GitHub Pages.

It isn't a magic complete census: some YouTube specials aren't on TMDB; others have missing performer credits or are not tagged stand-up. Such titles may need manual corrections in `config.json` or entries in `data/manual_additions.json` (using real IDs). The review list is in `docs/build_report.json`. The Viral & Rising Comedians roster refreshes its choices weekly from available TMDB records; it does **not yet** search social media or enforce a YouTube video's 10+ minute length.

YouTube-only playback through **YouStream** and the 10+ minute official-set discovery/filtering are a **separate next phase**; nothing in this package installs YouTube or its API key.

## First-time setup

1. Make a [TMDB account](https://www.themoviedb.org/signup) and request its free, noncommercial API access under **Account Settings → API**. Obtain the **API Read Access Token**. **Do not post the token publicly or in chat.**
2. Create a new **public** GitHub repository, e.g. `Standup-Comedy`. Upload the **contents of this folder to the repository root**, preserving `.github/workflows/refresh.yml`. (You can use GitHub Desktop or Git locally to preserve the hidden `.github` folder.)
3. In that repository open **Settings → Secrets and variables → Actions → New repository secret**. Name it `TMDB_READ_ACCESS_TOKEN` and paste your token as the value.
4. Open **Settings → Pages** and under **Build and deployment → Source** choose **GitHub Actions**.
5. Open **Actions → Refresh Stand-Up Comedy Catalogs → Run workflow**. The first run downloads TMDB entries, generates the catalogs, and publishes the site. The initial discovery may take several minutes.
6. After the workflow finishes, visit `https://kmortz24-star.github.io/Standup-Comedy/manifest.json` (adjust if you used a different repo name). Use that **manifest URL** to install the catalog as a Stremio-compatible addon in Nuvio/BingeCat, where supported. Check that Nuvio displays all 12 rows.

If an account already has the addon installed, a later refresh updates its lists at the same address. Playback still comes from the account's own installed stream providers.

**Important:** the entire published catalog is public. Keep passwords, API tokens and TorBox information *out* of data files. The secret belongs only in GitHub Actions settings.

## How to rebalance sections or add specials

- `config.json`: `alphabet_groups` labels and boundaries, curated Viral & Rising roster, hidden gem thresholds, omitted IDs, and performer/tag corrections.
- `data/manual_additions.json`: extra records, or corrected versions of TMDB records. Use an actual IMDb ID (for example `tt...`) when available for easier matching to metadata/playback. Records require `id`, `title`, `performer`, and `release_date` (`YYYY-MM-DD`).
- `data/specials.json`: automatically managed discovered records. Don't edit it directly; add corrections to `manual_additions.json`.
- `docs/build_report.json`: counts per row and specials with uncertain comedian names.

By default, the first alphabet section is called `Comedians {letters}`; the other alphabet headers are just their letter ranges. The six catalog IDs stay unchanged when the ranges change.

## Run or test locally

Python 3.10+ is enough; no third-party packages are needed.

```bash
python3 -m unittest discover -s tests -v
TMDB_READ_ACCESS_TOKEN=your_private_token python3 fetch_tmdb.py
python3 build_catalogs.py
```

The local token example is only an illustration. On GitHub, use the repository secret and let the workflow pass it in. `docs/manifest.json` and `docs/catalog/movie/...` are the generated Stremio-compatible output.

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

TMDB: <https://www.themoviedb.org>. Published catalog metadata and artwork are sourced from TMDB. This project uses their API for noncommercial purposes; check TMDB's terms and attribution requirements before wider distribution.

Built against the [Stremio addon protocol](https://github.com/Stremio/stremio-addon-sdk/blob/master/docs/protocol.md). Streaming sources are independent.
