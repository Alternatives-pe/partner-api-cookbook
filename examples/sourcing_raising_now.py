"""
Recipe 2 — Live deal-flow sourcing.

Find companies currently raising, optionally filtered by theme and geography,
ranked by latest valuation. Turns "who's in market right now" into a repeatable
query. Uses POST body filters.

Endpoint:
    POST capital-receivers/   filters: is_raising_now + themes_keys + country

Examples:
    python examples/sourcing_raising_now.py
    python examples/sourcing_raising_now.py --country SGP -n 25
    python examples/sourcing_raising_now.py --themes themes_payments themes_digital_neo_banking
    python examples/sourcing_raising_now.py --country IDN --format json -o out/raising_idn.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402


def row(company):
    le = company.get("legal_entity") or {}
    funding = company.get("funding") or {}
    return {
        "uuid": company["uuid"],
        "name": le.get("display_name"),
        "hq_country": pick(le, "headquarters.country_name"),
        "trading_status": pick(le, "trading_status.name"),
        "year_founded": le.get("year_founded"),
        "themes": [t.get("name") for t in company.get("themes") or []],
        "latest_stage": funding.get("latest_investment_stage_name"),
        "latest_valuation_usd": funding.get("latest_valuation_usd"),
        "total_funding_usd": funding.get("total_funding_amount_usd"),
    }


def main():
    parser = build_parser(
        "Find companies currently raising a round.", default_limit=50
    )
    parser.add_argument("--country", help="HQ country ISO alpha-3 (e.g. SGP, IDN)")
    parser.add_argument(
        "--themes", nargs="+", metavar="KEY",
        help="theme keys to match (e.g. themes_payments). See reference_data.py.",
    )
    args = parser.parse_args()

    filters = [{"op": "eq", "field": "is_raising_now", "value": True}]
    if args.country:
        filters.append({
            "op": "eq", "field": "headquarters_country_iso_alpha3",
            "value": args.country.upper(),
        })
    if args.themes:
        filters.append({"op": "in", "field": "themes_keys", "value": args.themes})

    client = AltClient()
    # Sort server-side via `ordering` (query param) so we get a true top-N
    # across the whole result set, not just within the fetched window.
    data = client.post(
        "capital-receivers/",
        {"filters": {"all": filters}},
        params={"limit": args.limit, "ordering": args.sort or "-latest_valuation_usd"},
    )
    records = [row(r) for r in data.get("results", [])]
    print(f"{data.get('count')} companies raising now; showing {len(records)}.",
          file=sys.stderr)
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
