"""Poll Jellyfin for the target user's playback and mirror it to Discord presence."""
import asyncio
import logging
import time

import aiohttp

from .config import Config
from .discord_presence import DiscordPresence
from .jellyfin import Jellyfin, normalize_excluded_types

log = logging.getLogger("main")


def _clip(s, n=128):
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _text_for(item):
    """Return (details, state) lines for the activity card."""
    t = (item.get("Type") or "").lower()
    name = item.get("Name") or "Unknown"
    if t == "episode":
        series = item.get("SeriesName") or name
        season = item.get("ParentIndexNumber")
        ep = item.get("IndexNumber")
        tag = ""
        if season is not None and ep is not None:
            tag = f"S{int(season):02d}E{int(ep):02d} · "
        return series, f"{tag}{name}"
    if t == "movie":
        year = item.get("ProductionYear")
        return (f"{name} ({year})" if year else name), "Movie"
    if t == "audio":
        artists = ", ".join(item.get("Artists") or []) or (item.get("AlbumArtist") or "")
        album = item.get("Album") or ""
        sub = " — ".join([x for x in (artists, album) if x]) or "Music"
        return name, sub
    return name, (item.get("Type") or "Jellyfin")


def _image_item_id(item):
    t = (item.get("Type") or "").lower()
    if t == "episode":
        return item.get("SeriesId") or item.get("Id")
    if t == "audio":
        return item.get("AlbumId") or item.get("Id")
    return item.get("Id")


def _prune(d):
    return {k: v for k, v in d.items() if v not in (None, "", {})}


def build_activity(cfg, item, playstate, large_image, small_image, small_text):
    item_type = (item.get("Type") or "").lower()
    media_type = (item.get("MediaType") or "").lower()
    # 2 = Listening, 3 = Watching
    atype = 2 if media_type == "audio" or item_type in ("audio", "musicalbum") else 3

    details, state = _text_for(item)
    assets = _prune({
        "large_image": large_image,
        "large_text": _clip(item.get("Name") or cfg.activity_name),
        "small_image": small_image,
        "small_text": _clip(small_text),
    })

    activity = {
        "name": cfg.activity_name,
        "type": atype,
        "application_id": cfg.discord_app_id,
        "details": _clip(details),
        "state": _clip(state),
        "assets": assets,
    }

    if not playstate.get("IsPaused"):
        run = item.get("RunTimeTicks") or 0
        pos = playstate.get("PositionTicks") or 0
        if run > 0:
            now_ms = int(time.time() * 1000)
            start = now_ms - pos // 10000  # ticks are 100ns -> ms = ticks / 10000
            activity["timestamps"] = {"start": start, "end": start + run // 10000}

    return _prune(activity)


async def compute_activity(cfg, jf, dp, excluded_types, target_name, target_id):
    sessions = await jf.get_sessions()

    sess = None
    for s in sessions:
        if not s.get("NowPlayingItem"):
            continue
        if target_id and s.get("UserId") == target_id:
            sess = s
            break
        if target_name and (s.get("UserName") or "").lower() == target_name:
            sess = s
            break
    if not sess:
        return None  # nothing playing -> clear presence

    item = sess["NowPlayingItem"]
    playstate = sess.get("PlayState") or {}

    if (item.get("Type") or "").lower() in excluded_types:
        return None
    if (item.get("MediaType") or "").lower() in excluded_types:
        return None

    if cfg.exclude_libraries:
        lib = await jf.library_of(item.get("Id"), sess.get("UserId"))
        if lib and lib in cfg.exclude_libraries:
            log.debug("excluded by library: %s", lib)
            return None

    if playstate.get("IsPaused") and not cfg.show_paused:
        return None

    # Poster art (only if a public, Discord-reachable URL is configured)
    large_image = None
    if cfg.jellyfin_public_url:
        img_id = _image_item_id(item)
        if img_id:
            poster = f"{cfg.jellyfin_public_url}/Items/{img_id}/Images/Primary?fillHeight=512&quality=90"
            large_image = await dp.external_asset(poster)
    if not large_image:
        large_image = cfg.static_large_image or None

    if playstate.get("IsPaused"):
        small_image, small_text = (cfg.small_image_paused or None), "Paused"
    else:
        small_image, small_text = (cfg.small_image_playing or None), "Playing"

    return build_activity(cfg, item, playstate, large_image, small_image, small_text)


async def poll_loop(cfg, jf, dp, excluded_types):
    target_name = cfg.jellyfin_username.lower()
    target_id = cfg.jellyfin_user_id
    while True:
        try:
            activity = await compute_activity(cfg, jf, dp, excluded_types, target_name, target_id)
            await dp.set_activity(activity)
        except Exception as e:  # noqa: BLE001
            log.warning("poll error: %s", e)
        await asyncio.sleep(cfg.poll_interval)


async def amain():
    cfg = Config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    excluded_types = normalize_excluded_types(cfg.exclude_media_types)
    log.info("watching Jellyfin user '%s'; excluding libraries=%s types=%s",
             cfg.jellyfin_username or cfg.jellyfin_user_id,
             cfg.exclude_libraries or "-", sorted(excluded_types) or "-")

    async with aiohttp.ClientSession() as session:
        jf = Jellyfin(cfg.jellyfin_url, cfg.jellyfin_api_key, session)
        dp = DiscordPresence(cfg.discord_token, cfg.discord_app_id, session)
        await asyncio.gather(dp.run_forever(), poll_loop(cfg, jf, dp, excluded_types))


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
