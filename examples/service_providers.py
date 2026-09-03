"""
Recipe 13 — Auditor / service-provider signal.

List professional-services firms (auditors by default, but also tax, legal,
fund administration, etc.) as a diligence and network cross-check. The mix of
firms auditing a company is a quieter quality/credibility signal.

Endpoint:
    GET service-providers/?service_type=...&search=...

Examples:
    python examples/service_providers.py
    python examples/service_providers.py --service-type service_provider_type_audit -n 50
    python examples/service_providers.py --search Deloitte
    python examples/service_providers.py --country SGP --format json -o out/auditors_sg.json

Tip: run reference_data.py --categories service_types to list valid type keys.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402


def row(sp):
    le = sp.get("legal_entity") or {}
    return {
        "uuid": sp["uuid"],
        "name": sp.get("display_name"),
        "service_types": [t.get("name") for t in sp.get("service_types") or []],
        "domicile_country": pick(le, "domicile_country.name"),
        "registration_number": (le.get("registration_numbers") or [{}])[0].get("reg_number"),
        "last_updated_at": sp.get("last_updated_at"),
    }


def main():
    parser = build_parser("List service providers (auditors, etc.).")
    parser.add_argument("--service-type", default="service_provider_type_audit",
                        help="service type key (default: auditors)")
    parser.add_argument("--search", help="filter by firm name")
    parser.add_argument("--country", help="keep only firms domiciled in this ISO alpha-3 "
                                          "(filtered client-side)")
    args = parser.parse_args()

    # Sort server-side via `ordering` (query param); the country filter below
    # only narrows the ordered rows, so their order is preserved.
    params = {"limit": args.limit, "ordering": args.sort or "name"}
    if args.service_type:
        params["service_type"] = args.service_type
    if args.search:
        params["search"] = args.search

    client = AltClient()
    rows = [row(sp) for sp in client.paginate("service-providers/", params=params,
                                              max_records=args.limit)]
    if args.country:
        rows = [r for r in rows if r["domicile_country"]
                and args.country.lower() in r["domicile_country"].lower()]
    print(f"{len(rows)} service provider(s).", file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
