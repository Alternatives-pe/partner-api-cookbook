"""
Recipe 4 — Founder / director background check.

Look up a person and see their track record: organisational roles (founder,
director, etc.) and any personal investment history. Lightweight diligence and
reference-checking.

Endpoints:
    GET people/?search=...              (resolve the person)
    GET people/{uuid}/                  (profile)
    GET people/{uuid}/roles/            (roles across organisations)
    GET people/{uuid}/investments/      (personal angel investments)

Note: server-side role_type filtering is unreliable, so we fetch all roles and
filter client-side with --role.

Examples:
    python examples/person_background.py "Shanru Lai"
    python examples/person_background.py "Henry Chan" --role founder
    python examples/person_background.py --uuid f2eac778-a47b-497e-a4c6-ddd71335a404
    python examples/person_background.py "Shanru Lai" --investments --format json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402


def role_row(r):
    return {
        "role": pick(r, "role_type.name"),
        "role_key": pick(r, "role_type.key"),
        "organization": pick(r, "organization.display_name"),
        "organization_uuid": pick(r, "organization.uuid"),
        "title": r.get("title"),
        "is_current": r.get("is_current"),
        "start_date": r.get("start_date"),
        "end_date": r.get("end_date"),
    }


def main():
    parser = build_parser("Background-check a founder or director.", default_limit=50)
    parser.add_argument("name", nargs="?", help="person name to search for")
    parser.add_argument("--uuid", help="person UUID (skip the search)")
    parser.add_argument("--role", help="only show roles whose key/name contains this (e.g. founder)")
    parser.add_argument("--investments", action="store_true",
                        help="show personal investment history instead of roles")
    args = parser.parse_args()

    if not args.name and not args.uuid:
        parser.error("provide a person name or --uuid")

    client = AltClient()
    if args.uuid:
        uuid = args.uuid
    else:
        matches = client.get(
            "people/", params={"search": args.name, "limit": 1}
        ).get("results", [])
        if not matches:
            print(f"No person matching '{args.name}'.", file=sys.stderr)
            return
        uuid = matches[0]["uuid"]

    profile = client.get(f"people/{uuid}/")
    print(f"{profile.get('display_name')} ({uuid}) — "
          f"{pick(profile, 'location_country.name', 'location n/a')}; "
          f"{profile.get('linkedin_url') or 'no LinkedIn'}", file=sys.stderr)

    if args.investments:
        rows = list(client.paginate(f"people/{uuid}/investments/", max_records=args.limit))
        print(f"{len(rows)} personal investment(s).", file=sys.stderr)
        emit(rows, fmt=args.format, output=args.output)
        return

    roles = [role_row(r) for r in client.paginate(f"people/{uuid}/roles/", max_records=args.limit)]
    if args.role:
        needle = args.role.lower()
        roles = [r for r in roles
                 if needle in (r["role_key"] or "").lower()
                 or needle in (r["role"] or "").lower()]
    print(f"{len(roles)} role(s)" + (f" matching '{args.role}'." if args.role else "."),
          file=sys.stderr)
    emit(roles, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
