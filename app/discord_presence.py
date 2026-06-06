"""Headless Discord Rich Presence over the gateway using a user token.

NOTE: driving a *user* account programmatically (a "self-bot") violates Discord's
Terms of Service. This is the only way to show presence on your own profile without
a running Discord client. Use at your own risk; see README.
"""
import asyncio
import json
import logging

import aiohttp

log = logging.getLogger("discord")

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
REST = "https://discord.com/api/v9"

# Op codes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_PRESENCE = 3
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11


class DiscordPresence:
    def __init__(self, token, app_id, session: aiohttp.ClientSession):
        self.token = token
        self.app_id = app_id
        self.s = session
        self.ws = None
        self.seq = None
        self._desired = None          # latest activity dict (or None to clear)
        self._sent = "__force__"      # last transmitted payload key (dedupe)
        self._ext_cache = {}          # image url -> "mp:external/..." path

    # ----- public API -----
    async def set_activity(self, activity):
        self._desired = activity
        if self.ws is not None and not self.ws.closed:
            await self._flush()

    async def external_asset(self, image_url):
        """Turn an arbitrary (public) image URL into a Discord proxied asset path."""
        if not image_url:
            return None
        if image_url in self._ext_cache:
            return self._ext_cache[image_url]
        url = f"{REST}/applications/{self.app_id}/external-assets"
        try:
            async with self.s.post(
                url,
                headers={"Authorization": self.token},
                json={"urls": [image_url]},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    log.warning("external-assets HTTP %s: %s", r.status, await r.text())
                    return None
                data = await r.json()
            path = "mp:" + data[0]["external_asset_path"]
            if len(self._ext_cache) > 500:
                self._ext_cache.clear()
            self._ext_cache[image_url] = path
            return path
        except Exception as e:  # noqa: BLE001
            log.warning("external-assets failed: %s", e)
            return None

    # ----- gateway lifecycle -----
    async def run_forever(self):
        backoff = 1
        while True:
            try:
                await self._connect()
                backoff = 1
            except Exception as e:  # noqa: BLE001
                log.warning("gateway error: %s (reconnect in %ss)", e, backoff)
            self.ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _connect(self):
        async with self.s.ws_connect(
            GATEWAY, heartbeat=None, timeout=aiohttp.ClientTimeout(total=30)
        ) as ws:
            self.ws = ws
            self._sent = "__force__"  # force a resend on the fresh session
            hello = await ws.receive_json()
            interval = hello["d"]["heartbeat_interval"] / 1000.0
            hb = asyncio.create_task(self._heartbeat(interval))
            try:
                await self._identify()
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._on_message(json.loads(msg.data))
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
            finally:
                hb.cancel()

    async def _heartbeat(self, interval):
        try:
            while True:
                await asyncio.sleep(interval)
                if self.ws and not self.ws.closed:
                    await self.ws.send_json({"op": OP_HEARTBEAT, "d": self.seq})
        except asyncio.CancelledError:
            pass

    async def _identify(self):
        await self.ws.send_json({
            "op": OP_IDENTIFY,
            "d": {
                "token": self.token,
                "capabilities": 30717,
                "properties": {
                    "os": "Linux",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "en-US",
                    "browser_user_agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "browser_version": "120.0.0.0",
                    "os_version": "",
                    "referrer": "",
                    "referring_domain": "",
                    "release_channel": "stable",
                    "client_build_number": 9999,
                },
                "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                "compress": False,
            },
        })

    async def _on_message(self, data):
        if data.get("s") is not None:
            self.seq = data["s"]
        op = data.get("op")
        if op == OP_DISPATCH:
            if data.get("t") == "READY":
                user = data["d"].get("user", {})
                log.info("gateway READY (logged in as %s)", user.get("username"))
                await self._flush()
        elif op == OP_HEARTBEAT:
            await self.ws.send_json({"op": OP_HEARTBEAT, "d": self.seq})
        elif op == OP_RECONNECT:
            log.info("gateway requested reconnect")
            await self.ws.close()
        elif op == OP_INVALID_SESSION:
            log.warning("invalid session (check that DISCORD_USER_TOKEN is valid)")
            await self.ws.close()
        elif op == OP_HEARTBEAT_ACK:
            pass

    # ----- internals -----
    async def _flush(self):
        key = json.dumps(self._desired, sort_keys=True) if self._desired else None
        if key == self._sent:
            return
        await self.ws.send_json({
            "op": OP_PRESENCE,
            "d": {
                "since": 0,
                "activities": [self._desired] if self._desired else [],
                "status": "online",
                "afk": False,
            },
        })
        self._sent = key
        log.info("presence -> %s", self._desired.get("details") if self._desired else "(cleared)")
