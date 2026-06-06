"""Headless Discord Rich Presence over the gateway using a user token.

NOTE: driving a *user* account programmatically (a "self-bot") violates Discord's
Terms of Service. This is the only way to show presence on your own profile without
a running Discord client. Use at your own risk; see README.
"""
import asyncio
import json
import logging
import random

import aiohttp

log = logging.getLogger("discord")

GATEWAY = "wss://gateway.discord.gg/?v=9&encoding=json"
REST = "https://discord.com/api/v9"

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_PRESENCE = 3
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Gateway close codes that won't be fixed by reconnecting with the same token.
FATAL_CLOSE = {4004, 4010, 4011, 4012, 4013, 4014}


class DiscordPresence:
    def __init__(self, token, app_id, session: aiohttp.ClientSession):
        self.token = token
        self.app_id = app_id
        self.s = session
        self.ws = None
        self.seq = None
        self.session_id = None
        self.resume_url = None
        self.ready = False
        self._acked = True
        self._desired = None        # latest activity dict (or None to clear)
        self._sent = None           # last transmitted payload key (dedupe)
        self._ext_cache = {}        # image url -> "mp:external/..." path
        self._next_wait = 5

    # ----- public API -----
    async def set_activity(self, activity):
        self._desired = activity
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
        while True:
            url = self.resume_url or GATEWAY
            self._next_wait = 5
            try:
                await self._connect_once(url)
            except Exception as e:  # noqa: BLE001
                log.warning("gateway error: %s", e)
            self.ws = None
            self.ready = False
            await asyncio.sleep(self._next_wait)

    async def _connect_once(self, url):
        async with self.s.ws_connect(
            url, heartbeat=None, timeout=aiohttp.ClientTimeout(total=30)
        ) as ws:
            self.ws = ws
            self._acked = True
            hello = await ws.receive_json()
            if hello.get("op") != OP_HELLO:
                log.warning("expected HELLO, got op %s", hello.get("op"))
                return
            interval = hello["d"]["heartbeat_interval"] / 1000.0
            hb = asyncio.create_task(self._heartbeat(interval))
            try:
                if self.session_id and self.seq is not None:
                    log.info("resuming session")
                    await ws.send_json({
                        "op": OP_RESUME,
                        "d": {"token": self.token, "session_id": self.session_id, "seq": self.seq},
                    })
                else:
                    log.info("identifying")
                    await self._identify()

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if await self._on_message(json.loads(msg.data)):
                            break
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

                code = ws.close_code
                if code is not None:
                    if code in FATAL_CLOSE:
                        log.error("fatal gateway close %s — clearing session "
                                  "(4004 = the DISCORD_USER_TOKEN is invalid/expired)", code)
                        self.session_id = None
                        self.seq = None
                        self._next_wait = 30
                    else:
                        log.info("gateway closed (code=%s); will resume", code)
                        self._next_wait = 2
            finally:
                hb.cancel()

    async def _heartbeat(self, interval):
        try:
            await asyncio.sleep(interval * random.random())  # jittered first beat
            while True:
                if not self._acked:
                    log.info("heartbeat not acked; dropping connection to reconnect")
                    if self.ws and not self.ws.closed:
                        await self.ws.close(code=4000)
                    return
                self._acked = False
                if self.ws and not self.ws.closed:
                    await self.ws.send_json({"op": OP_HEARTBEAT, "d": self.seq})
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _identify(self):
        await self.ws.send_json({
            "op": OP_IDENTIFY,
            "d": {
                "token": self.token,
                "capabilities": 30717,
                "properties": {
                    "os": "Windows",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "en-US",
                    "browser_user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    ),
                    "browser_version": "130.0.0.0",
                    "os_version": "10",
                    "referrer": "",
                    "referring_domain": "",
                    "referrer_current": "",
                    "referring_domain_current": "",
                    "release_channel": "stable",
                    "client_build_number": 369402,
                    "client_event_source": None,
                },
                "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                "compress": False,
                "client_state": {
                    "guild_versions": {},
                    "highest_last_message_id": "0",
                    "read_state_version": 0,
                    "user_guild_settings_version": -1,
                    "user_settings_version": -1,
                    "private_channels_version": "0",
                    "api_code_version": 0,
                },
            },
        })

    async def _on_message(self, data):
        """Return True to break the read loop (so the connection is re-established)."""
        if data.get("s") is not None:
            self.seq = data["s"]
        op = data.get("op")

        if op == OP_DISPATCH:
            t = data.get("t")
            if t == "READY":
                d = data["d"]
                self.session_id = d.get("session_id")
                ru = d.get("resume_gateway_url")
                self.resume_url = (ru + "/?v=9&encoding=json") if ru else None
                self.ready = True
                self._sent = None  # force a resend on the fresh session
                log.info("gateway READY (logged in as %s)", d.get("user", {}).get("username"))
                await self._flush()
            elif t == "RESUMED":
                self.ready = True
                self._sent = None
                log.info("gateway RESUMED")
                await self._flush()
        elif op == OP_HEARTBEAT:
            if self.ws and not self.ws.closed:
                await self.ws.send_json({"op": OP_HEARTBEAT, "d": self.seq})
        elif op == OP_RECONNECT:
            log.info("server requested reconnect; will resume")
            self._next_wait = 2
            return True
        elif op == OP_INVALID_SESSION:
            resumable = bool(data.get("d"))
            log.warning("invalid session (resumable=%s)", resumable)
            if not resumable:
                self.session_id = None
                self.seq = None
            self._next_wait = random.uniform(1.5, 5.0)  # Discord requires a 1-5s wait
            return True
        elif op == OP_HEARTBEAT_ACK:
            self._acked = True
        return False

    # ----- internals -----
    async def _flush(self):
        if not (self.ready and self.ws and not self.ws.closed):
            return  # only send once the session is actually live
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
