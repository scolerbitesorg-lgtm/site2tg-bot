# Reliability & security hardening

This maintenance branch keeps the existing Telegram bot, adapter format, state file,
and Vercel webhook architecture. It adds destination validation to the actual outbound
HTTP request paths, including redirects, so a configured URL cannot trivially point at
localhost, a private network, or cloud metadata IPs.

## Scheduling
The GitHub Actions schedule runs every 30 minutes at :17 and :47. GitHub's scheduler is
best-effort (on 2026-10-28 a */10 schedule ran twice in 11 hours), so an optional outside
pinger can call the Vercel `/api/tick?key=TICK_KEY` endpoint, which starts a run only when
none is queued, running, or started in the last 10 minutes. The repository is public, so
standard-runner minutes are free. Every state commit is a Vercel deployment event; the
`ignoreCommand` in vercel.json skips the build for `state: update` commits, but Vercel's
Hobby plan still counts them toward its 100 deployments/day, so keep the schedule at
15 minutes or slower.

## Safe URL handling
- Only HTTP(S) URLs without embedded username/password credentials are accepted.
- Local hostnames and non-public IP addresses are rejected.
- DNS answers are checked before requests; every redirect destination is checked too.
- Downloads are streamed, declared and actual size are bounded, and HTML error pages
  are rejected as files.
- These checks are defence-in-depth, not a substitute for network egress controls.

## Supported media
The bot supports direct downloadable files and the existing video-catalog adapter.
YouTube is link-only: watch links for single videos, public playlists/channels, and
videos embedded on added websites are posted; no YouTube media is downloaded.
HLS/m3u8/DASH streams, stream-to-mp4 conversion, yt-dlp, DRM, logins and paid-course
extractors are out of scope for this bot and are not planned. For a site that yields
nothing (a JavaScript-rendered app, a stream player, a login wall) the bot records a
plain-language reason shown in /status and /sites.

## Tests
Run locally with Python 3.12 and Node 20+:
```bash
python -m pip install -r requirements.txt
python -m pytest -q
node --test tests/webhook.test.js
```
