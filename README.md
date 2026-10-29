# site2tg-bot 🤖

Aapki **apni websites** se files (videos, APK, PDF, zip…) download karke aapke **private Telegram channel** mein daal deta hai, backup ki tarah. YouTube videos ka sirf **watch link** post karta hai (video download nahi).
Sab free servers pe chalta hai (GitHub Actions + Vercel). **Phone ka data/storage use nahi hota, laptop nahi chahiye.**

## Kya karta hai

- **GitHub Actions** asli kaam karta hai: website padhna, download, Telegram pe upload. Har **30 min** khud sync karta hai (GitHub kabhi-kabhi late karta hai ya run chhod deta hai — neeche "Auto-sync pakka karna" dekho).
- **Vercel webhook**: bot hamesha online. `/status`, `/sites`, `/youtubes`, `/menu`, `/help` ka jawab **turant**; add/remove/sync/get pe turant "⏳" aur GitHub run usi second start.
- Jo file ek baar bhej di, wo dobara nahi jaati (`state.json` yaad rakhta hai). Same file do links pe ho, ya same site do tarah se likhi ho (`site.com`, `https://www.site.com/`), tab bhi ek hi baar.

### Website types
1. **Video catalog site** (jaise https://videoclasses.vercel.app/) — bot khud pehchaanta hai. Folders kitne bhi andar hon (Course → Topic → Subject → Lecture → videos), sab milte hain. Caption: `Course · Topic · Subject · Lecture · Title`.
2. **Normal website** — page pe jitne seedhe file links hain (`.mp4 .mkv .apk .pdf .zip .mp3 .epub …`) sab bhejta hai.
   - **Andar ke pages bhi** (default 5 level): usi site ke links kholta hai. Jis page pe files mil gayi, us raaste mein aage nahi jaata. Ek sync mein max 60 pages, `robots.txt` maanta hai, login/cart/admin pages skip.
   - Jo page diya uske **folder ke andar** ke pages dekhta hai. Agar wo page sirf ek list hai jiske lectures dusre folder mein hain (jaise examhint: `/p/7/...` → `/video-lectures/...`), toh page ke **main content** ke links kholta hai (upar/neeche ke menu ke links nahi).
   - Page pe **YouTube video embed** ho toh uska **watch link** channel mein jaata hai (har sync mein kuch, ek-ek karke). Video download nahi hoti.
   - `/addsite <url> <limit> <depth>` — depth 0-5 (0 = sirf wahi page).

### Kab 0 files aati hain (aur bot batata hai kyun)
`/status` aur `/sites` mein har site ke saath "⚠️ 0 kyun: …" dikhta hai:
- **JavaScript app site** (page khulne ke baad list JS se aati hai, HTML mein link nahi): bot nahi padh sakta. Jaise `spidyiq.vercel.app`.
- **Stream (m3u8/HLS)** wali videos: bot streams download/convert **nahi** karta. Ye pakki limit hai.
- **Login ke peeche** content: bot login nahi karta.
- Ya bas kisi page pe file link / YouTube video nahi mila.

## Commands

| Command | Kaam |
|---|---|
| `/addsite <url> [limit] [depth]` | website jodo. limit = ek sync mein max nayi files (default 3), depth = andar ke pages 0-5 (default 5). YouTube link doge toh wo YouTube tracker mein chala jaata hai |
| `/removesite <url>` | website hatao |
| `/sites` | saari websites, kitni files gayi, YouTube links, 0 kyun |
| `/sync` | abhi sync karo |
| `/retry` | jo files 3 baar fail hui, unhe dobara |
| `/get <link>` | ek seedha file link (`…/video.mp4`, `…/app.apk`, `…/notes.pdf`) turant channel mein |
| `/yt <video link>` | ek YouTube video ka watch link channel mein (download nahi) |
| `/addplaylist <playlist link>` | playlist ki saari videos ke links, har sync mein kuch, ek-ek karke |
| `/addyoutube <channel link ya @naam>` | channel ki latest 3 videos ke link, phir har nayi video ka link |
| `/youtubes` | kaunse playlist/channel track ho rahe hain, kitne post hue, kitne line mein |
| `/removeyoutube <link/ID>` | YouTube tracker hatao |
| `/status` | files kitni gayi, last sync, GitHub runs, errors, 0 kyun |
| `/menu` | buttons wala menu (Vercel ke saath) |
| `/ai <sawal>` | AI se poocho (Vercel + NVIDIA key). Ya seedha koi bhi sawal likh do |
| `/id` | aapka OWNER_ID |
| `/help` | saare commands |

**Menu buttons** (`/menu`): 📊 Status · 🌐 Sites · 🔄 Sync now · 🔁 Retry · 📥 Download file link · ➕ Add website · 🗑 Remove website · 📺 Add playlist · ▶️ Track channel · 📋 YouTube trackers · 🗑 Remove YouTube tracker · 🔗 Post YouTube link · 🤖 Ask AI · ❓ Help.
Button dabane pe bot link maangta hai: **us message ka reply karke** link bhejo.

Koi link **bina command** ke bhej diya toh bot bata deta hai kaunsa command lagega (YouTube → `/yt` / `/addplaylist` / `/addyoutube`, file → `/get`, website → `/addsite`).

⏱ Asli test (28 Oct): command ke ~1 sec mein GitHub run bana, ~5 sec mein shuru, ~18 sec mein jawab. Download wale kaam file size pe depend karte hain. Ek run chal raha ho toh agla uske baad (koi command khota nahi).

Sirf aapke (OWNER_ID) commands maane jaate hain.

---

## Setup (sirf phone se)

### 1. Bot aur channel
1. Telegram → **@BotFather** → `/newbot` → naam + username (`bot` pe khatam) → **token** milega. Kisi ko mat bhejna.
2. Private channel banao → Administrators → apna bot add karo (**Post Messages** on).
3. (Optional) Videos aur files alag chahiye toh do channels banao, dono mein bot admin.

### 2. GitHub Secrets
Phone browser (GitHub login): https://github.com/scolerbitesorg-lgtm/site2tg-bot/settings/secrets/actions → **New repository secret**. (Settings na dikhe toh browser menu → "Desktop site".)

| Secret | Value |
|---|---|
| `BOT_TOKEN` | BotFather wala token |
| `OWNER_ID` | aapka Telegram user id (sirf number). Pata nahi? Bot ko `/start` bhejo aur Actions → site2tg-bot → **Run workflow** — bot bata dega. Ya **@userinfobot** |
| `CHANNEL_ID` | channel id (`-100…`). Channel ki koi post bot ko forward karke Run workflow → bot bata dega |
| `CHANNEL_ID_VIDEO` | *(optional)* video channel id |
| `CHANNEL_ID_FILES` | *(optional)* files channel id |
| `API_ID`, `API_HASH`, `SESSION_STRING` | *(optional)* 50 MB se badi files ke liye, neeche dekho |

Phir https://github.com/scolerbitesorg-lgtm/site2tg-bot/actions → "enable workflows" dikhe toh dabao → **site2tg-bot → Run workflow**.

### 3. Vercel (bot hamesha online)
**A. GitHub token (sirf is repo ke liye):** https://github.com/settings/personal-access-tokens/new
- Name: `site2tg-vercel` · Expiration: jitna lamba chaho
- Repository access → **Only select repositories** → `site2tg-bot`
- Repository permissions: **Actions → Read and write**, **Contents → Read-only** (bas ye do)
- **Generate token** → `github_pat_…` copy karo (dobara nahi dikhega)

**B. WEBHOOK_SECRET:** khud ek 20+ letters ka random word banao, sirf `A-Z a-z 0-9 _ -`. Jaise `meraBot_x7Kq92LmPz04Ty`.

**C. Deploy:** https://vercel.com/new → `site2tg-bot` **Import** → Framework: **Other** (build settings mat chhedo) → **Environment Variables**:

| Name | Value |
|---|---|
| `BOT_TOKEN` | BotFather wala token |
| `OWNER_ID` | aapka user id |
| `GH_TOKEN` | step A ka `github_pat_…` |
| `GH_REPO` | `scolerbitesorg-lgtm/site2tg-bot` |
| `WEBHOOK_SECRET` | step B ka word |
| `NVIDIA_API_KEY` | *(optional, AI)* build.nvidia.com → Get API Key (`nvapi-…`) |
| `NVIDIA_MODEL` | *(optional)* default `openai/gpt-oss-20b` |
| `TICK_KEY` | *(optional)* auto-sync pinger ki key, neeche dekho |

→ **Deploy**.

**D. Webhook chalu:** Project → **Domains** se chhota domain lo (jaise `site2tg-bot.vercel.app`; lamba random wala deployment link nahi). Browser mein kholo:
```
https://<domain>/api/setup?key=<WEBHOOK_SECRET>
```
"✅ Webhook set ho gaya!" aana chahiye → bot ko `/menu` bhejo 🎉

- Webhook ka haal: `…/api/setup?key=<WEBHOOK_SECRET>&action=info`
- Wapas sirf-GitHub mode: `…&action=delete`
- Env var missing hai kya: `https://<domain>/api/telegram` kholo

⚠️ **Vercel mein koi env var badla/joda toh Redeploy zaroori:** Deployments → sabse upar wala → ⋯ → **Redeploy**. Agar wahan "Use project's Ignore Build Step" ka tick dikhe toh **hata do**, warna redeploy cancel ho sakta hai.

Vercel pe sirf `api/`, `lib/`, `public/` jaate hain. Bot ke `state.json` commits pe Vercel build nahi karta (`vercel.json` ka ignoreCommand), par Vercel free plan **100 deployments/din** gin-ta hai (skip hue bhi). 30 min wale schedule pe ye limit ke andar rehta hai; schedule 15 min se tez mat karna.

### 4. Auto-sync pakka karna (optional, free)
GitHub ka schedule "best effort" hai: 28 Oct ko 10-min schedule 11 ghante mein sirf 2 baar chala. Har 30 min pakka sync chahiye toh:
1. Vercel env mein `TICK_KEY` = ek naya random word (16+ letters, WEBHOOK_SECRET se alag) → **Redeploy**
2. https://cron-job.org pe free account (phone browser) → **Create cronjob**
3. URL: `https://<domain>/api/tick?key=<TICK_KEY>` · Schedule: **every 30 minutes** → Save
Bot pehle se chal raha ho ya 10 min ke andar chala ho toh tick kuch nahi karta (double run nahi).

### 5. AI (optional, NVIDIA free)
build.nvidia.com → login → koi chat model (jaise `openai/gpt-oss-20b`) → **Get API Key** → Vercel env `NVIDIA_API_KEY` → Redeploy. Bot ko koi bhi sawal likho: "kitni files gayi?", "examhint se kya aaya?". AI ko sirf bot ka live status jaata hai (koi secret nahi), aur wo khud kuch add/delete nahi karta, bas command batata hai.

### 6. Badi files (50 MB se upar, optional)
Telegram bot sirf 50 MB tak bhej sakta hai; badi files aapke apne account se jaati hain (2 GB tak). Secrets: `API_ID`, `API_HASH` (https://my.telegram.org → API development tools) aur `SESSION_STRING`:
1. **F-Droid** se Termux → `pkg install python -y` → `pip install telethon`
2. `nano gen_session.py` → [`scripts/gen_session.py`](scripts/gen_session.py) ka code paste → save → `python gen_session.py`
3. API_ID, API_HASH, number (+91), Telegram code daalo → string Saved Messages mein aayegi → `SESSION_STRING` secret
⚠️ SESSION_STRING aapke Telegram account ki poori chaabi hai. Kisi ko mat do, kisi "generator" bot/website pe mat banao.

---

## Settings (GitHub → Settings → Secrets and variables → Actions → **Variables**)
- `SYNC_EVERY_MIN` — do sync ke beech kam se kam kitne minute (default `25`, schedule 30 min)
- `MAX_FILES_PER_RUN` — ek run mein max files, saari sites mila ke (default `15`)
- `PARALLEL_DOWNLOADS` — ek saath kitne downloads (default `4`); upload line se hota hai
- `MAX_YOUTUBE_LINKS_PER_RUN` — har playlist/channel/site se ek run mein max YouTube links (default `5`)
- `WEBHOOK_MODE` — `1`/`0` zabardasti; khali = bot khud pata karta hai
- Schedule badalna: `.github/workflows/bot.yml` mein `cron: "17,47 * * * *"`

Repo **public** hai, isliye GitHub Actions ke minutes free hain (ek run max 6 ghante). Public mein code, `state.json` (sites ki list) aur run logs sab dekh sakte hain; **secrets kabhi nahi dikhte**.

## Safety aur limits (pakki)
- Token/keys sirf GitHub Secrets / Vercel env mein. Code, `state.json`, logs mein kabhi nahi (logs mein chhupa diye jaate hain).
- **Nahi karta:** YouTube video download, m3u8/HLS/stream download ya mp4 conversion, yt-dlp, DRM/login/paywall bypass, paid course apps ki videos nikaalna. YouTube ka sirf public watch link post hota hai.
- Sirf public `http(s)` links; local/private network addresses block.

## Kya abhi test nahi hua (sach)
- Telegram pe asli messages/buttons aur asli Vercel deploy: code ke tests mock se pass hain, par Telegram/Vercel ka har button asli phone pe check nahi kiya.
- NVIDIA AI ka asli jawab (key ke bina test nahi ho sakta).
- `/api/tick` + cron-job.org asli mein.
- YouTube pages: 29 Oct ko is tareeke se playlist/channel padhe gaye, par YouTube page badal de ya GitHub ke servers ko rok de toh tracker `/status` mein error dikhayega (RSS feed us din 404/500 de rahi thi).
- Badi files (userbot) ka naya code path nahi badla; pehle 1 GB file gayi thi.

## Files
```
bot/main.py            har run: commands + sync + YouTube link queue
bot/adapters/          tgvideo = video catalog site, generic = seedhe links + andar ke pages + YouTube embeds + "0 kyun"
bot/youtube_tracker.py YouTube playlist/channel/video links (sirf link)
bot/telegram_api.py    Telegram Bot API (50 MB tak)
bot/userbot.py         badi files apne account se (2 GB, optional)
bot/security.py        sirf public URLs (redirect bhi check)
state.json             bot ki yaadash (sites, bheji files, queues, errors)
api/telegram.js        Vercel webhook (Telegram yahan bhejta hai)
api/setup.js           webhook set/info/delete link
api/tick.js            optional auto-sync pinger
lib/webhook.js         webhook ka code (menu, live status, AI, GitHub dispatch)
vercel.json, .vercelignore, public/   Vercel settings
scripts/               gen_session.py (Termux), live_check.py
tests/                 python -m pytest -q   aur   node --test tests/webhook.test.js
.github/workflows/     bot.yml (schedule + commands), tests.yml
```
