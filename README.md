# pocketry-prices

The price feed [Pocketry](https://github.com/Ink-Iron-Apps/pocketry) reads.

The app never calls a price API from the device. It fetches one static file
from here, which is what keeps marginal cost per user at zero, keeps API keys
out of the binary, and lets the price source change without an app release.

## What is published

Served from GitHub Pages at `https://ink-iron-apps.github.io/pocketry-prices/`:

| File | What it is |
|---|---|
| `manifest.json` | Latest date, per-source timestamps, row count, and the SHA-256 of the CSV |
| `prices.csv` | `productId,finishIndex,market,low,high` — around 45,000 rows |

The app reads the manifest first and downloads the CSV only when
`sources.tcgplayer_usd` is newer than what it already has. It verifies the
published checksum and refuses a file under 30,000 rows: a truncated feed
silently zeroes collections, where a stale one is at least visible.

## How it is built

`.github/workflows/publish.yml` runs `tools/pull_prices.py` daily against
[tcgcsv.com](https://tcgcsv.com), then deploys the result to Pages. The
workflow uses this repository's own `GITHUB_TOKEN`; there is no secret to
configure.

The CSV is **not** committed. It is deployed as a Pages artifact, so a daily
1.1 MB file does not accumulate in git history forever. The gzipped archive
under `archive/` **is** committed, because value-over-time charts are built
from it and a gap in it is permanent.

`pull_prices.py` refuses to publish a short or mostly-unpriced pull. Let it:
stale is visible to the user, wrong is silent.
