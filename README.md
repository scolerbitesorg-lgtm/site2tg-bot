# site2tg-bot 🤖

Aapki **apni websites** se files (videos, APK, PDF, zip…) download karke aapke **private Telegram channel** mein daal deta hai, backup storage ki tarah.
Sab kuch GitHub ke free server (GitHub Actions) pe chalta hai, **aapke phone ka data ya storage use nahi hota**. Laptop ki zaroorat nahi, sab phone se ho jayega.

## Ye kya karta hai

- Har ~30 minute pe GitHub pe ek baar chalta hai
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

⏰ **Dhyan do:** bot har time online nahi rehta, ~30 min mein ek baar jaagta hai (GitHub kabhi-kabhi 5-15 min late bhi karta hai). Isliye command ka jawab turant nahi aayega, agle run pe aayega.
Jaldi chahiye toh: GitHub app ya site pe **Actions → site2tg-bot → Run workflow** dabao, 1-2 min mein jawab aa jayega.

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
- Iske baad ye apne aap har ~30 min pe chalega.

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
- `MAX_FILES_PER_RUN` — ek run mein saari sites mila ke max files (default `15`). Baaki agle run mein.
- Har site ki apni limit `/addsite <url> <limit>` se badlo.

Run ka time badalna ho toh `.github/workflows/bot.yml` mein `cron: "*/30 * * * *"` badlo.

## Free limit ka hisaab

Private repo pe GitHub **2000 minute/month free** deta hai. Har 30 min ka run ≈ 1 min = ~1440 min/month, plus downloads ka time. Isliye default 30 min rakha hai.
- Agar "minutes khatam" ka message aaye: cron ko `"0 * * * *"` (har ghante) kar do.
- Ya repo ko **Public** kar do: public repo pe Actions unlimited free hai (secrets tab bhi safe rehte hain), lekin `state.json` mein aapki websites ki list sabko dikhegi.

## Safety

- Token, API hash, session string sirf GitHub Secrets mein rehte hain, code ya `state.json` mein kabhi nahi likhe jaate, logs mein bhi chhupa diye jaate hain.
- Ye bot sirf aapki apni websites ke liye hai. Paid course apps / doosron ki protected videos ke liye isme koi support nahi hai.

## Files

```
bot/main.py           har run ka kaam: commands + sync
bot/adapters/         website types (tgvideo = video site, generic = direct links)
bot/telegram_api.py   Telegram Bot API (50 MB tak)
bot/userbot.py        badi files apne account se (2 GB tak, optional)
bot/state.py          state.json padhna/likhna
state.json            bot ki yaadash (sites, bheji gayi files, errors)
scripts/gen_session.py  SESSION_STRING banane ke liye (Termux)
scripts/live_check.py   site check: kaun si files milengi
tests/                tests (python -m pytest)
.github/workflows/bot.yml  GitHub Actions schedule
```
