"""
Recipe 9 — Co-investor / syndicate network mapping.

Aggregate cap tables across a set of companies to see who co-invests with whom.
Source the companies either by theme (+ optional country) or by passing explicit
company UUIDs, pull each one's investor list, then build an investor-pair
co-occurrence table client-side.

Endpoints:
    POST capital-receivers/                  (source companies by theme/country)
    GET  capital-receivers/{uuid}/investors/ (managed cap tables only)

Examples:
    python examples/syndicate_map.py --themes themes_payments --companies 30
    python examples/syndicate_map.py --themes themes_fintech --country SGP --min-shared 2
    python examples/syndicate_map.py --uuids c16a0ffd-4dbb-4f7b-a9ca-a3a47f93be67 ...
    python examples/syndicate_map.py --themes themes_payments --format json -o out/syndicates.json

Note: companies with a snapshot cap table expose no investor aggregates
(/investors/ returns 400); those are skipped and reported.
"""

import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick, sort_records  # noqa: E402


def source_companies(client, args):
    if args.uuids:
        return [(u, u) for u in args.uuids]
    filters = [{"op": "in", "field": "themes_keys", "value": args.themes}]
    if args.country:
        filters.append({"op": "eq", "field": "headquarters_country_iso_alpha3",
                        "value": args.country.upper()})
    data = client.post("capital-receivers/", {"filters": {"all": filters}},
                       params={"limit": args.companies})
    return [(r["uuid"], pick(r, "legal_entity.display_name")) for r in data.get("results", [])]


def main():
    parser = build_parser("Map co-investor syndicates across companies.", default_limit=50)
    parser.add_argument("--themes", nargs="+", metavar="KEY",
                        help="source companies matching these theme keys")
    parser.add_argument("--country", help="restrict sourced companies to this HQ ISO alpha-3")
    parser.add_argument("--uuids", nargs="+", metavar="UUID",
                        help="explicit company UUIDs instead of a theme search")
    parser.add_argument("--companies", type=int, default=25,
                        help="how many companies to source when using --themes")
    parser.add_argument("--min-shared", type=int, default=1,
                        help="only show pairs that co-invested in at least this many companies")
    args = parser.parse_args()

    if not args.themes and not args.uuids:
        parser.error("provide --themes or --uuids")

    client = AltClient()
    companies = source_companies(client, args)
    print(f"Sourced {len(companies)} companies; pulling investor lists…", file=sys.stderr)

    # For each company, every pair of its investors is a co-investment edge.
    # Accumulate the set of companies in which each pair co-invested.
    names = {}
    co_companies = defaultdict(set)
    skipped = 0
    for cuuid, clabel in companies:
        try:
            investors = client.get(f"capital-receivers/{cuuid}/investors/",
                                   params={"limit": 200}).get("results", [])
        except Exception:
            skipped += 1  # snapshot cap table (HTTP 400) or no access
            continue
        keys = []
        for inv in investors:
            key = inv.get("uuid") or inv.get("name")
            if not key:
                continue
            names[key] = inv.get("name")
            keys.append(key)
        for a, b in combinations(sorted(set(keys)), 2):
            co_companies[(a, b)].add(clabel)

    pairs = [{
        "investor_a": names.get(a),
        "investor_b": names.get(b),
        "shared_company_count": len(shared),
        "shared_companies": sorted(shared),
    } for (a, b), shared in co_companies.items() if len(shared) >= args.min_shared]
    pairs = sort_records(pairs, args.sort or "-shared_company_count")[:args.limit]
    print(f"{len(pairs)} co-investor pairs (>= {args.min_shared} shared); "
          f"{skipped} companies skipped (snapshot/no access).", file=sys.stderr)
    emit(pairs, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
