# jellyfin-discord-presence

Headless Discord **Rich Presence** for Jellyfin. Polls your Jellyfin server's API and
mirrors what *you* are watching/listening to onto *your* Discord profile — 24/7, with
**no Discord client running anywhere** and nothing installed on your PC. Supports
per-**library** and per-**media-type** exclusions.

It runs as a single small Docker container (e.g. on Unraid).

---

## ⚠️ Read this first — it uses a self-bot (against Discord ToS)

Showing presence on **your own** profile with no Discord client is *only* possible by
driving your account with your **user token** (a "self-bot"). This **violates Discord's
Terms of Service.** Presence-only self-bots have run for years for many people, but
Discord does occasional ban waves — it is a small, real, non-zero risk to your **main**
account (it has to be your main, since that's whose profile shows).

- Your user token = **full access to your account.** Treat it like a password. It lives
  only in `.env` (git-ignored) / your container's env. Never share or commit it.
- The token **silently rotates** whenever you change your Discord password.

A ToS-clean (but not headless) alternative is [Radiicall/jellyfin-rpc](https://github.com/Radiicall/jellyfin-rpc)
run next to a normal Discord client. This project deliberately trades that for "always on".

---

## What you need to collect

### 1. Jellyfin API key
Jellyfin **Dashboard → API Keys → +**. Copy it into `JELLYFIN_API_KEY`.
Set `JELLYFIN_URL` to the address the container can reach (e.g. `http://192.168.1.10:8096`),
and `JELLYFIN_USERNAME` to the account whose playback you want shown.

### 2. Discord application (for the name + images)
[Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
- Copy **Application ID** → `DISCORD_APP_ID`.
- **Rich Presence → Art Assets**: upload a large image named `jellyfin` (matches the
  default `STATIC_LARGE_IMAGE`). Optionally upload `playing` / `paused` small badges and
  set `SMALL_IMAGE_PLAYING` / `SMALL_IMAGE_PAUSED`.

### 3. Your Discord user token (the secret)
1. Open **discord.com/app in a browser** (not the desktop app) and log in.
2. **F12 → Network** tab. Filter for `science` (or click anything that fires a request).
3. Click a request to `discord.com/api/...` → **Headers → Request Headers** → copy the
   value of **`authorization`**.
4. Paste into `DISCORD_USER_TOKEN`. Keep it secret.

### 4. (Optional) Poster art
To show the actual poster/cover instead of the static logo, set `JELLYFIN_PUBLIC_URL` to
a **public, HTTPS** URL of your Jellyfin (e.g. your reverse-proxy domain). Discord's image
proxy must be able to reach it. Jellyfin's `/Images/Primary` endpoint is public (no key),
so only the artwork is exposed. Leave blank for LAN-only setups → the static logo is used.

---

## Configure & run

```bash
cp .env.example .env      # then edit .env with the values above
docker compose up -d      # pulls ghcr.io/johagan94/jellyfin-discord-presence
docker compose logs -f    # watch for "gateway READY (logged in as ...)"
```

When you start playing something in Jellyfin you should see a
`presence -> <title>` log line, and the status appears on your Discord profile within a
poll interval (~15 s).

### On Unraid
The image is published to **GHCR** by CI (`.github/workflows/docker-publish.yml`):
`ghcr.io/johagan94/jellyfin-discord-presence:latest` (make the package **public** once, under
the repo's Packages settings, so Unraid can pull it without credentials).

Docker tab → **Add Container**, set **Repository** to
`ghcr.io/johagan94/jellyfin-discord-presence:latest`, and add each variable from
`.env.example` as a Key/Value. No ports or volumes — it only makes outbound connections.
To update later, just hit **Force Update** (CI keeps `:latest` current).

---

## Exclusions

| Variable | Example | Effect |
| --- | --- | --- |
| `EXCLUDE_LIBRARIES` | `Anime,Home Videos` | Hide anything in those libraries (names exactly as shown in Jellyfin). |
| `EXCLUDE_MEDIA_TYPES` | `music,livetv` | Hide whole categories. Accepts `movie, episode (tv/shows), music (audio), musicvideo, livetv, book, trailer`. |

When the current item is excluded (or nothing is playing, or paused with
`SHOW_PAUSED=false`), the presence is cleared.

---

## Troubleshooting

- **`fatal gateway close 4004`** → the `DISCORD_USER_TOKEN` is wrong or expired (e.g. you
  changed your password). Re-grab it.
- **`invalid session (resumable=...)` occasionally** is normal — the client waits 1–5s and
  resumes/re-identifies. A healthy run logs `gateway READY` once and then stays quiet. If
  you *never* see `gateway READY` and it loops, Discord client internals may have shifted;
  bump `client_build_number` in `app/discord_presence.py`.
- **Status shows but no image** → check `STATIC_LARGE_IMAGE` matches an uploaded Art Asset
  key; for poster art confirm `JELLYFIN_PUBLIC_URL` is HTTPS and reachable from the
  public internet.
- **Wrong/no playback detected** → confirm `JELLYFIN_USERNAME` matches exactly and the API
  key is admin-scoped (needed to read `/Sessions`).

## How it works

`app/main.py` polls `GET /Sessions`, finds your user's `NowPlayingItem`, applies
exclusions, and builds an activity object. `app/discord_presence.py` holds one gateway
connection (IDENTIFY + heartbeat) using your token and sends Presence Update (op 3)
whenever the activity changes. Poster art is proxied via Discord's `external-assets`
endpoint.
