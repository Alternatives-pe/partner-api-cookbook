"""
Recipe 5 — Thematic market map.

Landscape every company in a theme (+ optional geography and minimum founding
year), ranked by latest valuation, with revenue alongside. Underpins sector
theses and competitive maps.

Endpoint:
    POST capital-receivers/   filters: themes_keys + country + year_founded

Examples:
    python examples/market_map.py --themes themes_payments
    python examples/market_map.py --themes themes_fintech themes_digital_neo_banking --country SGP
    python examples/market_map.py --themes themes_ai_genai_ml --founded-after 2018 -n 100
    python examples/market_map.py --themes themes_payments --format json -o out/payments_map.json

Tip: run reference_data.py to list valid theme keys.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def row(company):
    le = company.get("legal_entity") or {}
    funding = company.get("funding") or {}
    fin = company.get("latest_financials") or {}
    return {
        "uuid": company["uuid"],
        "name": le.get("display_name"),
        "hq_country": pick(le, "headquarters.country_name"),
        "year_founded": le.get("year_founded"),
        "trading_status": pick(le, "trading_status.name"),
        "themes": [t.get("name") for t in company.get("themes") or []],
        "latest_stage": funding.get("latest_investment_stage_name"),
        "latest_valuation_usd": funding.get("latest_valuation_usd"),
        "total_funding_usd": funding.get("total_funding_amount_usd"),
        "operating_revenue_usd": fin.get("operating_revenue_usd"),
        "revenue_growth_yoy_pct": fin.get("annual_operating_revenue_yoy_growth_pct"),
    }


def main():
    parser = build_parser("Build a thematic market map.", default_limit=100)
    parser.add_argument("--themes", nargs="+", metavar="KEY", required=True,
                        help="theme keys to match (e.g. themes_payments)")
    parser.add_argument("--country", help="HQ country ISO alpha-3 (e.g. SGP)")
    parser.add_argument("--founded-after", type=int, metavar="YEAR",
                        help="only companies founded in this year or later")
    args = parser.parse_args()

    filters = [{"op": "in", "field": "themes_keys", "value": args.themes}]
    if args.country:
        filters.append({"op": "eq", "field": "headquarters_country_iso_alpha3",
                        "value": args.country.upper()})
    if args.founded_after:
        filters.append({"op": "gte", "field": "year_founded", "value": args.founded_after})

    client = AltClient()
    data = client.post("capital-receivers/", {"filters": {"all": filters}},
                       params={"limit": args.limit})
    records = sort_records([row(r) for r in data.get("results", [])],
                           args.sort or "-latest_valuation_usd")
    print(f"{data.get('count')} companies in this map; showing {len(records)}.",
          file=sys.stderr)
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
