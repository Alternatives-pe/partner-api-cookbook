"""
Recipe 1 — Company enrichment / CRM auto-fill.

Look up a company by name or registration number, then pull the full profile:
identity, trading status, themes, latest funding, and latest financials. Use it
to keep a deal CRM current without manual data entry.

Endpoints:
    GET capital-receivers/?search=...            (or ?registration_number=...)
    GET capital-receivers/{uuid}/                (full profile + financials[])

Examples:
    python examples/enrich_company.py shopback
    python examples/enrich_company.py --reg 201411189G
    python examples/enrich_company.py shopback --format json
    python examples/enrich_company.py grab -n 3 -o out/grab.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402


def enrich(client, company):
    """Build one flat enrichment record from a company's full profile."""
    detail = client.get(f"capital-receivers/{company['uuid']}/")
    le = detail.get("legal_entity") or {}
    funding = detail.get("funding") or {}
    financials = detail.get("financials") or []
    latest_fin = financials[0] if financials else {}
    regs = le.get("registration_numbers") or [{}]
    return {
        "uuid": detail["uuid"],
        "name": le.get("display_name"),
        "registration_number": regs[0].get("reg_number"),
        "domicile_country": pick(le, "domicile_country.name"),
        "hq_country": pick(le, "headquarters.country_name"),
        "trading_status": pick(le, "trading_status.name"),
        "year_founded": le.get("year_founded"),
        "is_female_founder": le.get("is_female_founder"),
        "website": le.get("website_url"),
        "themes": [t.get("name") for t in detail.get("themes") or []],
        "funding_status": detail.get("funding_status"),
        "latest_stage": funding.get("latest_investment_stage_name"),
        "latest_valuation_usd": funding.get("latest_valuation_usd"),
        "total_funding_usd": funding.get("total_funding_amount_usd"),
        "latest_fy_end": latest_fin.get("financial_year_end"),
        "operating_revenue_usd": latest_fin.get("operating_revenue_usd"),
        "revenue_growth_yoy_pct": latest_fin.get("annual_operating_revenue_yoy_growth_pct"),
        "captable_source": pick(detail, "captable_source.type"),
    }


def main():
    parser = build_parser("Enrich a company by name or registration number.",
                          default_limit=5)
    parser.add_argument("query", nargs="?", help="company name to search for")
    parser.add_argument("--reg", help="look up by registration number instead of name")
    args = parser.parse_args()

    if not args.query and not args.reg:
        parser.error("provide a company name or --reg <registration_number>")

    client = AltClient()
    if args.reg:
        params = {"registration_number": args.reg, "limit": args.limit}
    else:
        params = {"search": args.query, "limit": args.limit}
    matches = client.get("capital-receivers/", params=params).get("results", [])

    if not matches:
        print("No matching company found.", file=sys.stderr)
        return

    records = [enrich(client, m) for m in matches]
    print(f"Enriched {len(records)} company record(s).", file=sys.stderr)
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
