"""CSV-backed offline cache.

No database by design. After every successful upstream fetch we write the
normalized matches to CSV; on startup (or whenever every live provider fails)
we load them back. A committed public-domain seed in ``data/seed`` guarantees
the app shows real fixtures the very first time it runs, even with no network.

Standings are recomputed from matches on read, so only matches need to persist.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timezone
from typing import List, Optional

from .models import Match

_FIELDS = [
    "id", "group", "stage", "utc_date", "status",
    "home", "away", "home_score", "away_score", "minute", "venue",
]


def _to_int(value: str) -> Optional[int]:
    return int(value) if value not in ("", None) else None


class CsvStore:
    def __init__(self, cache_dir: str, seed_dir: str):
        self.cache_dir = cache_dir
        self.seed_dir = seed_dir
        self.matches_path = os.path.join(cache_dir, "matches.csv")
        self.meta_path = os.path.join(cache_dir, "meta.json")
        os.makedirs(cache_dir, exist_ok=True)

    # -- writing -----------------------------------------------------------
    def save(self, matches: List[Match], source: str) -> None:
        tmp = self.matches_path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            for m in matches:
                writer.writerow({k: ("" if v is None else v) for k, v in m.to_dict().items()})
        os.replace(tmp, self.matches_path)
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"updated_at": datetime.now(timezone.utc).isoformat(), "source": source},
                fh,
            )

    # -- reading -----------------------------------------------------------
    def _read_csv(self, path: str) -> List[Match]:
        matches: List[Match] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                matches.append(
                    Match(
                        id=row["id"],
                        group=row["group"] or None,
                        stage=row["stage"],
                        utc_date=row["utc_date"],
                        status=row["status"],
                        home=row["home"],
                        away=row["away"],
                        home_score=_to_int(row["home_score"]),
                        away_score=_to_int(row["away_score"]),
                        minute=_to_int(row["minute"]),
                        venue=row["venue"] or None,
                    )
                )
        return matches

    def load(self) -> List[Match]:
        """Load cached matches, falling back to the committed seed snapshot."""
        if os.path.exists(self.matches_path):
            return self._read_csv(self.matches_path)
        seed = os.path.join(self.seed_dir, "matches.csv")
        if os.path.exists(seed):
            shutil.copy(seed, self.matches_path)
            return self._read_csv(self.matches_path)
        return []

    def meta(self) -> dict:
        if os.path.exists(self.meta_path):
            with open(self.meta_path, encoding="utf-8") as fh:
                return json.load(fh)
        return {"updated_at": None, "source": "seed"}
