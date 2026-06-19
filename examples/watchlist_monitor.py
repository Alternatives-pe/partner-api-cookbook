"""
Recipe 10 — Portfolio / watchlist monitoring.

Track owned and target companies for new funding rounds, financial updates and
news. Each run snapshots a few signals per company, compares against the previous
run's state file, and reports what changed — so you can run it on a schedule and
alert on deltas.

Endpoints (per company):
    GET capital-receivers/{uuid}/deals/
    GET capital-receivers/{uuid}/financials/
    GET capital-receivers/{uuid}/news/

State is stored in --state (default data/watchlist_state.json; data/ is
gitignored). The first run establishes the baseline (everything shows as "new").

Examples:
    python examples/watchlist_monitor.py c16a0ffd-4dbb-4f7b-a9ca-a3a47f93be67
    python examples/watchlist_monitor.py --file watchlist.txt
    python examples/watchlist_monitor.py <uuid1> <uuid2> --format json
    python examples/watchlist_monitor.py <uuid> --state /tmp/state.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_client import AltClient, build_parser, emit, pick  # noqa: E402


def snapshot(client, uuid):
    """Capture a small set of monitorable signals for one company."""
    detail = client.get(f"capital-receivers/{uuid}/")
    deals = client.get(f"capital-receivers/{uuid}/deals/", params={"limit": 100})
    fins = client.get(f"capital-receivers/{uuid}/financials/", params={"limit": 1})
    news = client.get(f"capital-receivers/{uuid}/news/", params={"limit": 100})
    deal_rows = deals.get("results", [])
    fin_rows = fins.get("results", [])
    news_rows = news.get("results", [])
    return {
        "uuid": uuid,
        "name": pick(detail, "legal_entity.display_name"),
        "latest_valuation_usd": pick(detail, "funding.latest_valuation_usd"),
        "latest_stage": pick(detail, "funding.latest_investment_stage_name"),
        "deal_count": deals.get("count"),
        "latest_deal_date": max((d.get("date") for d in deal_rows if d.get("date")), default=None),
        "latest_fy_end": fin_rows[0].get("financial_year_end") if fin_rows else None,
        "news_count": news.get("count"),
        "latest_news_date": max((n.get("date") for n in news_rows if n.get("date")), default=None),
    }


def diff(prev, cur):
    """Human-readable list of changed signals between two snapshots."""
    if prev is None:
        return ["new to watchlist"]
    watched = [
        ("deal_count", "deals"),
        ("latest_deal_date", "latest deal"),
        ("latest_valuation_usd", "valuation"),
        ("latest_stage", "stage"),
        ("latest_fy_end", "financials"),
        ("news_count", "news"),
        ("latest_news_date", "latest news"),
    ]
    changes = []
    for key, label in watched:
        if prev.get(key) != cur.get(key):
            changes.append(f"{label}: {prev.get(key)} -> {cur.get(key)}")
    return changes


def main():
    parser = build_parser("Monitor a watchlist of companies for changes.")
    parser.add_argument("uuids", nargs="*", help="company UUIDs to monitor")
    parser.add_argument("--file", help="text file with one company UUID per line")
    parser.add_argument("--state", default="data/watchlist_state.json",
                        help="path to the JSON state file")
    args = parser.parse_args()

    uuids = list(args.uuids)
    if args.file:
        uuids += [ln.strip() for ln in Path(args.file).read_text().splitlines()
                  if ln.strip() and not ln.startswith("#")]
    if not uuids:
        parser.error("provide one or more UUIDs or --file")

    client = AltClient()
    state_path = Path(args.state)
    prev_state = {}
    if state_path.exists():
        prev_state = {r["uuid"]: r for r in json.loads(state_path.read_text())}

    rows, new_state = [], []
    for uuid in uuids:
        cur = snapshot(client, uuid)
        changes = diff(prev_state.get(uuid), cur)
        new_state.append(cur)
        rows.append({**cur, "changes": changes or ["no change"]})

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, indent=2, default=str))
    changed = sum(1 for r in rows if r["changes"] != ["no change"])
    print(f"Monitored {len(rows)} companies; {changed} with changes. "
          f"State saved to {state_path}.", file=sys.stderr)
    emit(rows, fmt=args.format, output=args.output)


if __name__ == "__main__":
    main()
