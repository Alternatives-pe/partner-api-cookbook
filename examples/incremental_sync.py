"""
Recipe 14: Incremental sync.

Keep a local copy of a list current by pulling only the records that changed
since the last run, instead of re-fetching the full set. Every capital receiver,
capital allocator, fund, person and service provider carries
`aggregate_updated_at`: the last time the record, or anything shown on it
(financials, transactions, the cap table, news, ...), changed. It includes the
record's own edits, so it is the one field to poll.

Endpoints:
    POST capital-receivers/     (or capital-allocators/, funds/, people/,
    POST service-providers/)     with an aggregate_updated_at window

How it works:
    * The previous run's high-water mark is read from --state (default
      data/sync_state.json; data/ is gitignored). The first run pulls everything
      changed in the last --days days.
    * Each pull starts --overlap minutes before that mark. Two changes saved at
      nearly the same moment can become visible in the opposite order to their
      timestamps, and the overlap means the earlier one is never missed.
    * Pages by keyset on (aggregate_updated_at, uuid), never by offset: a record
      edited mid-pull would otherwise shift every later row and one would be
      skipped. See AltClient.paginate_changed.
    * Rows are merged by uuid, so a record that comes round twice is reported
      once, with its newest value.

Two things to design for:
    * A record can move with no visible change, when the change was to data the
      API does not show (for example a hidden investor's transaction). Treat a
      new value as "something may have changed", not "the payload differs".
    * Removals are not reported. A deleted or unpublished record just stops
      appearing; compare the uuids you hold against a full pull now and then.

Examples:
    python examples/incremental_sync.py
    python examples/incremental_sync.py --entity funds --days 30
    python examples/incremental_sync.py --since 2026-09-24T00:00:00Z --no-save
    python examples/incremental_sync.py --entity people --format json -o out/people_changed.json
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402

ENTITIES = {
    "capital-receivers": lambda r: pick(r, "legal_entity.display_name"),
    "capital-allocators": lambda r: r.get("display_name"),
    "funds": lambda r: r.get("display_name"),
    "people": lambda r: r.get("display_name"),
    "service-providers": lambda r: r.get("display_name"),
}


def iso_z(moment):
    """A UTC datetime as the offset-qualified ISO 8601 string the filter requires."""
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    """Parse an API timestamp such as 2026-09-24T03:12:45.118204Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    parser = build_parser("Pull the records that changed since the last run.",
                          default_limit=0)
    parser.add_argument("--entity", choices=sorted(ENTITIES), default="capital-receivers",
                        help="which list to sync")
    parser.add_argument("--since", help="start of the window, ISO 8601 with an offset "
                                        "(overrides the saved high-water mark)")
    parser.add_argument("--days", type=int, default=7,
                        help="window for a first run with no saved state")
    parser.add_argument("--overlap", type=int, default=5,
                        help="minutes to start before the saved high-water mark")
    parser.add_argument("--state", default="data/sync_state.json",
                        help="path to the JSON state file holding the high-water marks")
    parser.add_argument("--no-save", action="store_true",
                        help="do not update the state file")
    args = parser.parse_args()
    if args.sort:
        parser.error("--sort is fixed to aggregate_updated_at,uuid for a keyset pull")

    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    mark = state.get(args.entity)

    if args.since:
        since = args.since
    elif mark:
        since = iso_z(parse_iso(mark) - timedelta(minutes=args.overlap))
    else:
        since = iso_z(datetime.now(timezone.utc) - timedelta(days=args.days))

    client = AltClient()
    latest = {}
    for record in client.paginate_changed(f"{args.entity}/", since,
                                          max_records=args.limit or None):
        latest[record["uuid"]] = record  # a later copy of the same record is newer

    name_of = ENTITIES[args.entity]
    rows = [
        {
            "uuid": uuid,
            "name": name_of(record),
            "aggregate_updated_at": record.get("aggregate_updated_at"),
        }
        for uuid, record in latest.items()
    ]
    # Compare parsed times, not strings: the API omits microseconds when they are
    # zero, so "...:45Z" sorts after "...:45.1Z" as text but is earlier in time.
    rows.sort(key=lambda r: (parse_iso(r["aggregate_updated_at"]), r["uuid"]))

    new_mark = max((r["aggregate_updated_at"] for r in rows),
                   key=parse_iso, default=mark)
    if new_mark and not args.no_save:
        state[args.entity] = new_mark
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))

    print(f"{len(rows)} {args.entity} changed since {since}. "
          f"High-water mark: {new_mark or 'none'}"
          f"{'' if args.no_save else f' (saved to {state_path})'}.", file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
