"""
Helper — Reference data (filter taxonomies).

Dump the lookup lists used for filtering — theme keys, allocation deal types,
service types, countries, etc. Cache this at startup to build UI dropdowns or to
discover valid filter keys for the other recipes.

Endpoint:
    GET reference-data/?type=enums&enum_categories=...

Examples:
    python examples/reference_data.py --categories themes
    python examples/reference_data.py --categories themes service_types allocation_deal_types
    python examples/reference_data.py --type countries
    python examples/reference_data.py --categories themes --format json -o out/themes.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit  # noqa: E402


def main():
    parser = build_parser("List reference-data taxonomies (keys + names).",
                          default_limit=1000)
    parser.add_argument("--type", default="enums",
                        help="section: enums, countries, cities, industries, business_sic_codes")
    parser.add_argument("--categories", nargs="+", metavar="CAT",
                        help="when type=enums, restrict to these enum categories "
                             "(e.g. themes service_types)")
    args = parser.parse_args()

    params = {"type": args.type}
    if args.type == "enums" and args.categories:
        params["enum_categories"] = ",".join(args.categories)

    client = AltClient()
    data = client.get("reference-data/", params=params)

    # Flatten into (category, key, name) rows so CSV and JSON are both useful.
    rows = []
    if args.type == "enums":
        for category, values in (data.get("enums") or {}).items():
            for v in values:
                rows.append({"category": category, "key": v.get("key"), "name": v.get("name")})
    else:
        for v in data.get(args.type) or []:
            rows.append(v)

    rows = rows[:args.limit]
    print(f"{len(rows)} reference rows.", file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
