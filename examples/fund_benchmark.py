"""
Recipe 8 — Fund benchmarking.

Compare IRR / TVPI / DPI / RVPI across funds by vintage to benchmark a GP or
screen funds. Fund size and fee terms come on the fund list itself; performance
metrics do not, so we fetch the latest performance record per fund.

Endpoints:
    POST funds/                       filters: vintage_year range
                                      (returns latest_fund_size + fee terms)
    GET  funds/{uuid}/performance/    (latest IRR/DPI/RVPI/TVPI record)

Examples:
    python examples/fund_benchmark.py --vintage-from 2016 --vintage-to 2020
    python examples/fund_benchmark.py --vintage-from 2018 -n 15 --sort=-irr
    python examples/fund_benchmark.py --vintage-from 2016 --format json -o out/funds.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def latest(client, path, date_key="date"):
    """Return the most recent record (by ``date_key``) from a paged sub-endpoint."""
    rows = client.get(path, params={"limit": 100}).get("results", [])
    rows = [r for r in rows if r.get(date_key)]
    return max(rows, key=lambda r: r[date_key]) if rows else {}


def benchmark(client, fund):
    uuid = fund["uuid"]
    perf = latest(client, f"funds/{uuid}/performance/")
    managers = fund.get("fund_managers") or []
    return {
        "uuid": uuid,
        "fund": fund.get("display_name"),
        "manager": ", ".join(m.get("display_name") for m in managers),
        "vintage_year": fund.get("vintage_year"),
        "status": pick(fund, "status.name"),
        # The list row's newest AUM record, null when the fund has none.
        "fund_size_usd": pick(fund, "latest_fund_size.aum_value_usd"),
        "fund_size_as_of": pick(fund, "latest_fund_size.aum_value_date"),
        "management_fee_pct": fund.get("management_fee_percentage"),
        "carry_pct": fund.get("carry_percentage"),
        "hurdle_pct": fund.get("hurdle_percentage"),
        "gp_commitment_pct": fund.get("gp_commitment_percentage"),
        "as_of": perf.get("date"),
        "irr": perf.get("irr"),
        "tvpi": perf.get("net_multiple"),
        "dpi": perf.get("dpi"),
        "rvpi": perf.get("rvpi"),
        "committed_capital_usd": perf.get("committed_capital_usd"),
        "source": perf.get("source"),
    }


def main():
    parser = build_parser("Benchmark funds by vintage.", default_limit=20)
    parser.add_argument("--vintage-from", type=int, metavar="YEAR", required=True,
                        help="earliest vintage year (inclusive)")
    parser.add_argument("--vintage-to", type=int, metavar="YEAR",
                        help="latest vintage year (inclusive)")
    args = parser.parse_args()

    filters = [{"op": "gte", "field": "vintage_year", "value": args.vintage_from}]
    if args.vintage_to:
        filters.append({"op": "lte", "field": "vintage_year", "value": args.vintage_to})

    client = AltClient()
    funds = client.post("funds/", {"filters": {"all": filters}},
                        params={"limit": args.limit}).get("results", [])
    print(f"Benchmarking {len(funds)} funds (one /performance/ call each)…",
          file=sys.stderr)
    records = sort_records([benchmark(client, f) for f in funds],
                           args.sort or "-irr")
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
