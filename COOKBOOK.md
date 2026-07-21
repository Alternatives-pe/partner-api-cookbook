# Cookbook

Recipe-style use cases for the **Alternatives Partner API (v3)**, grouped from simple to complex. Each entry lists what it does, why it's useful, the API recipe, and a ready-to-run script in [`examples/`](examples/).

Base URL: `https://api.altdmp.io/v3/partners/`. All money fields are USD-normalized (`_usd`). Full reference: https://docs.altdmp.io/

Every script imports the shared client in [`api_client.py`](api_client.py), which handles auth, token caching, paging, and 429 back-off. They all accept the same switches:

| Switch | Meaning |
| --- | --- |
| `-n, --limit` | max rows to fetch / return |
| `-s, --sort` | ordering field; prefix `-` for descending. Use `=`, e.g. `--sort=-latest_valuation_usd` |
| `-f, --format` | `csv` (default) or `json` |
| `-o, --output` | write to a file instead of stdout |

> **Sorting.** Recipes backed by a list endpoint sort **server-side** by passing `ordering` as a query param, so `--sort` gives a true global top-N. A few recipes still sort client-side because they rank on values computed per row (IRR in fund benchmarking, shared-company counts in the syndicate map) or read from sub-resources (cap tables, commitments); there `--sort` orders only the fetched window, so raise `-n` to widen it.

Run everything from the repo root with the virtualenv active (see [README](README.md)).

---

## Simple recipes (single endpoint)

### 1. Company enrichment / CRM auto-fill
**What:** Look up a company by name or registration number; pull profile, funding, latest valuation, trading status, financials.
**Why:** Keep your deal CRM current without manual data entry.
**Script:** [`examples/enrich_company.py`](examples/enrich_company.py)

```python
client.get("capital-receivers/", params={"search": "shopback"})
# or by registration number:
client.get("capital-receivers/", params={"registration_number": "201411189G"})
# then the full detail (display_name lives under legal_entity):
client.get(f"capital-receivers/{uuid}/")   # funding, financials[], legal_entity
```

```bash
python examples/enrich_company.py shopback
python examples/enrich_company.py --reg 201411189G --format json
```

### 2. Live deal-flow sourcing
**What:** Find companies currently raising, filtered by theme and geography.
**Why:** Turn "who's in market right now" into a repeatable query.
**Script:** [`examples/sourcing_raising_now.py`](examples/sourcing_raising_now.py)

```python
client.post("capital-receivers/", {
    "filters": {"all": [
        {"op": "eq", "field": "is_raising_now", "value": True},
        {"op": "in", "field": "themes_keys", "value": ["themes_payments"]},
        {"op": "eq", "field": "headquarters_country_iso_alpha3", "value": "SGP"},
    ]},
}, params={"limit": 50, "ordering": "-latest_valuation_usd"})   # limit & ordering are query params; the body takes only `filters`
```

```bash
python examples/sourcing_raising_now.py --country SGP -n 25
python examples/sourcing_raising_now.py --themes themes_payments themes_digital_neo_banking
```

### 3. Competitor / co-investor portfolio pull
**What:** Pick any investor and pull their entire portfolio.
**Why:** See what rivals are backing and where they concentrate.
**Script:** [`examples/investor_portfolio.py`](examples/investor_portfolio.py)

```python
inv = client.get("capital-allocators/", params={"search": "Wavemaker"})["results"][0]
client.get(f"capital-allocators/{inv['uuid']}/investments/")
```

```bash
python examples/investor_portfolio.py Wavemaker -n 50
python examples/investor_portfolio.py "East Ventures" --sort=-total_invested_usd
```

### 4. Founder / director background check
**What:** Look up a person and see track record, roles, and prior-company associations.
**Why:** Lightweight diligence and reference-checking.
**Script:** [`examples/person_background.py`](examples/person_background.py)

```python
person = client.get("people/", params={"search": "Shanru"})["results"][0]
client.get(f"people/{person['uuid']}/roles/")        # filter by role client-side
client.get(f"people/{person['uuid']}/investments/")
```

```bash
python examples/person_background.py "Shanru Lai" --role founder
python examples/person_background.py "Henry Chan" --investments
```

> Search on the full name directly. Roles come back as a small per-person list, so `--role` filters them client-side — matching on either the role key or its display name.

---

## Medium recipes (multi-call, light analysis)

### 5. Thematic market map
**What:** Landscape of every company in a theme + geography + stage, with valuation and revenue, ranked.
**Why:** Underpins sector theses and competitive maps.
**Script:** [`examples/market_map.py`](examples/market_map.py)

```python
client.post("capital-receivers/", {
    "filters": {"all": [
        {"op": "in",  "field": "themes_keys", "value": ["themes_payments"]},
        {"op": "eq",  "field": "headquarters_country_iso_alpha3", "value": "SGP"},
        {"op": "gte", "field": "year_founded", "value": 2018},
    ]},
}, params={"limit": 1000})
```

```bash
python examples/market_map.py --themes themes_payments --country SGP -n 50
python examples/market_map.py --themes themes_ai_genai_ml --founded-after 2018
```

### 6. Cap table & ownership analysis for a target
**What:** For a company, pull who owns what, percentages, and (for managed cap tables) amounts invested.
**Why:** Core diligence input.
**Script:** [`examples/captable.py`](examples/captable.py)

```python
detail = client.get(f"capital-receivers/{uuid}/")
detail["captable_source"]["type"]              # "managed" or "snapshot" — check first
client.get(f"capital-receivers/{uuid}/captable/")
client.get(f"capital-receivers/{uuid}/investors/")   # managed only; snapshot -> HTTP 400
```

```bash
python examples/captable.py shopback
python examples/captable.py shopback --investors        # investor-centric aggregates
```

> **Check `captable_source.type` first.** `managed` = transaction-derived positions with amounts; `snapshot` = point-in-time percentages only, and `/investors/` returns HTTP 400. The script handles both and picks the right columns.

### 7. Fund benchmarking
**What:** Compare IRR/TVPI/DPI/RVPI across funds by vintage to benchmark a GP or screen funds.
**Why:** Directly relevant to PE — LP diligence and GP comparison.
**Script:** [`examples/fund_benchmark.py`](examples/fund_benchmark.py)

```python
funds = client.post("funds/", {
    "filters": {"all": [{"op": "gte", "field": "vintage_year", "value": 2016}]},
}, params={"limit": 20})
for f in funds["results"]:
    client.get(f"funds/{f['uuid']}/performance/")   # IRR/DPI/RVPI/TVPI per record
    client.get(f"funds/{f['uuid']}/aum/")           # fund size
```

```bash
python examples/fund_benchmark.py --vintage-from 2016 --vintage-to 2020 --sort=-irr
```

> Performance metrics are **not** on the fund list — fetch them per fund. `net_multiple` is TVPI.

### 8. Co-investor / syndicate network mapping
**What:** Aggregate cap tables across a sector to see who co-invests with whom.
**Why:** Surfaces syndicate partners and competitive overlap.
**Script:** [`examples/syndicate_map.py`](examples/syndicate_map.py)

```python
# For each sourced company, pull its investors, then build a co-occurrence
# graph of investor pairs client-side.
for uuid in company_uuids:
    client.get(f"capital-receivers/{uuid}/investors/")
```

```bash
python examples/syndicate_map.py --themes themes_payments --companies 60
python examples/syndicate_map.py --themes themes_fintech --country SGP --min-shared 2
```

---

## Complex recipes (the PE-move differentiators)

### 9. PE buyout / target screening engine
**What:** Screen for mature, profitable, growing businesses by combining financial filters with a per-company profitability check.
**Why:** The headline use case for a VC moving into PE — shifts sourcing from fast-growth startups to cash-flowing, consolidation-ready businesses.
**Script:** [`examples/pe_screener.py`](examples/pe_screener.py)

```python
hits = client.post("capital-receivers/", {
    "filters": {"all": [
        {"op": "gte", "field": "latest_operating_revenue_usd", "value": 10_000_000},
        {"op": "gte", "field": "operating_revenue_growth_yoy_pct", "value": 0},
        {"op": "eq",  "field": "trading_status_name", "value": "Operating"},
    ]},
}, params={"limit": 200})
# Earnings are not directly filterable — confirm EBT > 0 per company:
for h in hits["results"]:
    client.get(f"capital-receivers/{h['uuid']}/financials/")
```

```bash
python examples/pe_screener.py --min-revenue 25000000 --min-growth 0 --country SGP --profitable-only
```

### 10. Portfolio / watchlist monitoring
**What:** Track owned and target companies for new rounds, valuation changes, financial updates, and news, and diff against the previous run.
**Why:** Replaces manual portfolio surveillance — schedule it and alert on deltas.
**Script:** [`examples/watchlist_monitor.py`](examples/watchlist_monitor.py)

```python
for uuid in watchlist:
    client.get(f"capital-receivers/{uuid}/deals/")
    client.get(f"capital-receivers/{uuid}/financials/")
    client.get(f"capital-receivers/{uuid}/news/")
# The script snapshots these to a state file and reports what changed.
```

```bash
python examples/watchlist_monitor.py c16a0ffd-4dbb-4f7b-a9ca-a3a47f93be67 0e0b0078-15d1-4d9c-b84a-6a862890f306
python examples/watchlist_monitor.py --file watchlist.txt
```

### 11. LP / fundraising intelligence
**What:** Map fund/LP commitment relationships — the commitments into a fund, or the funds an LP backs.
**Why:** Useful as you scale a PE vehicle.
**Script:** [`examples/lp_intelligence.py`](examples/lp_intelligence.py)

```python
client.get(f"funds/{fund_uuid}/commitments/")            # LPs into a fund (transactions[].buyer)
client.get(f"capital-allocators/{lp_uuid}/commitments/") # funds a given LP backs (by name)
```

```bash
python examples/lp_intelligence.py --lp Wavemaker
python examples/lp_intelligence.py --fund "Bain Capital Asia III"
```

> The fund-side feed now names the committing LPs: each commitment carries `transactions[]`, and each transaction's `buyer` is the LP (uuid, name, type). The `--fund` view expands these into one row per LP. The `--lp` view is the reverse lens — the funds a given LP backs.

### 12. Auditor / service-provider signal
**What:** Use auditor and professional-services links as a diligence and network cross-check.
**Why:** A quieter quality/credibility signal.
**Script:** [`examples/service_providers.py`](examples/service_providers.py)

```python
client.get("service-providers/", params={
    "service_type": "service_provider_type_audit", "search": "Deloitte"})
```

```bash
python examples/service_providers.py --search Deloitte
python examples/service_providers.py --service-type service_provider_type_audit -n 50
```

---

## Helper — reference data

Discover the valid filter keys (theme keys, deal types, service types, countries, …) used by the recipes above.
**Script:** [`examples/reference_data.py`](examples/reference_data.py)

```bash
python examples/reference_data.py --categories themes
python examples/reference_data.py --categories themes service_types allocation_deal_types
python examples/reference_data.py --type countries
```

---

## Best practices

- **Cache the token.** Bearer tokens from `POST /v3/token/issue/` last 24h — reuse, don't re-issue per call. `AltClient` does this for you.
- **Wrap filters in a boolean group.** POST bodies need `{"filters": {"all": [...]}}` (or `any` / `not`) — a bare `{"op", "field", "value"}` is rejected. Operators: `eq`, `ne`, `in`, `nin`, `contains`, `gt`, `gte`, `lt`, `lte`, `range`, `isnull`.
- **`limit`/`offset`/`ordering` are query params, even for POST.** The JSON body accepts **only** `filters`; sending any other top-level key returns HTTP 400.
- **Sort server-side where you can.** Pass `ordering` as a query param on list endpoints for a true global top-N; an invalid field returns a 400 listing the valid ones. Fall back to client-side sorting only for rankings the API can't do: values computed per row (IRR, co-investment counts) or read from sub-resources (cap tables, commitments, an allocator's investments — these ignore `ordering`).
- **Bootstrap reference data.** Cache `GET /reference-data/?type=enums` to get valid filter keys (theme keys, stages, etc.). See the helper above.
- **Check `captable_source.type`** before reading cap tables (`managed` vs `snapshot`).
- **Store UUIDs.** There are no integer IDs and no v2→v3 ID mapping.
- **Handle errors:** `429` = back off and retry (built in), `403` = subscription/entitlement gap (not a bug), `401` = bad or expired token, `400` = bad filter (e.g. `/investors/` on a snapshot company).
- **Money is USD-normalized** (`_usd` suffix) — no client-side FX.
