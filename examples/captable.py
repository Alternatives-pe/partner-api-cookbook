"""
Recipe 6 — Cap table & ownership analysis for a target.

For a company, pull who owns what. The shape depends on how the cap table is
sourced, which you must check first:

  * captable_source.type == "managed"  -> transaction-derived positions, with
    share counts, percentages and a holding value. /investors/ is also available
    (investor-centric aggregates with amounts invested).
  * captable_source.type == "snapshot" -> a point-in-time shareholder register
    (percentages only). /investors/ returns HTTP 400 for these.

Endpoints:
    GET capital-receivers/?search=...        (resolve the company)
    GET capital-receivers/{uuid}/            (read captable_source.type)
    GET capital-receivers/{uuid}/captable/
    GET capital-receivers/{uuid}/investors/  (managed only; with --investors)

Examples:
    python examples/captable.py shopback
    python examples/captable.py --uuid c16a0ffd-4dbb-4f7b-a9ca-a3a47f93be67 --investors
    python examples/captable.py grab --format json -o out/grab_captable.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def managed_row(r):
    return {
        "shareholder": pick(r, "shareholder.name"),
        "shareholder_uuid": pick(r, "shareholder.uuid"),
        "shareholder_type": pick(r, "shareholder.type"),
        "shares_held": r.get("shares_currently_held_absolute"),
        "percentage_held": r.get("percentage_held_absolute"),
        "shares_issued": r.get("shares_issued_absolute"),
        "shares_sold": r.get("shares_sold_absolute"),
        "total_invested_usd": r.get("total_invested_usd_absolute"),
        "holding_value_usd": r.get("holding_value_usd"),
    }


def snapshot_row(r):
    return {
        "shareholder": pick(r, "shareholder.name"),
        "shareholder_uuid": pick(r, "shareholder.uuid"),
        "shareholder_type": pick(r, "shareholder.type"),
        "number_of_shares": r.get("number_of_shares"),
        "percentage_held": r.get("percentage_held"),
        "is_former_shareholder": r.get("is_former_shareholder"),
        "start_date": r.get("start_date"),
        "end_date": r.get("end_date"),
    }


def investor_row(r):
    return {
        "investor": r.get("name"),
        "investor_uuid": r.get("uuid"),
        "investor_type": r.get("investor_type"),
        "shares_held": r.get("shares_currently_held"),
        "percentage_held": r.get("current_share_holding_percentage"),
        "amount_invested_usd": r.get("amount_invested_usd"),
        "first_investment_date": r.get("first_investment_date"),
        "latest_investment_date": r.get("latest_investment_date"),
    }


def main():
    parser = build_parser("Pull a company's cap table.", default_limit=100)
    parser.add_argument("query", nargs="?", help="company name to search for")
    parser.add_argument("--uuid", help="company UUID (skip the search)")
    parser.add_argument("--investors", action="store_true",
                        help="show investor-centric aggregates (managed cap tables only)")
    args = parser.parse_args()

    if not args.query and not args.uuid:
        parser.error("provide a company name or --uuid")

    client = AltClient()
    if args.uuid:
        uuid = args.uuid
    else:
        matches = client.get("capital-receivers/",
                             params={"search": args.query, "limit": 1}).get("results", [])
        if not matches:
            print(f"No company matching '{args.query}'.", file=sys.stderr)
            return
        uuid = matches[0]["uuid"]

    detail = client.get(f"capital-receivers/{uuid}/")
    name = pick(detail, "legal_entity.display_name")
    source = pick(detail, "captable_source.type")
    print(f"{name} ({uuid}) — cap table source: {source}", file=sys.stderr)

    if args.investors:
        if source != "managed":
            print("Investor aggregates are only available for 'managed' cap tables. "
                  "Use the cap table view instead.", file=sys.stderr)
            return
        rows = [investor_row(r) for r in
                client.paginate(f"capital-receivers/{uuid}/investors/", max_records=args.limit)]
        rows = sort_records(rows, args.sort or "-percentage_held")
        print(f"{len(rows)} investors.", file=sys.stderr)
        emit(rows, fmt=args.format, output=args.output)
        return

    ct = client.get(f"capital-receivers/{uuid}/captable/", params={"limit": args.limit})
    results = ct.get("results", [])
    fn = managed_row if source == "managed" else snapshot_row
    rows = sort_records([fn(r) for r in results], args.sort or "-percentage_held")
    print(f"{len(rows)} shareholders; as of {ct.get('as_of_date')}.", file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
