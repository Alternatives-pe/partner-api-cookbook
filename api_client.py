"""
Shared library for the Alternatives Partner API (v3) cookbook.

Provides:
  - AltClient: a thin HTTP client that handles auth, token caching, paging,
    and rate-limit cooldowns. The patterns it demonstrates are the ones we recommend
    in every example:
      * read the API key from the environment (never hard-code it)
      * exchange the key for a bearer token and cache it (valid 24h)
      * reuse one session, page with limit/offset, or by keyset on
        (aggregate_updated_at, uuid) for an incremental sync (paginate_changed)
      * on 429, wait the cooldown the response asks for, then retry
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
import random
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# Longest single cooldown we will sit through before giving up and raising. A
# rolling-window limit hands back a delta of seconds; anything beyond this is
# better surfaced to the caller than slept off inside a script.
MAX_RETRY_WAIT = float(os.environ.get("ALT_MAX_RETRY_WAIT", "120"))

API_KEY = os.environ.get("ALT_API_KEY")
BASE_URL = os.environ.get("ALT_BASE_URL", "https://api.altdmp.io/v3/partners")
TOKEN_URL = os.environ.get("ALT_TOKEN_URL", "https://api.altdmp.io/v3/token/issue/")


class RateLimitExceeded(requests.HTTPError):
    """A 429 that outlived the retry budget.

    Subclasses ``requests.HTTPError`` so callers that already catch that keep
    working, and carries the response so ``exc.response`` still holds the
    server's headers and body.
    """


def _rate_limit_wait(resp, attempt):
    """Seconds to wait before retrying a 429.

    Prefers the server's own cooldown over anything we could guess: the API
    returns ``Retry-After`` and ``X-RateLimit-Reset`` as a delta in seconds —
    the time until the rolling window frees capacity — and repeats it in the
    body as ``retry_after_seconds``. Falls back to exponential backoff only when
    the response carries none of them.

    A little jitter is added so several clients released from the same window
    don't retry on the same tick and immediately re-trip the limit.
    """
    wait = None
    header = resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset")
    if header is not None:
        try:
            wait = float(header)
        except ValueError:
            # Retry-After also has an HTTP-date form. This API sends seconds, so
            # rather than parse dates, fall through to backoff.
            wait = None
    if wait is None:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("retry_after_seconds") is not None:
            try:
                wait = float(body["retry_after_seconds"])
            except (TypeError, ValueError):
                wait = None
    if wait is None:
        wait = float(2 ** attempt)
    return max(wait, 0.0) + random.uniform(0, 0.5)


def _rate_limit_detail(resp):
    """Human-readable summary of which limit was hit, for logs and errors."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    bits = []
    for key in ("scope", "dimension"):
        if body.get(key):
            bits.append(f"{key}={body[key]}")
    limit = resp.headers.get("X-RateLimit-Limit")
    if limit:
        bits.append(f"limit={limit}")
    return ", ".join(bits) or "no scope reported"


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

    def _request(self, method, url, headers=None, params=None, json_body=None,
                 max_retries=4):
        """Send one request, waiting out 429s for as long as the server asks.

        Rate-limit responses carry the exact cooldown (``Retry-After``, mirrored
        in the body as ``retry_after_seconds``), so we sleep for that rather than
        guessing with a fixed backoff — retrying early just burns another slot in
        the window. Every other error is raised as usual.
        """
        for attempt in range(max_retries + 1):
            resp = self.session.request(
                method, url, headers=headers, params=params, json=json_body,
                timeout=30,
            )
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            if attempt == max_retries:
                break
            wait = _rate_limit_wait(resp, attempt)
            if wait > MAX_RETRY_WAIT:
                raise RateLimitExceeded(
                    f"Rate limited ({_rate_limit_detail(resp)}); the API asked for "
                    f"{wait:.0f}s, above the {MAX_RETRY_WAIT:.0f}s cap. Raise "
                    f"ALT_MAX_RETRY_WAIT to wait longer.",
                    response=resp,
                )
            print(
                f"Rate limited ({_rate_limit_detail(resp)}); "
                f"waiting {wait:.0f}s before retry {attempt + 1}/{max_retries}…",
                file=sys.stderr,
            )
            time.sleep(wait)
        raise RateLimitExceeded(
            f"Rate limited ({_rate_limit_detail(resp)}) and still limited after "
            f"{max_retries} retries.",
            response=resp,
        )

    def _get_token(self):
        # Reuse the cached token until ~5 min before it expires (tokens last 24h).
        if self._token and time.time() < self._token_expiry - 300:
            return self._token
        # Token issuance is rate-limited on its own scope (token.issue), and a
        # script that re-issues per process trips it well before any data call
        # does — so this goes through the same retry path as everything else.
        resp = self._request("POST", TOKEN_URL, json_body={"api_key": self.api_key})
        body = resp.json()
        self._token = body["access_token"]
        # token_duration is in minutes
        self._token_expiry = time.time() + body.get("token_duration", 1440) * 60
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def get(self, path, params=None, max_retries=4):
        url = f"{BASE_URL}/{path.lstrip('/')}"
        return self._request(
            "GET", url, headers=self._headers(), params=params,
            max_retries=max_retries,
        ).json()

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
        return self._request(
            "POST", url, headers=headers, params=params, json_body=body,
            max_retries=max_retries,
        ).json()

    def paginate_post(self, path, body, params=None, page_size=200, max_records=None):
        """Yield results across pages of a POST filter endpoint.

        The batch endpoints (e.g. ``capital-receivers/deals/``) take ``filters`` in
        the body and ``limit``/``offset``/``ordering`` as query params. Pass a stable
        ``ordering`` so rows don't shift between pages as you walk the offsets.
        Don't use this to page by ``aggregate_updated_at``: that value changes
        mid-pull, so an offset walk can skip a row. Use paginate_changed().
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

    def paginate_changed(self, path, since, filters=None, page_size=1000, max_records=None):
        """Yield every record on a list endpoint that changed at or after ``since``.

        Works on the five list endpoints (capital-receivers, capital-allocators,
        funds, people, service-providers). ``since`` is an ISO 8601 date-time
        with a UTC offset, e.g. ``"2026-09-24T00:00:00Z"``; ``filters`` is an
        optional list of extra conditions ANDed onto the window.

        Pages by keyset on (aggregate_updated_at, uuid) instead of by offset. The
        watermark changes while you page: a record edited mid-pull jumps to the
        end, every later row moves up one place, and the next offset page skips
        one. Asking for "everything after the last row's (value, uuid)" cannot
        skip. The uuid half matters because one change can stamp many records
        with the same instant.

        A record edited mid-pull comes round twice, and the later copy is the
        newer one, so store rows by uuid and let the later one win.
        """
        params = {"ordering": "aggregate_updated_at,uuid", "limit": page_size}
        base = list(filters or [])
        window = [{"op": "gte", "field": "aggregate_updated_at", "value": since}]
        yielded = 0
        while True:
            body = {"filters": {"all": base + window}}
            rows = self.post(path, body, params=params).get("results", [])
            for row in rows:
                yield row
                yielded += 1
                if max_records and yielded >= max_records:
                    return
            if len(rows) < page_size:
                return
            last = rows[-1]
            value = last["aggregate_updated_at"]
            window = [
                {"op": "gte", "field": "aggregate_updated_at", "value": value},
                {"any": [
                    {"op": "gt", "field": "aggregate_updated_at", "value": value},
                    {"op": "gt", "field": "uuid", "value": last["uuid"]},
                ]},
            ]


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
    last. List and sub-resource endpoints support server-side ``ordering``
    (pass it as a query param for a true global top-N), so prefer that where
    you can. Use this helper for rankings the API can't do for you: values
    computed client-side (IRR, co-investment counts) or rows from fixed-order
    routes (cap tables, a company's investors), which return 400 for any
    ``ordering``.
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
