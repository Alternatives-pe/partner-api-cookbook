# Partner API Cookbook

Sample code for the **Alternatives Partner API (v3)** — a read-only REST API for private-market data across Southeast Asia (companies, investors, funds, people, and service providers).

Each script in [`examples/`](examples/) is a self-contained recipe. The catalog, with the API calls and a runnable command for each, is in [`COOKBOOK.md`](COOKBOOK.md).

Full documentation: https://docs.altdmp.io/

> **Note:** Access is subscription-gated. You need an API key and the relevant entitlements. Request one from support@alternatives.pe.

## Quick start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your credentials
cp .env.example .env
# edit .env and set ALT_API_KEY to your real key

# 4. Run the smoke test
python api_client.py

# 5. Run any recipe (from the repo root)
python examples/enrich_company.py shopback

# ...or smoke-test every recipe at once
python run_all.py
```

## What's here

| File | Purpose |
| --- | --- |
| `api_client.py` | Shared library — `AltClient` (token caching, paging, rate-limit handling) plus CLI and CSV/JSON output helpers used by every example. Run it directly for a smoke test. |
| `COOKBOOK.md` | The recipe catalog: what each script does, the API calls, and an example command. |
| `examples/` | One runnable script per recipe. |
| `run_all.py` | Smoke-test runner — executes every recipe with a light invocation and reports pass/fail. |
| `.env.example` | Template for your credentials. Copy to `.env` (which is gitignored). |
| `requirements.txt` | Python dependencies. |

### Recipes

| Script | Recipe |
| --- | --- |
| `examples/enrich_company.py` | Company enrichment / CRM auto-fill |
| `examples/sourcing_raising_now.py` | Live deal-flow sourcing |
| `examples/investor_portfolio.py` | Competitor / co-investor portfolio pull |
| `examples/person_background.py` | Founder / director background check |
| `examples/deal_flow.py` | Market-wide deal flow (date window) |
| `examples/market_map.py` | Thematic market map |
| `examples/captable.py` | Cap table & ownership analysis |
| `examples/fund_benchmark.py` | Fund benchmarking (IRR/TVPI/DPI/RVPI) |
| `examples/syndicate_map.py` | Co-investor / syndicate network mapping |
| `examples/pe_screener.py` | PE buyout / target screening engine |
| `examples/watchlist_monitor.py` | Portfolio / watchlist monitoring |
| `examples/lp_intelligence.py` | LP / fundraising intelligence |
| `examples/service_providers.py` | Auditor / service-provider signal |
| `examples/incremental_sync.py` | Incremental sync on `aggregate_updated_at` (keyset paging) |
| `examples/reference_data.py` | Helper: list valid filter keys (themes, deal types, …) |

## Common switches

Every script accepts the same options (see `--help` on any of them):

- `-n, --limit` — max rows to fetch / return.
- `-s, --sort` — ordering field; prefix `-` for descending. Pass with `=`, e.g. `--sort=-latest_valuation_usd` (argparse otherwise treats the leading `-` as a flag). Recipes that hit a list or sub-resource endpoint sort **server-side** (a true global top-N); a few that rank on computed metrics or read fixed-order routes (cap tables) sort client-side over the fetched rows.
- `-f, --format` — `csv` (default) or `json`.
- `-o, --output` — write to a file instead of stdout (progress goes to stderr).

```bash
python examples/market_map.py --themes themes_payments --country SGP -n 100 --sort=-latest_valuation_usd -o out/map.csv
python examples/fund_benchmark.py --vintage-from 2018 --format json -o out/funds.json
```

## Conventions used in every example

- **Read the API key from the environment** (`ALT_API_KEY`), never hard-code it.
- **Cache the bearer token** — it's valid for 24h; don't re-issue it on every call.
- **Use `POST` body filters** for anything beyond a simple search, wrapped in a boolean group: `{"filters": {"all": [...]}}` (or `any` / `not`).
- **Pass `limit`/`offset`/`ordering` as query params** — the POST body accepts **only** `filters`; any other top-level key returns HTTP 400.
- **Store UUIDs** — there are no integer IDs.
- **Honor the rate-limit cooldown.** A `429` carries `Retry-After` (seconds until the rolling window frees capacity, repeated in the body as `retry_after_seconds`) plus `scope` and `dimension` naming which limit you hit. `AltClient` waits exactly that long and retries — up to `ALT_MAX_RETRY_WAIT` seconds (default 120), after which it raises `RateLimitExceeded`. Retrying sooner than asked just burns another slot in the window.
- **Handle the other errors:** `403` = subscription/entitlement gap, `401` = bad or expired token.
- **Money fields are USD-normalized** (`_usd` suffix) — no client-side FX needed.

## Security

This repo is intended to be safe to publish. Please keep it that way:

- **Never commit real keys, tokens, or `.env` files.** Use placeholders and environment variables. `.gitignore` already excludes `.env`, `*.token`, and common secret files.
- **Never commit real API responses.** Cap tables, financials, valuations, and LP/commitment data are subscription-gated customer data. Script output is gitignored: write it under `out/` (the `-o` examples do), and `out/`, `*.csv`, `data/`, `cache/`, and `responses/` (where `watchlist_monitor.py` writes state) are all excluded.
- Run a secret scan (e.g. `gitleaks`) before making the repo public.

## License

See [`LICENSE`](LICENSE).
