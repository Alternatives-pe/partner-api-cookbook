"""
Recipe 12 — LP / fundraising intelligence.

Map limited-partner relationships two ways:
  * --fund: the LPs committed INTO a given fund — one row per committing LP
            (name, type) with the commitment date, asset class and amount.
  * --lp:   where a given limited partner has committed capital — the funds it
            backs, by name. This is the richer view for building a target list.

Use it when raising a fund to profile LPs and the funds they back.

Endpoints:
    GET funds/{uuid}/commitments/               (LPs in a fund)
    GET capital-allocators/{uuid}/commitments/  (commitments made by an LP)

Examples:
    python examples/lp_intelligence.py --lp Wavemaker
    python examples/lp_intelligence.py --fund "Bain Capital Asia III"
    python examples/lp_intelligence.py --fund-uuid 50280c30-d626-44db-8aff-7cdf1eb323bb
    python examples/lp_intelligence.py --lp GIC --format json -o out/gic_commitments.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def resolve(client, path, query, name_field="display_name"):
    res = client.get(path, params={"search": query, "limit": 1}).get("results", [])
    if not res:
        return None, None
    return res[0]["uuid"], res[0].get(name_field)


def fund_lp_rows(commitment):
    """Expand one fund-side commitment into a row per committing LP.

    Each commitment groups one or more transactions; a transaction's ``buyer``
    is the committing LP (uuid, name, type). We emit one row per buyer, with
    the transaction-level amount. Commitments with no transactions still yield
    a single row (LP unknown) so nothing is silently dropped.
    """
    meta = {
        "date": commitment.get("date"),
        "allocation_type": commitment.get("allocation_type_name"),
        "allocation_subtype": commitment.get("allocation_subtype_name"),
    }
    txns = commitment.get("transactions") or []
    if not txns:
        return [{"lp": None, "lp_uuid": None, "lp_type": None, **meta,
                 "amount_committed_usd": commitment.get("investment_amount_usd")}]
    rows = []
    for t in txns:
        buyer = t.get("buyer") or {}
        rows.append({
            "lp": buyer.get("name"),
            "lp_uuid": buyer.get("uuid"),
            "lp_type": buyer.get("type"),
            **meta,
            "amount_committed_usd": t.get("investment_amount_usd"),
        })
    return rows


def lp_commitment_row(r):
    return {
        "fund": pick(r, "fund.display_name"),
        "fund_uuid": pick(r, "fund.uuid"),
        "fund_status": pick(r, "fund.status.name"),
        "vintage_year": pick(r, "fund.vintage_year"),
        "date": r.get("date"),
        "allocation_type": pick(r, "allocation_type.name"),
        "amount_committed_usd": r.get("cash_value_transacted_usd"),
    }


def main():
    parser = build_parser("Map LP / fund commitment relationships.")
    parser.add_argument("--fund", help="fund name (LPs committed into this fund)")
    parser.add_argument("--fund-uuid", help="fund UUID (skip the fund search)")
    parser.add_argument("--lp", help="limited partner name (where this LP commits)")
    parser.add_argument("--lp-uuid", help="capital allocator UUID (skip the LP search)")
    args = parser.parse_args()

    client = AltClient()

    if args.fund or args.fund_uuid:
        uuid, label = (args.fund_uuid, args.fund_uuid) if args.fund_uuid else \
            resolve(client, "funds/", args.fund)
        if not uuid:
            print(f"No fund matching '{args.fund}'.", file=sys.stderr)
            return
        rows = []
        for c in client.paginate(f"funds/{uuid}/commitments/", max_records=args.limit):
            rows.extend(fund_lp_rows(c))
        rows = sort_records(rows, args.sort or "-amount_committed_usd")
        print(f"Fund {label}: {len(rows)} LP commitment(s).", file=sys.stderr)
    elif args.lp or args.lp_uuid:
        uuid, label = (args.lp_uuid, args.lp_uuid) if args.lp_uuid else \
            resolve(client, "capital-allocators/", args.lp)
        if not uuid:
            print(f"No LP matching '{args.lp}'.", file=sys.stderr)
            return
        rows = [lp_commitment_row(r) for r in
                client.paginate(f"capital-allocators/{uuid}/commitments/", max_records=args.limit)]
        rows = sort_records(rows, args.sort or "-amount_committed_usd")
        print(f"LP {label}: {len(rows)} commitment(s) made.", file=sys.stderr)
    else:
        parser.error("provide --fund / --fund-uuid or --lp / --lp-uuid")

    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
