# Reliability & security hardening

This maintenance branch keeps the existing Telegram bot, adapter format, state file,
and Vercel webhook architecture. It adds destination validation to the actual outbound
HTTP request paths, including redirects, so a configured URL cannot trivially point at
localhost, a private network, or cloud metadata IPs.

## Scheduling
The GitHub Actions schedule is set to every 10 minutes. GitHub can delay cron jobs during
busy periods, and scheduled workflows run from the repository's default branch only after
the changes are merged there. Keep an eye on Actions minutes: total usage depends on the
duration of each run and the account's quota.

## Safe URL handling
- Only HTTP(S) URLs without embedded username/password credentials are accepted.
- Local hostnames and non-public IP addresses are rejected.
- DNS answers are checked before requests; every redirect destination is checked too.
- Downloads are streamed, declared and actual size are bounded, and HTML error pages
  are rejected as files.
- These checks are defence-in-depth, not a substitute for network egress controls.

## Supported media
The bot supports direct downloadable files and the existing video-catalog adapter.
It does not decrypt DRM-protected media, extract keys, or bypass access controls.
An HLS playlist should only be added as a future feature for unencrypted streams that
the operator is authorized to download, with an explicit domain allowlist and strict
segment/size limits.

## Tests
Run locally with Python 3.12:
```bash
python -m pip install -r requirements.txt
python -m pytest -q
```
