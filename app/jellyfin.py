"""Thin async Jellyfin API client: read sessions and resolve an item's library."""
import logging

import aiohttp

log = logging.getLogger("jellyfin")

# Friendly alias -> set of Jellyfin item "Type" values (all lower-cased).
_TYPE_ALIASES = {
    "movie": {"movie"},
    "movies": {"movie"},
    "episode": {"episode"},
    "episodes": {"episode"},
    "tv": {"episode"},
    "show": {"episode"},
    "shows": {"episode"},
    "series": {"episode"},
    "audio": {"audio"},
    "music": {"audio"},
    "song": {"audio"},
    "songs": {"audio"},
    "musicvideo": {"musicvideo"},
    "livetv": {"tvchannel", "livetvchannel", "channel"},
    "live tv": {"tvchannel", "livetvchannel", "channel"},
    "book": {"book", "audiobook"},
    "audiobook": {"audiobook"},
    "trailer": {"trailer"},
    "video": {"video"},
}


def normalize_excluded_types(values):
    """Map friendly names to Jellyfin item Type values; pass unknowns through raw."""
    out = set()
    for v in values:
        key = v.lower().strip()
        if key in _TYPE_ALIASES:
            out |= _TYPE_ALIASES[key]
        else:
            out.add(key)
    return out


class Jellyfin:
    def __init__(self, base_url, api_key, session: aiohttp.ClientSession):
        self.base = base_url
        self.api_key = api_key
        self.s = session
        self._lib_cache = {}  # item_id -> library name (lower) or None

    def _headers(self):
        return {"Authorization": f'MediaBrowser Token="{self.api_key}"'}

    async def get_sessions(self):
        url = f"{self.base}/Sessions"
        async with self.s.get(
            url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)
        ) as r:
            r.raise_for_status()
            return await r.json()

    async def library_of(self, item_id, user_id=None):
        """Return the lower-cased name of the CollectionFolder (library) an item lives in."""
        if not item_id:
            return None
        if item_id in self._lib_cache:
            return self._lib_cache[item_id]

        url = f"{self.base}/Items/{item_id}/Ancestors"
        params = {"userId": user_id} if user_id else None
        name = None
        try:
            async with self.s.get(
                url, headers=self._headers(), params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                r.raise_for_status()
                ancestors = await r.json()
            for a in ancestors:
                if a.get("Type") == "CollectionFolder":
                    name = (a.get("Name") or "").lower()
                    break
        except Exception as e:  # noqa: BLE001 - non-fatal, just skip the exclusion check
            log.warning("Ancestors lookup failed for %s: %s", item_id, e)

        if len(self._lib_cache) > 1000:
            self._lib_cache.clear()
        self._lib_cache[item_id] = name
        return name
