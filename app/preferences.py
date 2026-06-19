"""User team preferences — persisted to a small JSON file (no database).

Exactly one favorite team and any number of followed teams. The favorite is
never also in the following list; the store enforces that invariant on save so
the rest of the app never has to.
"""
from __future__ import annotations

import json
import os
import threading
from typing import List, Optional


class PreferencesStore:
    def __init__(self, cache_dir: str):
        os.makedirs(cache_dir, exist_ok=True)
        self.path = os.path.join(cache_dir, "preferences.json")
        self._lock = threading.Lock()

    def load(self) -> dict:
        with self._lock:
            if not os.path.exists(self.path):
                return {"favorite": None, "following": []}
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (ValueError, OSError):
                return {"favorite": None, "following": []}
        return self._normalize(data.get("favorite"), data.get("following") or [])

    def save(self, favorite: Optional[str], following: List[str]) -> dict:
        prefs = self._normalize(favorite, following)
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(prefs, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        return prefs

    @staticmethod
    def _normalize(favorite: Optional[str], following: List[str]) -> dict:
        fav = (favorite or "").strip() or None
        seen, clean = set(), []
        for name in following:
            name = (name or "").strip()
            key = name.casefold()
            # drop blanks, duplicates, and the favorite (can't follow your fav)
            if not name or key in seen or (fav and key == fav.casefold()):
                continue
            seen.add(key)
            clean.append(name)
        return {"favorite": fav, "following": clean}
