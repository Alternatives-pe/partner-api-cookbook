"""
Shared library for the Alternatives Partner API (v3) cookbook.

Provides:
  - AltClient: a thin HTTP client that handles auth, token caching, paging,
    and 429 back-off. The patterns it demonstrates are the ones we recommend
    in every example:
      * read the API key from the environment (never hard-code it)
      * exchange the key for a bearer token and cache it (valid 24h)
      * reuse one session, page with limit/offset, back off on 429
  - CLI + output helpers shared across the cookbook scripts:
      * add_common_args() / build_parser() — standard --limit/--sort/--format/-o
      * emit() — write a list of records as CSV (default) or JSON
      * pick() — pull a value out of a nested dict with a dotted path

Setup:
    cp .env.example .env   # then put your real key in .env
    pip install -r requirements.txt
    python api_client.py   # smoke test
"""

import argparse
import csv
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("ALT_API_KEY")
BASE_URL = os.environ.get("ALT_BASE_URL", "https://api.altdmp.io/v3/partners")
TOKEN_URL = os.environ.get("ALT_TOKEN_URL", "https://api.altdmp.io/v3/token/issue/")


class AltClient:
    """Minimal client for the Partner API. Import this in every example."""

    def __init__(self, api_key=None):
        self.api_key = api_key or API_KEY
        if not self.api_key or self.api_key == "YOUR_API_KEY":
            raise SystemExit(
                "Set ALT_API_KEY in your .env (copy .env.example). "
                "Request a key from support@alternatives.pe."
            )
        self.session = requests.Session()
        self._token = None
        self._token_expiry = 0.0

    def _get_token(self):
        # Reuse the cached token until ~5 min before it expires (tokens last 24h).
        if self._token and time.time() < self._token_expiry - 300:
            return self._token
        resp = self.session.post(TOKEN_URL, json={"api_key": self.api_key}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        # token_duration is in minutes
        self._token_expiry = time.time() + body.get("token_duration", 1440) * 60
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def get(self, path, params=None, max_retries=4):
        url = f"{BASE_URL}/{path.lstrip('/')}"
        for attempt in range(max_retries):
            resp = self.session.get(
                url, headers=self._headers(), params=params, timeout=30
            )
            if resp.status_code == 429:  # rate limited — back off and retry
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()

    def post(self, path, body, params=None, max_retries=4):
        """Advanced filtering via JSON body.

        Filters must be wrapped in a boolean group — ``all`` (AND), ``any`` (OR),
        or ``not`` (NOT) — each holding a list of ``{op, field, value}`` clauses::

            {"filters": {"all": [{"op": "eq", "field": "...", "value": ...}]}}

        Note: the JSON body accepts **only** ``filters``. Pagination and sorting
        (``limit``, ``offset``, ``ordering``) are query parameters — pass them
        via ``params``. Any other top-level body key is rejected with HTTP 400.
        """
        url = f"{BASE_URL}/{path.lstrip('/')}"
        headers = {**self._headers(), "Content-Type": "application/json"}
        for attempt in range(max_retries):
            resp = self.session.post(
                url, headers=headers, json=body, params=params, timeout=30
            )
            if resp.status_code == 429:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()

    def paginate_post(self, path, body, params=None, page_size=200, max_records=None):
        """Yield results across pages of a POST filter endpoint.

        The batch endpoints (e.g. ``capital-receivers/deals/``) take ``filters`` in
        the body and ``limit``/``offset``/``ordering`` as query params. Pass a stable
        ``ordering`` so rows don't shift between pages as you walk the offsets.
        """
        params = dict(params or {})
        params.setdefault("limit", page_size)
        offset = 0
        seen = 0
        while True:
            params["offset"] = offset
            page = self.post(path, body, params=params)
            for row in page.get("results", []):
                yield row
                seen += 1
                if max_records and seen >= max_records:
                    return
            if not page.get("next"):
                break
            offset += params["limit"]

    def paginate(self, path, params=None, page_size=200, max_records=None):
        """Yield results across pages (GET). Stops at ``max_records`` if given."""
        params = dict(params or {})
        params.setdefault("limit", page_size)
        offset = 0
        seen = 0
        while True:
            params["offset"] = offset
            page = self.get(path, params=params)
            for row in page.get("results", []):
                yield row
                seen += 1
                if max_records and seen >= max_records:
                    return
            if not page.get("next"):
                break
            offset += params["limit"]


# --------------------------------------------------------------------------- #
# CLI helpers — shared switches every cookbook script accepts.
# --------------------------------------------------------------------------- #

def add_common_args(parser, default_limit=20, default_format="csv"):
    """Attach the switches common to every cookbook script."""
    parser.add_argument(
        "-n", "--limit", type=int, default=default_limit,
        help="max rows to fetch / return",
    )
    parser.add_argument(
        "-s", "--sort", default=None,
        help="ordering field; prefix with '-' for descending "
             "(e.g. -latest_valuation_usd)",
    )
    parser.add_argument(
        "-f", "--format", choices=["csv", "json"], default=default_format,
        help="output format",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="write to this file instead of stdout",
    )
    return parser


def build_parser(description, default_limit=20, default_format="csv"):
    """Make an ArgumentParser pre-loaded with the common switches."""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser, default_limit=default_limit, default_format=default_format)
    return parser


# --------------------------------------------------------------------------- #
# Output helpers — JSON or CSV, with sensible flattening of nested API records.
# --------------------------------------------------------------------------- #

def pick(record, path, default=None):
    """Pull a value out of a nested dict with a dotted path.

    >>> pick(company, "legal_entity.display_name")
    """
    cur = record
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur if cur is not None else default


def sort_records(records, sort):
    """Sort a list of dict records client-side by a (dotted) key.

    Prefix the key with '-' for descending. Missing/None values always sort
    last. Most list endpoints now support server-side ``ordering`` (pass it as
    a query param for a true global top-N), so prefer that where you can. Use
    this helper for rankings the API can't do for you: values computed
    client-side (IRR, co-investment counts) or read from sub-resources
    (cap tables, commitments), and endpoints without a working ``ordering``.
    Note: this orders only the rows you fetched, not the full result set.
    """
    if not sort:
        return list(records)
    desc = sort.startswith("-")
    key = sort.lstrip("-")
    present = [r for r in records if pick(r, key) is not None]
    missing = [r for r in records if pick(r, key) is None]
    try:
        numeric = {id(r): float(pick(r, key)) for r in present}
        present.sort(key=lambda r: numeric[id(r)], reverse=desc)
    except (TypeError, ValueError):
        present.sort(key=lambda r: str(pick(r, key)).lower(), reverse=desc)
    return present + missing


def _flatten(obj, prefix="", out=None):
    """Flatten a nested dict for CSV.

    Nested dicts become dotted keys. Lists of scalars join with '|'; lists of
    dicts and other complex values are serialized to compact JSON.
    """
    out = {} if out is None else out
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{prefix}.{key}" if prefix else key
            _flatten(val, child, out)
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix] = "|".join("" if x is None else str(x) for x in obj)
        else:
            out[prefix] = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    else:
        out[prefix] = obj
    return out


def emit(records, fmt="csv", output=None, columns=None):
    """Write ``records`` (a list of dicts) as CSV or JSON.

    CSV flattens nested objects (dotted keys); JSON preserves the raw structure.
    ``columns`` optionally fixes the CSV column order; otherwise the union of
    flattened keys is used, in first-seen order.
    """
    records = list(records)
    stream = open(output, "w", newline="", encoding="utf-8") if output else sys.stdout
    try:
        if fmt == "json":
            json.dump(records, stream, indent=2, ensure_ascii=False, default=str)
            stream.write("\n")
            return

        # CSV
        flat = [_flatten(r) for r in records]
        if columns is None:
            columns, seen = [], set()
            for row in flat:
                for key in row:
                    if key not in seen:
                        seen.add(key)
                        columns.append(key)
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in flat:
            writer.writerow(row)
    finally:
        if output:
            stream.close()
            print(f"Wrote {len(records)} rows to {output}", file=sys.stderr)


if __name__ == "__main__":
    client = AltClient()
    # Simple smoke test: search for a company by name.
    data = client.get("capital-receivers/", params={"search": "shopback", "limit": 5})
    print(f"matches: {data.get('count')}")
    for r in data.get("results", []):
        print(" -", pick(r, "legal_entity.display_name"), r.get("uuid"))
