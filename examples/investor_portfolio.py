"""
Recipe 3 — Competitor / co-investor portfolio pull.

Pick any investor (capital allocator) and pull their entire portfolio of
direct investments — what they back and where they concentrate.

Endpoints:
    GET capital-allocators/?search=...               (resolve the firm)
    GET capital-allocators/{uuid}/investments/       (portfolio companies)

Examples:
    python examples/investor_portfolio.py Wavemaker
    python examples/investor_portfolio.py "East Ventures" -n 100 --sort -total_invested_usd
    python examples/investor_portfolio.py --uuid f80754f5-16c7-4aac-9cab-4149285c7220
    python examples/investor_portfolio.py Wavemaker --format json -o out/wavemaker.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, sort_records  # noqa: E402


def main():
    parser = build_parser("Pull an investor's portfolio.", default_limit=50)
    parser.add_argument("name", nargs="?", help="investor name to search for")
    parser.add_argument("--uuid", help="capital allocator UUID (skip the search)")
    args = parser.parse_args()

    if not args.name and not args.uuid:
        parser.error("provide an investor name or --uuid")

    client = AltClient()
    if args.uuid:
        uuid, label = args.uuid, args.uuid
    else:
        matches = client.get(
            "capital-allocators/", params={"search": args.name, "limit": 1}
        ).get("results", [])
        if not matches:
            print(f"No investor matching '{args.name}'.", file=sys.stderr)
            return
        uuid = matches[0]["uuid"]
        label = matches[0].get("display_name")
        print(f"Resolved '{args.name}' -> {label} ({uuid})", file=sys.stderr)

    rows = list(client.paginate(
        f"capital-allocators/{uuid}/investments/",
        params={"limit": args.limit}, max_records=args.limit,
    ))
    rows = sort_records(rows, args.sort or "-total_invested_usd")
    print(f"{label}: {len(rows)} portfolio companies (showing up to {args.limit}).",
          file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
