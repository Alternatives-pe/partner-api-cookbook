"""
Recipe 10 — PE buyout / target screening engine.

Screen for mature, profitable, growing businesses: filter on revenue, revenue
growth and trading status server-side, then enrich each candidate with its
financial history to confirm profitability (earnings before tax > 0). The
earnings field is not directly filterable, so that check is done client-side.

Endpoints:
    POST capital-receivers/                  (revenue + growth + status filters)
    GET  capital-receivers/{uuid}/financials/ (confirm latest EBT > 0)

Examples:
    python examples/pe_screener.py --min-revenue 10000000
    python examples/pe_screener.py --min-revenue 25000000 --min-growth 0 --country SGP
    python examples/pe_screener.py --min-revenue 10000000 --profitable-only -n 50
    python examples/pe_screener.py --min-revenue 10000000 --format json -o out/targets.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def screen(client, company):
    le = company.get("legal_entity") or {}
    funding = company.get("funding") or {}
    uuid = company["uuid"]
    fins = client.get(f"capital-receivers/{uuid}/financials/",
                      params={"limit": 1}).get("results", [])
    latest = fins[0] if fins else {}
    ebt = latest.get("earnings_before_tax_usd")
    try:
        is_profitable = ebt is not None and float(ebt) > 0
    except (TypeError, ValueError):
        is_profitable = None
    return {
        "uuid": uuid,
        "name": le.get("display_name"),
        "hq_country": pick(le, "headquarters.country_name"),
        "trading_status": pick(le, "trading_status.name"),
        "year_founded": le.get("year_founded"),
        "latest_fy_end": latest.get("financial_year_end"),
        "operating_revenue_usd": latest.get("operating_revenue_usd"),
        "revenue_growth_yoy_pct": latest.get("annual_operating_revenue_yoy_growth_pct"),
        "earnings_before_tax_usd": ebt,
        "is_profitable": is_profitable,
        "latest_valuation_usd": funding.get("latest_valuation_usd"),
    }


def main():
    parser = build_parser("Screen for PE buyout targets.", default_limit=50)
    parser.add_argument("--min-revenue", type=float, default=10_000_000,
                        help="minimum latest operating revenue (USD)")
    parser.add_argument("--min-growth", type=float, default=None,
                        help="minimum YoY operating-revenue growth (%%)")
    parser.add_argument("--country", help="HQ country ISO alpha-3 (e.g. SGP)")
    parser.add_argument("--profitable-only", action="store_true",
                        help="keep only companies with latest EBT > 0")
    args = parser.parse_args()

    filters = [
        {"op": "gte", "field": "latest_operating_revenue_usd", "value": args.min_revenue},
        {"op": "eq", "field": "trading_status_name", "value": "Operating"},
    ]
    if args.min_growth is not None:
        filters.append({"op": "gte", "field": "operating_revenue_growth_yoy_pct",
                        "value": args.min_growth})
    if args.country:
        filters.append({"op": "eq", "field": "headquarters_country_iso_alpha3",
                        "value": args.country.upper()})

    client = AltClient()
    candidates = client.post("capital-receivers/", {"filters": {"all": filters}},
                             params={"limit": args.limit}).get("results", [])
    print(f"{len(candidates)} candidates; checking profitability per company…",
          file=sys.stderr)
    records = [screen(client, c) for c in candidates]
    if args.profitable_only:
        records = [r for r in records if r["is_profitable"]]
    records = sort_records(records, args.sort or "-operating_revenue_usd")
    print(f"{len(records)} targets after screening.", file=sys.stderr)
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
