# site2tg-bot 🤖

Aapki **apni websites** se files (videos, APK, PDF, zip…) download karke aapke **private Telegram channel** mein daal deta hai, backup storage ki tarah.
Sab kuch free servers pe chalta hai (GitHub Actions + Vercel), **aapke phone ka data ya storage use nahi hota**. Laptop ki zaroorat nahi, sab phone se ho jayega.

## Ye kya karta hai

- **Vercel webhook** (optional, recommended): bot hamesha online, har command ka jawab turant ("✅ mil gaya"), aur bhaari kaam turant GitHub pe start
- **GitHub Actions** asli kaam karta hai: download, upload, list, status. Har ghante khud bhi sync karta hai
- Telegram pe aapke commands padhta hai aur jawab deta hai
- Har site pe nayi files dhoondhta hai, download karta hai, channel mein bhejta hai, phir server se delete kar deta hai
- Jo file ek baar bhej di, wo dobara nahi bhejega (`state.json` mein yaad rakhta hai)

**Website types:**
1. **Video site** (jaise https://videoclasses.vercel.app/) — bot khud pehchaan leta hai, saari videos caption ke saath bhejta hai: `Course · Folder · Title`
2. **Normal page** — page pe jitne direct file links hain (`.apk .mp4 .mkv .pdf .zip .mp3 .epub` etc.), sab bhej deta hai. Page ke icons/screenshots/log files nahi bhejta.

Ek hi file do alag links pe ho (jaise `latest.apk` aur `v52.apk` same file), toh channel mein ek hi baar jaayegi.

### 🧪 Demo site (pehle se daali hui)

Abhi aapki apni sites ready nahi hain, isliye bot mein ek **demo site** pehle se daali hai:
**F-Droid ka page** — https://f-droid.org/en/packages/org.fdroid.fdroid/ (free/open-source app store, iske APK share karna legal hai).
Setup hote hi bot is page se APK utha ke channel mein bhejega, **har sync mein max 3**, taaki pata chal jaye sab kaam kar raha hai. (Is page pe ~12 APK hain, toh sab aane mein ~4 sync lagenge.)

Apni site ready ho jaye toh:
- `/addsite https://aapki-site.com` — apni site jodo
- `/removesite https://f-droid.org/en/packages/org.fdroid.fdroid/` — demo hatao

Video site bhi aise hi jud jayegi: `/addsite https://videoclasses.vercel.app/` (bot khud pehchaan lega ki ye video catalog wali site hai).

## Commands (Telegram pe bot ko bhejo)

| Command | Kaam |
|---|---|
| `/addsite <url> [limit]` | nayi website jodo. `limit` = ek sync mein max kitni nayi files (default 3). Pehle se judi site pe dobara bhejo toh limit badal jaati hai |
| `/removesite <url>` | website hatao |
| `/sites` | saari websites |
| `/sync` | abhi sync karo |
| `/status` | kitni files gayi, last sync, errors, ruki hui badi files |
| `/retry` | jo files 3 baar fail hui, unhe dobara try karo |
| `/id` | aapka OWNER_ID aur CHANNEL_ID |
| `/help` | help |

⚡ **Vercel webhook laga hai toh (neeche "Hamesha online" section):**
- `/start`, `/help`, `/id` → **turant** jawab (Vercel khud deta hai)
- `/addsite`, `/removesite`, `/sites`, `/status`, `/sync`, `/retry` → turant "✅ Mil gaya", phir Vercel GitHub pe run start karta hai. Asli jawab / files **~1-3 min** mein aate hain (GitHub run ko start hone mein ~10-60 sec lagte hain, phir kaam). Badi files ya bahut saari files ho toh zyada.
- Agar pehle se koi sync chal raha hai, toh naya command uske baad line mein chalega (koi command kho nahi jaata).

⏰ **Webhook nahi laga toh:** bot har ghante ek baar jaagta hai (GitHub kabhi-kabhi 5-15 min late bhi karta hai), command ka jawab agle run pe aayega.
Jaldi chahiye toh: **Actions → site2tg-bot → Run workflow** dabao, 1-2 min mein jawab aa jayega.

Sirf aapke (OWNER_ID) commands maane jaate hain, kisi aur ke nahi.

---

## Setup (sirf phone se, ~15 min)

### Step 1: Bot banao
1. Telegram mein **@BotFather** kholo → `/newbot` bhejo
2. Naam aur username do (username `bot` pe khatam hona chahiye)
3. BotFather ek **token** dega (jaise `123456789:AAH...`). Ye kisi ko mat bhejna.

### Step 2: Private channel banao
1. Telegram → New Channel → **Private** channel banao
2. Channel → Administrators → Add Admin → apne bot ka username search karo → add karo (**Post Messages** permission on rahe)

### Step 3: Token GitHub mein daalo
Ye link phone ke browser mein kholo (GitHub login karke):
https://github.com/scolerbitesorg-lgtm/site2tg-bot/settings/secrets/actions

**New repository secret** dabao:
- Name: `BOT_TOKEN`  → Value: BotFather wala token

(Agar mobile site pe Settings nahi dikh raha, browser menu mein "Desktop site" on karo.)

### Step 4: Apna user id aur channel id nikaalo
1. Apne bot ko Telegram pe kholo, **/start** bhejo
2. Apne channel ki koi bhi ek post bot ko **forward** karo (channel mein pehle ek "hi" post kar do)
3. Ye link kholo aur **Run workflow** dabao: https://github.com/scolerbitesorg-lgtm/site2tg-bot/actions/workflows/bot.yml
4. 1-2 min mein bot jawab dega: `OWNER_ID: ...` aur `CHANNEL_ID: -100...`

(User id ke liye **@userinfobot** ko message karke bhi dekh sakte ho.)

### Step 5: Baaki secrets daalo
Wahi secrets page (https://github.com/scolerbitesorg-lgtm/site2tg-bot/settings/secrets/actions):
- `OWNER_ID` → aapka user id (sirf number)
- `CHANNEL_ID` → channel id (`-100` se shuru hone wala poora number)

### Step 6: Chalu karo
- https://github.com/scolerbitesorg-lgtm/site2tg-bot/actions kholo. Agar "enable workflows" jaisa button dikhe toh daba do.
- **Run workflow** dabao. Demo site ke APK channel mein aane lagenge ✅
- Iske baad ye apne aap har ghante chalega. Commands turant chahiye toh neeche Vercel wala step karo.

---

## ⚡ Hamesha online: Vercel webhook (phone se, ~10 min)

Isse bot har command pe **turant** jawab deta hai. Vercel free (Hobby) plan kaafi hai. Vercel pe sirf chhota sa webhook chalta hai (Vercel function ek request mein max 300 sec chal sakta hai, Hobby plan, Vercel docs Aug 2026), isliye download/upload GitHub Actions hi karta hai.

### Step A: GitHub token banao (sirf is repo ke liye)
1. Phone browser mein ye kholo (GitHub login): https://github.com/settings/personal-access-tokens/new
   (Ya: profile photo → **Settings** → sabse neeche **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**. Settings na dikhe toh "Desktop site" on karo.)
2. **Token name**: `site2tg-vercel`
3. **Expiration**: jitna lamba chaho (expire hone pe naya banana padega, bot "GH_TOKEN galat hai ya expire" bolega)
4. **Repository access** → **Only select repositories** → `site2tg-bot` chuno
5. **Permissions** → **Repository permissions** → **Actions** → **Read and write** (Metadata: Read apne aap aa jayega). Aur kuch mat do.
6. **Generate token** → token (`github_pat_...`) copy karo. Ye dobara nahi dikhega, aur kisi ko mat bhejna.

### Step B: Ek secret word socho
`WEBHOOK_SECRET` = koi bhi lamba random word, **sirf** `A-Z a-z 0-9 _ -` (space ya @ # nahi), kam se kam 20 letters. Jaise: `meraBot_x7Kq92LmPz04Ty`. Ye Telegram aur Vercel ke beech ka password hai.

### Step C: Vercel pe deploy
1. https://vercel.com/new kholo (GitHub se login)
2. **Import Git Repository** mein `site2tg-bot` dhoondo → **Import**
   (List mein na dikhe toh **Adjust GitHub App Permissions** → `site2tg-bot` allow karo)
3. **Framework Preset**: `Other` (apne aap aayega). Root Directory: `./`. Build settings mat chhedo.
4. **Environment Variables** khol ke ye 5 daalo:

| Name | Value |
|---|---|
| `BOT_TOKEN` | BotFather wala token (wahi jo GitHub Secrets mein hai) |
| `OWNER_ID` | aapka Telegram user id (sirf number) |
| `GH_TOKEN` | Step A wala `github_pat_...` token |
| `GH_REPO` | `scolerbitesorg-lgtm/site2tg-bot` |
| `WEBHOOK_SECRET` | Step B wala word |

5. **Deploy** dabao. 1 min mein "Congratulations" aayega.
6. Project ka **domain** dekho (Project → **Domains**, jaise `site2tg-bot.vercel.app` ya `site2tg-bot-xyz.vercel.app`). Lamba wala deployment link (jisme random letters hon) mat lena, wo Vercel ke login ke peeche hota hai aur Telegram usse nahi khol sakta.

### Step D: Webhook chalu karo (ek link kholna hai)
Phone browser mein kholo (apna domain aur secret daal ke):
```
https://<aapka-domain>/api/setup?key=<WEBHOOK_SECRET>
```
"✅ Webhook set ho gaya!" aana chahiye. Ab bot ko `/help` bhejo, turant jawab aayega. 🎉

Kaam ke links (same key ke saath):
- Status dekhna: `https://<aapka-domain>/api/setup?key=<WEBHOOK_SECRET>&action=info`
- **Wapas purana mode** (sirf GitHub, har ghante): `...&action=delete`. GitHub bot apne aap samajh jayega aur phir se khud commands padhne lagega.
- Webhook ka health: `https://<aapka-domain>/api/telegram` kholo. Koi env var missing hai toh naam bata dega.

⚠️ Vercel pe koi env var badla toh **Deployments → sabse upar wala → ⋯ → Redeploy** karna padta hai, tabhi naya value lagta hai.

**Kya-kya hota hai:** Telegram har message Vercel ko bhejta hai (secret header ke saath, warna Vercel mana kar deta hai). Vercel sirf OWNER_ID ki baat sunta hai. Bhaari command aaye toh GitHub ko "workflow chalao, command = /sync" bolta hai. GitHub run wahi command chala ke aapko jawab bhejta hai. Webhook laga ho toh GitHub run Telegram se purane tareeke (getUpdates) se messages nahi padhta, double kaam nahi hota. Setting `WEBHOOK_MODE` (repo variable) `1`/`0` se ye zabardasti on/off kar sakte ho, warna bot Telegram se khud pooch leta hai.

**Setup mode:** Vercel pe `OWNER_ID` na daala ho toh bot kisi ko bhi uska user id batata hai, aur channel ki forward ki hui post pe channel id. (OWNER_ID daalne ke baad bhi, aap channel ki post forward karoge toh channel id bata dega.)

Vercel pe repo ki baaki cheezein (Python bot, state.json) nahi jaati, sirf webhook (`api/`, `lib/`). Har ghante state.json ka commit hota hai, us pe Vercel dobara deploy nahi karta (sirf webhook code badle tab).

---

## Badi files (50 MB se upar) — optional

Telegram bot sirf **50 MB** tak ki file bhej sakta hai. Usse badi files ke liye bot aapke **apne Telegram account** se upload karega (2 GB tak). Iske liye 3 aur secrets chahiye: `API_ID`, `API_HASH`, `SESSION_STRING`.
Ye secrets nahi daale toh badi files skip hongi aur `/status` mein "ruki hui" dikhengi. Secrets daalte hi agle sync mein chali jayengi.

**API_ID aur API_HASH** (phone browser se ho jayega):
1. https://my.telegram.org kholo → apna number daalo → Telegram pe aaya code daalo
2. **API development tools** → koi bhi app naam/short name bhar ke create karo
3. `api_id` aur `api_hash` dikhenge → dono ko secrets mein daalo (`API_ID`, `API_HASH`)

**SESSION_STRING** — sach bata raha hoon: isko banane ke liye ek baar Telegram mein login karke code daalna padta hai, jo GitHub Actions pe nahi ho sakta. Phone pe sabse seedha safe tareeka **Termux** hai:
1. **F-Droid** se Termux install karo (Play Store wala purana hai, mat lena)
2. Termux mein ye do command chalao:
   ```
   pkg install python -y
   pip install telethon
   ```
3. Phir `nano gen_session.py` likho, aur repo ki file [`scripts/gen_session.py`](scripts/gen_session.py) ka poora code copy karke paste karo. Save: `Ctrl+O`, Enter, `Ctrl+X` (Termux ke upar wali extra keys mein CTRL hota hai)
4. Chalao: `python gen_session.py`
5. API_ID, API_HASH, phone number (+91 ke saath) aur Telegram ka code daalo
6. Ek lambi string milegi (aapke **Saved Messages** mein bhi aa jayegi) → use `SESSION_STRING` secret mein daalo

⚠️ SESSION_STRING aapke Telegram account ki **poori chaabi** hai. Kisi ko mat bhejna, kisi "session string generator" bot ya website pe mat banana. Wo aapka account le sakte hain.

---

## Settings (optional)

https://github.com/scolerbitesorg-lgtm/site2tg-bot/settings/variables/actions pe **Variables** bana sakte ho:
- `SYNC_EVERY_MIN` — kitne minute mein sync ho (default `60`). Commands har run pe padhe jaate hain.
- `WEBHOOK_MODE` — `1` = webhook mode, `0` = polling. Khali chhodo, bot khud pata kar leta hai.
- `MAX_FILES_PER_RUN` — ek run mein saari sites mila ke max files (default `15`). Baaki agle run mein.
- Har site ki apni limit `/addsite <url> <limit>` se badlo.

Run ka time badalna ho toh `.github/workflows/bot.yml` mein `cron: "17 * * * *"` (har ghante, 17 minute pe) badlo.

## Free limit ka hisaab

Private repo pe GitHub **2000 minute/month free** deta hai. Har run kam se kam 1 minute gina jaata hai. Har ghante wala run ≈ 720 min/month, baaki commands aur downloads ke liye bachta hai. (Pehle har 30 min tha = ~1440 min, isliye ab har ghante kar diya; webhook se commands waise bhi turant chalte hain.)
- Har command (`/status`, `/sync`…) ek run = ~1 min. Din mein 20-30 commands tak aaram se.
- Agar "minutes khatam" ka message aaye: cron ko `"17 */2 * * *"` (har 2 ghante) kar do.
- Vercel ka free plan is webhook ke liye kaafi se zyada hai.
- Ya repo ko **Public** kar do: public repo pe Actions unlimited free hai (secrets tab bhi safe rehte hain), lekin `state.json` mein aapki websites ki list sabko dikhegi.

## Safety

- Token, API hash, session string sirf GitHub Secrets / Vercel env vars mein rehte hain, code ya `state.json` mein kabhi nahi likhe jaate, logs mein bhi chhupa diye jaate hain.
- Ye bot sirf aapki apni websites ke liye hai. Paid course apps / doosron ki protected videos ke liye isme koi support nahi hai.

## Files

```
bot/main.py           har run ka kaam: commands + sync
bot/adapters/         website types (tgvideo = video site, generic = direct links)
bot/telegram_api.py   Telegram Bot API (50 MB tak)
bot/userbot.py        badi files apne account se (2 GB tak, optional)
bot/state.py          state.json padhna/likhna
state.json            bot ki yaadash (sites, bheji gayi files, errors)
api/telegram.js       Vercel webhook (Telegram yahan bhejta hai)
api/setup.js          webhook set/info/delete wala link
lib/webhook.js        webhook ka code (owner check, GitHub dispatch)
vercel.json, .vercelignore, public/   Vercel settings
scripts/gen_session.py  SESSION_STRING banane ke liye (Termux)
scripts/live_check.py   site check: kaun si files milengi
tests/                tests (python -m pytest  aur  node --test tests/webhook.test.js)
.github/workflows/bot.yml  GitHub Actions schedule + command input
```
