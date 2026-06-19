"""
Recipe 7 — Fund benchmarking.

Compare IRR / TVPI / DPI / RVPI across funds by vintage to benchmark a GP or
screen funds. Performance metrics are NOT on the fund list, so we fetch the
latest performance record (and fund size) per fund.

Endpoints:
    POST funds/                       filters: vintage_year range
    GET  funds/{uuid}/performance/    (latest IRR/DPI/RVPI/TVPI record)
    GET  funds/{uuid}/aum/            (latest fund size)

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
    aum = latest(client, f"funds/{uuid}/aum/", date_key="aum_value_date")
    managers = fund.get("fund_managers") or []
    return {
        "uuid": uuid,
        "fund": fund.get("display_name"),
        "manager": ", ".join(m.get("display_name") for m in managers),
        "vintage_year": fund.get("vintage_year"),
        "status": pick(fund, "status.name"),
        "fund_size_usd": aum.get("aum_value_usd"),
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
    print(f"Benchmarking {len(funds)} funds (one /performance/ + /aum/ call each)…",
          file=sys.stderr)
    records = sort_records([benchmark(client, f) for f in funds],
                           args.sort or "-irr")
    emit(records, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
