"""Scheduled data refresh — re-ingest, rebuild features, retrain, stamp the time.

Meant to run on a cron/launchd schedule (e.g. daily) so a live season's injuries,
lineups and transfers stay current. On a completed season this re-fetches the same
(cached) data — the plumbing is the point.

A file lock prevents overlapping runs. After it finishes, `meta.lastRefresh` is set;
`/api/health` and the app masthead surface it. A running API server picks up the new
data on its next model reload (restart or POST /api/ingest).

Usage:  python refresh.py
"""
from __future__ import annotations
import fcntl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOCK = Path("/tmp/wiq-refresh.lock")


def main() -> int:
    lock_fd = open(LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("refresh: another run is in progress — skipping")
        return 0

    import ingest
    import features as feat
    import fpl
    import risk
    import db

    t0 = time.time()
    print(f"refresh: start {datetime.now(timezone.utc).isoformat()}")
    counts = ingest.ingest()
    feat.compute_features()
    try:
        fpl.build_player_map()
    except Exception as e:  # noqa: BLE001 — FPL is optional
        print(f"refresh: FPL map skipped ({e})")
    risk.train_model()

    db.get_db()["meta"].update_one(
        {"_id": "meta"}, {"$set": {"lastRefresh": datetime.now(timezone.utc)}})
    print(f"refresh: done in {time.time() - t0:.0f}s — {counts.get('games')} games")
    return 0


if __name__ == "__main__":
    sys.exit(main())
