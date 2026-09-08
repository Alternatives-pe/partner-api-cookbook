"""
Recipe 5 — Market-wide deal flow.

Every funding round across the market in a date window, in one paginated query —
no company list needed. Answers "what closed in the last quarter, and what were
the biggest rounds", which previously meant walking companies one at a time and
throwing away everything outside the window.

Endpoint:
    POST capital-receivers/deals/   filters: date window (+ optional deal type,
                                    minimum size); ordering/limit/offset as
                                    query params

The date filter is what makes this a market-wide query, and the API requires a
lower bound on it — `--since` (or `--since` with `--until` for a range). An
upper bound alone is rejected, so the result set is always bounded.

Examples:
    python examples/deal_flow.py --since 2026-06-01
    python examples/deal_flow.py --since 2026-01-01 --until 2026-03-31
    python examples/deal_flow.py --since 2026-06-01 --sort=-total_deal_size_usd -n 25
    python examples/deal_flow.py --since 2026-06-01 --deal-type seed series_a
    python examples/deal_flow.py --since 2026-06-01 --min-size 10000000
    python examples/deal_flow.py --since 2026-06-01 --format json -o out/deal_flow.json

Tip: run reference_data.py --categories allocation_deal_types for valid
--deal-type keys.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402

# Sort keys the endpoint accepts. `deal_size_usd` is null on Reported deals and
# nulls sort last, so it ranks only part of the market — `total_deal_size_usd` is
# the one that ranks every deal together. See "Deal size" below.
SORT_KEYS = (
    "date", "total_deal_size_usd", "deal_size_usd", "reported_deal_size_usd",
    "post_money_valuation_usd", "no_shares_issued", "provenance",
)


def row(deal):
    """One CSV/JSON row per deal.

    Deal size comes in three fields: `deal_size_usd` carries the round size when
    the deal's provenance is not Reported, `reported_deal_size_usd` when it is —
    exactly one of the pair is ever populated. `total_deal_size_usd` is the same
    number without that split, so it is the column to filter, sort and read.

    Company identity is inline: every row carries a nested `capital_receiver`
    block holding the profile UUID and the legal entity's name and registration
    numbers, so naming a market-wide window costs no extra call.
    """
    reg_numbers = pick(deal, "capital_receiver.legal_entity.registration_numbers") or []
    return {
        "date": deal.get("date"),
        "company": pick(deal, "capital_receiver.legal_entity.display_name"),
        "company_uuid": deal.get("capital_receiver_uuid"),   # capital receiver profile UUID
        "company_reg_number": reg_numbers[0].get("reg_number") if reg_numbers else None,
        "deal_type": deal.get("allocation_deal_type_name"),
        "deal_type_key": deal.get("allocation_deal_type_key"),
        "stage_label": deal.get("self_declared_label"),
        "total_deal_size_usd": deal.get("total_deal_size_usd"),
        "post_money_valuation_usd": deal.get("post_money_valuation_usd"),
        "provenance": pick(deal, "provenance.name"),
        "transactions": deal.get("count_of_transactions"),
        "deal_uuid": deal.get("uuid"),
    }


def main():
    parser = build_parser(
        "List funding rounds across the market in a date window.", default_limit=50
    )
    parser.add_argument(
        "--since", metavar="YYYY-MM-DD",
        help="earliest deal date (default: 90 days ago). Required by the API — a "
             "market-wide query must have a lower bound.",
    )
    parser.add_argument("--until", metavar="YYYY-MM-DD", help="latest deal date")
    parser.add_argument(
        "--deal-type", nargs="+", metavar="KEY",
        help="allocation deal type keys (e.g. seed series_a). See reference_data.py.",
    )
    parser.add_argument(
        "--min-size", type=float, metavar="USD",
        help="minimum total deal size in USD",
    )
    args = parser.parse_args()

    since = args.since or (date.today() - timedelta(days=90)).isoformat()
    for label, value in (("--since", since), ("--until", args.until)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                parser.error(f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}")

    sort = args.sort or "-date"
    if sort.lstrip("-") not in SORT_KEYS:
        parser.error(f"--sort must be one of: {', '.join(SORT_KEYS)}")

    # The date lower bound is not optional: without company UUIDs the API requires
    # one so a market-wide query can never be unbounded. `--until` narrows the top
    # end; on its own it would be rejected.
    filters = [{"op": "gte", "field": "date", "value": since}]
    if args.until:
        filters.append({"op": "lte", "field": "date", "value": args.until})
    if args.deal_type:
        # `_key` fields take the stable keys the response and reference-data carry.
        # The name-matching siblings (deal_transaction_type) are case-sensitive.
        filters.append({"op": "in", "field": "deal_transaction_type_key",
                        "value": args.deal_type})
    if args.min_size:
        filters.append({"op": "gte", "field": "total_deal_size_usd",
                        "value": args.min_size})

    client = AltClient()
    body = {"filters": {"all": filters}}
    # Sorted server-side, so -n really is the global top-N for the window rather
    # than the top of whatever we happened to fetch.
    try:
        deals = list(client.paginate_post(
            "capital-receivers/deals/", body,
            params={"ordering": sort}, max_records=args.limit,
        ))
    except requests.HTTPError as exc:
        # The endpoint states what it wants, so pass its message through rather
        # than a traceback. A 400 here usually means the date filter did not carry
        # a lower bound, or this deployment predates market-wide date filtering and
        # still requires a capital_receiver_uuid filter (watchlist_monitor.py shows
        # that mode).
        resp = exc.response
        detail = ""
        if resp is not None:
            try:
                detail = resp.json().get("detail", resp.text[:300])
            except ValueError:
                detail = resp.text[:300]
            raise SystemExit(f"API rejected the query (HTTP {resp.status_code}): {detail}")
        raise

    records = [row(d) for d in deals]
    window = f"{since} to {args.until}" if args.until else f"{since} onward"
    print(f"{len(records)} deals ({window}), sorted by {sort}.", file=sys.stderr)
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
