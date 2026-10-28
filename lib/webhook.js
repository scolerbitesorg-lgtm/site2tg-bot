// site2tg-bot Vercel front-end (Node, no dependencies).
//
// Telegram -> POST /api/telegram (this webhook):
//   * instant: /start /menu /help /id, the inline menu, live /status and /sites
//     (read straight from the repo: state.json + latest workflow runs), and the
//     optional AI assistant (NVIDIA, OpenAI-compatible API)
//   * state-changing (/addsite /removesite /sync /retry): replies "⏳ chal raha
//     hai…" at once, then starts .github/workflows/bot.yml via workflow_dispatch
//     with inputs {command, ack_message_id}; the Actions run does the work and
//     edits that ⏳ message into the final result.
// Secrets come only from Vercel env vars and are never logged or echoed.
"use strict";

const crypto = require("crypto");

const WORKFLOW_FILE = "bot.yml";
const SECRET_RE = /^[A-Za-z0-9_-]{1,256}$/;
const ACTION_COMMANDS = ["/addsite", "/removesite", "/sync", "/retry", "/get"];
const LIVE_COMMANDS = ["/status", "/sites"];
const NEEDS_ARG = {
  "/addsite": "Aise likho: /addsite https://meri-site.com 3\n(ya /menu → ➕ Add site)",
  "/removesite": "Aise likho: /removesite https://meri-site.com\n(ya /menu → 🗑 Remove site)",
  "/get": "Aise likho: /get https://site.com/file.mp4\n(ya /menu → 📥 Download link)",
};
const GET_PROMPT = "📥 File ka direct link bhejo";
const STREAM_RE = /(\.m3u8|\.mpd)(\?|#|$)|^https?:\/\/([^/]*\.)?(youtube\.com|youtu\.be)(\/|$)/i;
const STREAM_NO = "Ye stream/YouTube link hai. Ye bot sirf direct file links download karta hai (jaise …/video.mp4, …/app.apk).";
const ADD_PROMPT = "➕ Nayi site ka URL bhejo";
const AI_PROMPT = "🤖 Apna sawal likho";
const DEFAULT_NVIDIA_BASE = "https://integrate.api.nvidia.com/v1";
const DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-20b";
const FALLBACK_NVIDIA_MODEL = "mistralai/mistral-large-2-instruct";
const DEFAULT_SITE_LIMIT = 3;
const MAX_TRIES = 3;

const HELP = `🤖 site2tg-bot

Neeche ke buttons ya ye commands:
/menu — buttons wala menu
/status — live status (turant)
/sites — saari websites (turant)
/addsite <url> [limit] [depth] — nayi website jodo (limit = ek sync mein max nayi files, default 3; depth = andar ke pages kitne level, 0-5, default 5)
/removesite <url> — website hatao
/sync — abhi sync karo
/get <link> — ek direct file link turant download karke channel mein
/retry — jo files 3 baar fail hui, unhe dobara try karo
/id — aapka OWNER_ID
/help — ye message

Koi bhi sawal seedha likh do (AI on ho toh jawab dega).
⏳ Add/remove/sync/retry GitHub pe chalte hain: "chal raha hai" turant aata hai, wahi message ~1-2 min mein result se badal jaata hai.`;

const ACK = {
  "/sync": "⏳ Sync chal raha hai… (GitHub run start ho raha hai, files 1-3 min mein channel mein)",
  "/addsite": "⏳ Site check karke jod raha hoon… (~1-2 min)",
  "/removesite": "⏳ Site hata raha hoon… (~1-2 min)",
  "/retry": "⏳ Fail hui files dobara try ho rahi hain… (~1-3 min)",
  "/get": "⏳ File download ho rahi hai… (chhoti file ~20 sec, badi file mein zyada)",
  "/status": "⏳ Status GitHub se la raha hoon… (~1-2 min)",
  "/sites": "⏳ List GitHub se la raha hoon… (~1-2 min)",
};

const MENU = {
  inline_keyboard: [
    [{ text: "📊 Status", callback_data: "m:status" }, { text: "🌐 Sites", callback_data: "m:sites" }],
    [{ text: "🔄 Sync now", callback_data: "m:sync" }, { text: "🔁 Retry", callback_data: "m:retry" }],
    [{ text: "📥 Download link", callback_data: "m:get" }],
    [{ text: "➕ Add site", callback_data: "m:add" }, { text: "🗑 Remove site", callback_data: "m:rm" }],
    [{ text: "🤖 Ask AI", callback_data: "m:ai" }, { text: "❓ Help", callback_data: "m:help" }],
  ],
};

const BOT_COMMANDS = [
  ["menu", "buttons wala menu"], ["status", "live status"], ["sites", "saari websites"],
  ["get", "ek file link download"], ["addsite", "nayi website jodo"], ["removesite", "website hatao"], ["sync", "abhi sync karo"],
  ["retry", "fail files dobara"], ["id", "apna id"], ["help", "help"],
].map(([command, description]) => ({ command, description }));

// ------------------------------------------------------------------ helpers

function cleanEnv(env, name) {
  return String((env && env[name]) || "").trim();
}

function safeEqual(a, b) {
  const x = Buffer.from(String(a || ""));
  const y = Buffer.from(String(b || ""));
  if (x.length !== y.length || x.length === 0) return false;
  return crypto.timingSafeEqual(x, y);
}

function header(req, name) {
  const h = req.headers || {};
  const v = h[name] !== undefined ? h[name] : h[name.toLowerCase()];
  return Array.isArray(v) ? v[0] : v;
}

async function readJson(req) {
  if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return req.body;
  let raw = req.body;
  if (raw === undefined || raw === null) {
    raw = await new Promise((resolve, reject) => {
      const chunks = [];
      req.on("data", (c) => chunks.push(Buffer.from(c)));
      req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
      req.on("error", reject);
    });
  }
  if (Buffer.isBuffer(raw)) raw = raw.toString("utf8");
  try {
    return JSON.parse(raw || "{}");
  } catch (e) {
    return null;
  }
}

function send(res, status, text) {
  res.statusCode = status;
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(text);
}

// never let a token reach a log line or a chat reply
function redact(text, env) {
  let s = String(text);
  for (const k of ["BOT_TOKEN", "GH_TOKEN", "WEBHOOK_SECRET", "NVIDIA_API_KEY"]) {
    const v = cleanEnv(env, k);
    if (v.length >= 4) s = s.split(v).join("***");
  }
  return s.replace(/\b\d{6,}:[A-Za-z0-9_-]{30,}\b/g, "***").replace(/\bnvapi-[A-Za-z0-9_-]{10,}/g, "***").slice(0, 500);
}

function shortHash(s) {
  return crypto.createHash("sha1").update(String(s)).digest("hex").slice(0, 10);
}

function ist(iso) {
  if (!iso) return "kabhi nahi";
  const d = new Date(String(iso));
  if (isNaN(d)) return "kabhi nahi";
  const t = new Date(d.getTime() + 5.5 * 3600 * 1000);
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][t.getUTCMonth()];
  let h = t.getUTCHours();
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(t.getUTCDate())} ${mon} ${p(h)}:${p(t.getUTCMinutes())} ${ampm} IST`;
}

function ago(iso, nowMs) {
  const d = new Date(String(iso || ""));
  if (isNaN(d)) return "";
  const m = Math.max(0, Math.round(((nowMs || Date.now()) - d.getTime()) / 60000));
  if (m < 1) return "abhi";
  if (m < 60) return `${m} min pehle`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} ghante pehle` : `${Math.floor(h / 24)} din pehle`;
}

function humanSize(n) {
  n = Number(n);
  if (!n) return "?";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

// ------------------------------------------------------------------ Telegram

async function tg(ctx, method, payload) {
  const token = cleanEnv(ctx.env, "BOT_TOKEN");
  const r = await ctx.fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
    signal: AbortSignal.timeout(8000),
  });
  let j = {};
  try { j = await r.json(); } catch (e) { j = { ok: false, description: `HTTP ${r.status}` }; }
  if (!j.ok) throw new Error(`${method}: ${j.error_code || r.status} ${j.description || ""}`);
  return j.result;
}

async function say(ctx, chatId, text, extra) {
  try {
    return await tg(ctx, "sendMessage", Object.assign({ chat_id: chatId, text: String(text).slice(0, 4000), disable_web_page_preview: true }, extra || {}));
  } catch (e) {
    ctx.log("reply failed: " + redact(e.message, ctx.env));
    return null;
  }
}

async function edit(ctx, chatId, messageId, text) {
  try {
    return await tg(ctx, "editMessageText", { chat_id: chatId, message_id: messageId, text: String(text).slice(0, 4000), disable_web_page_preview: true });
  } catch (e) {
    ctx.log("edit failed: " + redact(e.message, ctx.env));
    return say(ctx, chatId, text);
  }
}

// ------------------------------------------------------------------ GitHub

function ghRepo(env) {
  const repo = cleanEnv(env, "GH_REPO");
  if (repo) return repo;
  const owner = cleanEnv(env, "VERCEL_GIT_REPO_OWNER");
  const slug = cleanEnv(env, "VERCEL_GIT_REPO_SLUG");
  return owner && slug ? `${owner}/${slug}` : "";
}

function ghRef(env) {
  return cleanEnv(env, "GH_REF") || "main";
}

function ghHeaders(env, accept) {
  return {
    Authorization: `Bearer ${cleanEnv(env, "GH_TOKEN")}`,
    Accept: accept || "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "site2tg-bot-webhook",
  };
}

const DISPATCH_HINT = {
  401: "GH_TOKEN galat hai ya expire ho gaya. Naya token banao aur Vercel env mein daalo (phir Redeploy).",
  403: "GH_TOKEN ko is repo pe \"Actions: Read and write\" permission chahiye.",
  404: "Repo ya workflow nahi mila. GH_REPO check karo (scolerbitesorg-lgtm/site2tg-bot) aur token mein ye repo select hai ya nahi.",
  422: "GitHub ne command accept nahi ki (branch ya workflow inputs). GH_REF / bot.yml check karo.",
};

const READ_HINT = {
  401: "GH_TOKEN galat ya expire hai",
  403: "GH_TOKEN ko \"Contents: Read\" aur \"Actions: Read\" permission chahiye",
  404: "repo/state.json nahi mila (GH_REPO ya token ka repo access check karo)",
};

function configMissing(env) {
  const repo = ghRepo(env);
  const token = cleanEnv(env, "GH_TOKEN");
  if (!repo || !token) return `Vercel pe ${!token ? "GH_TOKEN" : "GH_REPO"} env var nahi hai. Settings → Environment Variables mein daalo, phir Redeploy.`;
  return "";
}

async function dispatch(ctx, commandText, ackMessageId) {
  const missing = configMissing(ctx.env);
  if (missing) return { ok: false, why: missing };
  const url = `https://api.github.com/repos/${ghRepo(ctx.env)}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const inputs = { command: String(commandText).slice(0, 1000) };
  if (ackMessageId) inputs.ack_message_id = String(ackMessageId);
  const body = { ref: ghRef(ctx.env), inputs };
  let r;
  try {
    r = await ctx.fetch(url, {
      method: "POST",
      headers: Object.assign(ghHeaders(ctx.env), { "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });
  } catch (e) {
    return { ok: false, why: `GitHub tak pahunch nahi paya (${e.name || "network error"}). Thodi der baad dobara bhejo.` };
  }
  if (r.status >= 200 && r.status < 300) return { ok: true, status: r.status };
  return { ok: false, status: r.status, why: DISPATCH_HINT[r.status] || `GitHub ne mana kiya (HTTP ${r.status}).` };
}

async function ghGet(ctx, path, accept) {
  const r = await ctx.fetch(`https://api.github.com/repos/${ghRepo(ctx.env)}${path}`, {
    method: "GET", headers: ghHeaders(ctx.env, accept), signal: AbortSignal.timeout(7000),
  });
  if (r.status !== 200) {
    const e = new Error(READ_HINT[r.status] || `GitHub HTTP ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return r;
}

// Live view: state.json (as last committed by the Actions run) + latest runs.
async function loadLive(ctx) {
  const missing = configMissing(ctx.env);
  if (missing) return { state: null, runs: null, error: missing };
  const ref = encodeURIComponent(ghRef(ctx.env));
  const [st, rn] = await Promise.allSettled([
    ghGet(ctx, `/contents/state.json?ref=${ref}`, "application/vnd.github.raw+json").then(async (r) => {
      const text = await r.text();
      return JSON.parse(text);
    }),
    ghGet(ctx, `/actions/workflows/${WORKFLOW_FILE}/runs?per_page=6`).then(async (r) => (await r.json()).workflow_runs || []),
  ]);
  return {
    state: st.status === "fulfilled" ? st.value : null,
    runs: rn.status === "fulfilled" ? rn.value : null,
    error: st.status === "rejected" ? `state.json padh nahi paya: ${st.reason.message}` : "",
    runsError: rn.status === "rejected" ? `runs padh nahi paya: ${rn.reason.message}` : "",
  };
}

const RUNNING = ["queued", "in_progress", "waiting", "pending", "requested"];

function runTitle(r) {
  const t = String(r.display_title || "");
  if (t.startsWith("cmd ")) return t.slice(4);
  return r.event === "schedule" ? "auto sync" : "manual run";
}

function runLine(r, nowMs) {
  if (RUNNING.includes(r.status)) {
    const label = r.status === "in_progress" ? "chal raha hai" : "line mein hai";
    return `▶️ ${runTitle(r)} — ${label} (${ago(r.run_started_at || r.created_at, nowMs)} start)`;
  }
  const icon = { success: "✅", failure: "❌", cancelled: "🚫", timed_out: "⏱" }[r.conclusion] || "•";
  return `${icon} ${runTitle(r)} — ${ist(r.updated_at || r.created_at)} (${r.conclusion || r.status})`;
}

function formatStatus(live, nowMs) {
  const s = live.state;
  const lines = ["📊 Live status"];
  if (!s) {
    lines.push(`⚠️ ${live.error || "state.json nahi mila"}`);
  } else {
    lines.push(
      `Websites: ${(s.sites || []).length}`,
      `Total files bheji: ${s.files_sent_total || 0}`,
      `Last sync: ${ist(s.last_sync)}${s.last_sync ? ` (${ago(s.last_sync, nowMs)})` : ""}`,
      `Last result: ${s.last_result || "-"}`,
    );
    if (s.routing) lines.push(`Channels: ${s.routing}`);
    if (s.last_get && s.last_get.name) lines.push(`Last /get: ${s.last_get.name} (${humanSize(s.last_get.size)}), ${ist(s.last_get.at)}`);
    if (s.sync_requested) lines.push("🔄 Agla sync line mein hai (bachi hui files)");
    const big = Object.values(s.big_pending || {});
    if (big.length) {
      lines.push(`\n⚠️ ${big.length} badi files (>50 MB) ruki hui hain (userbot secrets daalo):`);
      for (const v of big.slice(0, 8)) lines.push(`• ${v.name} (${humanSize(v.size)})`);
    }
    const gaveUp = Object.values(s.fails || {}).filter((v) => v >= MAX_TRIES).length;
    if (gaveUp) lines.push(`\n⛔ ${gaveUp} files 3 baar fail hui, skip ho rahi hain (/retry)`);
    const errs = (s.errors || []).slice(-4);
    if (errs.length) {
      lines.push("\n❌ Last errors:");
      for (const e of errs) lines.push(`• ${ist(e.at)}: ${String(e.msg).slice(0, 160)}`);
    }
  }
  if (live.runs) {
    const running = live.runs.filter((r) => RUNNING.includes(r.status));
    lines.push("", running.length ? `⚙️ GitHub: abhi ${running.length} run chal/ruk rahe hain` : "⚙️ GitHub: abhi koi run nahi chal raha");
    for (const r of live.runs.slice(0, 4)) lines.push(runLine(r, nowMs));
  } else if (live.runsError) {
    lines.push("", `⚠️ ${live.runsError}`);
  }
  return lines.join("\n");
}

function formatSites(state) {
  const sites = (state && state.sites) || [];
  if (!sites.length) return "Abhi koi site nahi hai. /menu → ➕ Add site, ya /addsite <url>";
  const lines = sites.map((s, i) => `${i + 1}. ${s.url} (${s.adapter || "?"}, max ${s.limit || DEFAULT_SITE_LIMIT}/sync${s.depth ? `, ${s.depth} level andar` : ""}) — ${((state.sent || {})[s.url] || []).length} files bheji`);
  return "🌐 Websites:\n" + lines.join("\n");
}

// ------------------------------------------------------------------ AI (NVIDIA)

function snapshot(live, nowMs) {
  const s = live.state || {};
  const snap = {
    now_ist: ist(new Date(nowMs || Date.now()).toISOString()),
    sites: (s.sites || []).map((x) => ({ url: x.url, type: x.adapter, max_per_sync: x.limit || DEFAULT_SITE_LIMIT, inner_page_levels: x.depth || 0, files_sent: ((s.sent || {})[x.url] || []).length })),
    files_sent_total: s.files_sent_total || 0,
    last_sync_ist: s.last_sync ? ist(s.last_sync) : null,
    last_result: s.last_result || "",
    channels: s.routing || "",
    last_get: s.last_get ? `${s.last_get.name} (${humanSize(s.last_get.size)}) ${ist(s.last_get.at)}` : null,
    next_sync_queued: !!s.sync_requested,
    big_files_waiting: Object.values(s.big_pending || {}).slice(0, 10).map((v) => `${v.name} (${humanSize(v.size)})`),
    files_given_up: Object.values(s.fails || {}).filter((v) => v >= MAX_TRIES).length,
    last_errors: (s.errors || []).slice(-5).map((e) => `${ist(e.at)}: ${String(e.msg).slice(0, 160)}`),
    github_runs: (live.runs || []).slice(0, 5).map((r) => ({ what: runTitle(r), status: r.status, result: r.conclusion, started_ist: ist(r.run_started_at || r.created_at) })),
  };
  if (live.error) snap.state_read_error = live.error;
  return JSON.stringify(snap).slice(0, 3500);
}

const AI_SYSTEM = `Tum "site2tg-bot" Telegram bot ke assistant ho. Ye bot owner ki apni websites se files (video, APK, PDF, zip) download karke unke private Telegram channel mein backup karta hai. Kaam GitHub Actions pe hota hai (har 10 minute schedule par auto sync + har command pe turant run), Vercel webhook turant reply deta hai.
Single file: /get <direct link> se ek file turant channel mein jaati hai. Videos aur baaki files alag channels mein ja sakti hain (CHANNEL_ID_VIDEO / CHANNEL_ID_FILES secrets).
Niyam:
- Jawab chhota, simple Hinglish mein (2-6 lines), WhatsApp jaisa casual.
- Bot ke baare mein facts SIRF diye gaye STATUS JSON se batao. Jo JSON mein nahi hai wo mat banao; "pata nahi" bolo.
- Tum khud koi action nahi karte (site add/remove/sync nahi kar sakte). Agar user kuch karwana chahe toh exact command batao: /get <link>, /addsite <url> [limit], /removesite <url>, /sync, /retry, /status, /sites, /menu.
- 50 MB se badi files ke liye API_ID, API_HASH, SESSION_STRING GitHub Secrets chahiye.
- Paid course sites, HLS/m3u8 streams, YouTube/yt-dlp jaisa support is bot mein nahi hai; aisi request pe politely mana karo.
- Kabhi bhi token, password ya secret mat maango.`;

async function askAI(ctx, question, live) {
  const key = cleanEnv(ctx.env, "NVIDIA_API_KEY");
  if (!key) return null;
  const base = (cleanEnv(ctx.env, "NVIDIA_BASE_URL") || DEFAULT_NVIDIA_BASE).replace(/\/+$/, "");
  const first = cleanEnv(ctx.env, "NVIDIA_MODEL") || DEFAULT_NVIDIA_MODEL;
  const models = first === FALLBACK_NVIDIA_MODEL ? [first] : [first, FALLBACK_NVIDIA_MODEL];
  const deadline = Date.now() + (Number(cleanEnv(ctx.env, "AI_TIMEOUT_SEC")) || 25) * 1000;
  let lastWhy = "";
  for (const model of models) {
    const left = deadline - Date.now();
    if (left < 3000) break;
    let r;
    try {
      r = await ctx.fetch(`${base}/chat/completions`, {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          model,
          temperature: 0.3,
          max_tokens: 900,
          messages: [
            { role: "system", content: AI_SYSTEM },
            { role: "user", content: `STATUS JSON: ${snapshot(live, ctx.now())}\n\nSawal: ${String(question).slice(0, 1500)}` },
          ],
        }),
        signal: AbortSignal.timeout(left),
      });
    } catch (e) {
      return { ok: false, why: e.name === "TimeoutError" || e.name === "AbortError" ? "AI ne time pe jawab nahi diya (NVIDIA slow hai). Thodi der baad dobara pucho." : "AI tak pahunch nahi paya." };
    }
    if (r.status === 401 || r.status === 403) return { ok: false, why: "NVIDIA_API_KEY galat ya expire hai. build.nvidia.com se nayi key lo, Vercel env mein daalo, Redeploy." };
    if (r.status === 404 || r.status === 410) { lastWhy = `model "${model}" nahi mila`; continue; }
    if (r.status === 429) return { ok: false, why: "NVIDIA ki free limit abhi bhar gayi hai, thodi der baad pucho." };
    if (r.status !== 200) return { ok: false, why: `AI se error aaya (HTTP ${r.status}).` };
    let j;
    try { j = await r.json(); } catch (e) { return { ok: false, why: "AI ka jawab samajh nahi aaya." }; }
    const text = (((j.choices || [])[0] || {}).message || {}).content;
    if (!text || !String(text).trim()) return { ok: false, why: "AI ne khaali jawab diya, dobara pucho." };
    return { ok: true, text: String(text).trim(), model };
  }
  return { ok: false, why: `AI model nahi mila (${lastWhy}). Vercel env NVIDIA_MODEL mein build.nvidia.com ka koi model id daalo.` };
}

const AI_OFF = `🤖 AI abhi band hai. Chalu karne ke liye:
1. build.nvidia.com pe login karo → kisi model pe "Get API Key" → key copy (nvapi-…)
2. Vercel → Project → Settings → Environment Variables → NVIDIA_API_KEY = wo key
3. Deployments → Redeploy
Tab tak /menu ke buttons use karo.`;

// ------------------------------------------------------------------ handlers

function setupReply(msg) {
  const lines = [`👤 Aapka user id (OWNER_ID): ${(msg.from || {}).id}`];
  const origin = msg.forward_origin || {};
  const chat = origin.chat || msg.forward_from_chat || {};
  if (chat.id) lines.push(`📢 Channel id (CHANNEL_ID): ${chat.id}  (${chat.title || ""})`);
  else lines.push("Channel id ke liye: apne channel ki koi bhi post is bot ko forward karo.");
  lines.push("OWNER_ID ko GitHub Secrets aur Vercel env vars dono mein daalo, CHANNEL_ID sirf GitHub Secrets mein. Phir Vercel pe Redeploy.");
  return lines.join("\n");
}

function parseCommand(text) {
  const parts = String(text).trim().split(/\s+/);
  const cmd = parts[0].split("@")[0].toLowerCase();
  const arg = String(text).trim().slice(parts[0].length).trim();
  return { cmd, arg };
}

// state-changing work: ⏳ message first, then GitHub run (which edits it)
async function runOnGitHub(ctx, chatId, command, ackText) {
  const ack = await say(ctx, chatId, ackText);
  const r = await dispatch(ctx, command, ack && ack.message_id);
  ctx.log(`dispatch ${command.split(" ")[0]}: ${r.ok ? "ok" : "failed " + (r.status || "")}`);
  if (!r.ok) {
    const text = `⚠️ Command GitHub tak nahi gayi: ${r.why}`;
    if (ack && ack.message_id) await edit(ctx, chatId, ack.message_id, text);
    else await say(ctx, chatId, text);
  }
  return r;
}

async function liveReply(ctx, chatId, cmd) {
  const live = await loadLive(ctx);
  if (!live.state && !live.runs) {
    // can't read the repo (e.g. token without Contents: read): let the Actions run answer
    await say(ctx, chatId, `⚠️ Live status nahi mila: ${live.error}${live.runsError ? "; " + live.runsError : ""}. GitHub run se mangwa raha hoon.`);
    return runOnGitHub(ctx, chatId, cmd, ACK[cmd]);
  }
  const text = cmd === "/sites" ? (live.state ? formatSites(live.state) : `⚠️ ${live.error}`) : formatStatus(live, ctx.now());
  return say(ctx, chatId, text, cmd === "/status" ? { reply_markup: MENU } : undefined);
}

async function aiReply(ctx, chatId, question) {
  if (!cleanEnv(ctx.env, "NVIDIA_API_KEY")) return say(ctx, chatId, AI_OFF);
  try { await tg(ctx, "sendChatAction", { chat_id: chatId, action: "typing" }); } catch (e) { /* not important */ }
  const live = await loadLive(ctx);
  const r = await askAI(ctx, question, live);
  ctx.log(`ai: ${r.ok ? "ok " + r.model : "failed"}`);
  return say(ctx, chatId, r.ok ? r.text : `⚠️ ${r.why}`);
}

async function handleMessage(ctx, msg) {
  const env = ctx.env;
  const owner = cleanEnv(env, "OWNER_ID");
  const chatId = msg.chat.id;
  const sender = String((msg.from || {}).id || "");
  if (!owner) return { note: "setup mode", sent: await say(ctx, chatId, setupReply(msg)) };
  if (sender !== owner) return { note: "non-owner ignored" };

  const text = String(msg.text || "").trim();
  const replyTo = msg.reply_to_message || {};
  const replyText = String(replyTo.text || "");
  const origin = msg.forward_origin || {};
  const fchat = origin.chat || msg.forward_from_chat || {};

  if (!text.startsWith("/")) {
    if (fchat.id) return { note: "channel id", sent: await say(ctx, chatId, `📢 Is channel ki id (CHANNEL_ID): ${fchat.id}  (${fchat.title || ""})`) };
    if (!text) return { note: "no text" };
    if (replyText.startsWith(GET_PROMPT)) {
      const url = text.split(/\s+/)[0];
      if (!/^https?:\/\/[^\s/]+\.[^\s]+/i.test(url)) return { note: "bad url", sent: await say(ctx, chatId, "Ye link nahi lag raha. Aise bhejo: https://site.com/file.mp4") };
      if (STREAM_RE.test(url)) return { note: "stream refused", sent: await say(ctx, chatId, STREAM_NO) };
      await runOnGitHub(ctx, chatId, `/get ${url}`, ACK["/get"]);
      return { note: "get via prompt" };
    }
    if (replyText.startsWith(ADD_PROMPT)) {
      const url = text.split(/\s+/)[0];
      if (!/^(https?:\/\/)?[^\s/]+\.[^\s]+/i.test(url)) return { note: "bad url", sent: await say(ctx, chatId, "Ye URL nahi lag raha. Aise bhejo: https://meri-site.com") };
      await runOnGitHub(ctx, chatId, `/addsite ${text}`, ACK["/addsite"]);
      return { note: "add via prompt" };
    }
    await aiReply(ctx, chatId, text);
    return { note: "ai" };
  }

  const { cmd, arg } = parseCommand(text);
  if (cmd === "/start" || cmd === "/menu") return { note: cmd, sent: await say(ctx, chatId, cmd === "/start" ? HELP : "📋 Menu — kya karna hai?", { reply_markup: MENU }) };
  if (cmd === "/help") return { note: cmd, sent: await say(ctx, chatId, HELP, { reply_markup: MENU }) };
  if (cmd === "/id") {
    const ch = cleanEnv(env, "CHANNEL_ID");
    return { note: cmd, sent: await say(ctx, chatId, `OWNER_ID: ${owner}\nCHANNEL_ID: ${ch || "(GitHub Secrets mein hai)"}`) };
  }
  if (cmd === "/ai" || cmd === "/ask") {
    if (!arg) return { note: "ai prompt", sent: await say(ctx, chatId, AI_PROMPT, { reply_markup: { force_reply: true, input_field_placeholder: "Sawal…" } }) };
    await aiReply(ctx, chatId, arg);
    return { note: "ai" };
  }
  if (LIVE_COMMANDS.includes(cmd)) {
    await liveReply(ctx, chatId, cmd);
    return { note: cmd };
  }
  if (ACTION_COMMANDS.includes(cmd)) {
    if (NEEDS_ARG[cmd] && !arg) return { note: "usage", sent: await say(ctx, chatId, NEEDS_ARG[cmd]) };
    if (cmd === "/get" && STREAM_RE.test(arg.split(/\s+/)[0])) return { note: "stream refused", sent: await say(ctx, chatId, STREAM_NO) };
    await runOnGitHub(ctx, chatId, arg ? `${cmd} ${arg}` : cmd, ACK[cmd]);
    return { note: cmd };
  }
  return { note: "unknown", sent: await say(ctx, chatId, "Ye command nahi pata. /menu ya /help dekho.") };
}

async function answerCb(ctx, id, text) {
  try { await tg(ctx, "answerCallbackQuery", Object.assign({ callback_query_id: id }, text ? { text } : {})); } catch (e) { /* ignore */ }
}

async function handleCallback(ctx, cq) {
  const owner = cleanEnv(ctx.env, "OWNER_ID");
  const sender = String((cq.from || {}).id || "");
  if (!owner || sender !== owner) {
    await answerCb(ctx, cq.id, owner ? "Ye bot sirf owner ke liye hai." : "Pehle OWNER_ID set karo.");
    return { note: "callback not allowed" };
  }
  const chatId = (cq.message && cq.message.chat && cq.message.chat.id) || sender;
  const data = String(cq.data || "");
  await answerCb(ctx, cq.id);
  switch (data) {
    case "m:status": await liveReply(ctx, chatId, "/status"); break;
    case "m:sites": await liveReply(ctx, chatId, "/sites"); break;
    case "m:sync": await runOnGitHub(ctx, chatId, "/sync", ACK["/sync"]); break;
    case "m:retry": await runOnGitHub(ctx, chatId, "/retry", ACK["/retry"]); break;
    case "m:help": await say(ctx, chatId, HELP); break;
    case "m:menu": await say(ctx, chatId, "📋 Menu — kya karna hai?", { reply_markup: MENU }); break;
    case "m:add":
      await say(ctx, chatId, `${ADD_PROMPT} (is message ka reply karke).\nJaise: https://meri-site.com 3 5  (3 = ek sync mein max files, 5 = andar ke pages kitne level; dono optional)`,
        { reply_markup: { force_reply: true, input_field_placeholder: "https://…" } });
      break;
    case "m:get":
      await say(ctx, chatId, `${GET_PROMPT} (is message ka reply karke).\nJaise: https://site.com/video.mp4 — sirf direct file link, stream/YouTube nahi.`,
        { reply_markup: { force_reply: true, input_field_placeholder: "https://…/file.mp4" } });
      break;
    case "m:ai":
      if (!cleanEnv(ctx.env, "NVIDIA_API_KEY")) await say(ctx, chatId, AI_OFF);
      else await say(ctx, chatId, `${AI_PROMPT} (is message ka reply karke, ya seedha koi bhi message likh do).`, { reply_markup: { force_reply: true, input_field_placeholder: "Sawal…" } });
      break;
    case "m:rm": {
      const live = await loadLive(ctx);
      if (!live.state) { await say(ctx, chatId, `⚠️ Sites list nahi mili: ${live.error}. /removesite <url> use karo.`); break; }
      const sites = live.state.sites || [];
      if (!sites.length) { await say(ctx, chatId, "Koi site nahi hai hatane ko."); break; }
      const rows = sites.slice(0, 30).map((s) => [{ text: `🗑 ${s.url.replace(/^https?:\/\//, "").slice(0, 50)}`, callback_data: `rm:${shortHash(s.url)}` }]);
      rows.push([{ text: "↩️ Cancel", callback_data: "m:menu" }]);
      await say(ctx, chatId, "Kaunsi site hatani hai?", { reply_markup: { inline_keyboard: rows } });
      break;
    }
    default:
      if (data.startsWith("rm:")) {
        const live = await loadLive(ctx);
        const site = ((live.state && live.state.sites) || []).find((s) => shortHash(s.url) === data.slice(3));
        if (!site) { await say(ctx, chatId, "Ye site ab list mein nahi hai. /sites dekho."); break; }
        await runOnGitHub(ctx, chatId, `/removesite ${site.url}`, `⏳ Hata raha hoon: ${site.url} (~1-2 min)`);
        break;
      }
      await say(ctx, chatId, "Ye button purana hai. /menu se naya kholo.");
  }
  return { note: "callback " + data.split(":")[0] };
}

function makeCtx(opts) {
  return {
    env: opts.env || {},
    fetch: opts.fetch,
    log: opts.log || ((m) => console.log(m)),
    now: opts.now || (() => Date.now()),
  };
}

function createTelegramHandler(opts) {
  const ctx = makeCtx(opts);
  const env = ctx.env;
  return async function handler(req, res) {
    const secret = cleanEnv(env, "WEBHOOK_SECRET");
    if (req.method !== "POST") {
      const need = ["BOT_TOKEN", "WEBHOOK_SECRET", "OWNER_ID", "GH_TOKEN"].filter((k) => !cleanEnv(env, k));
      if (!ghRepo(env)) need.push("GH_REPO");
      const ai = cleanEnv(env, "NVIDIA_API_KEY") ? "AI: on" : "AI: off (NVIDIA_API_KEY nahi hai, optional)";
      return send(res, 200, need.length
        ? `site2tg-bot webhook chal raha hai, par ye env vars missing hain: ${need.join(", ")}\n${ai}`
        : `site2tg-bot webhook chal raha hai ✅ (ye URL Telegram ke liye hai)\n${ai}`);
    }
    if (!secret || !cleanEnv(env, "BOT_TOKEN")) {
      ctx.log("config error: BOT_TOKEN or WEBHOOK_SECRET missing");
      return send(res, 500, "not configured");
    }
    if (!safeEqual(header(req, "x-telegram-bot-api-secret-token"), secret)) {
      ctx.log("rejected: bad or missing secret header");
      return send(res, 401, "unauthorized");
    }
    const update = await readJson(req);
    try {
      if (update && update.callback_query) {
        const r = await handleCallback(ctx, update.callback_query);
        ctx.log(`update: ${r.note}`);
      } else if (update && update.message && update.message.chat) {
        const r = await handleMessage(ctx, update.message);
        ctx.log(`update: ${r.note}`);
      }
    } catch (e) {
      ctx.log("handler error: " + redact(e && e.message, env));
    }
    // always 200 for a verified update, so Telegram doesn't redeliver (and re-dispatch)
    return send(res, 200, "ok");
  };
}

function baseUrl(req, env, query) {
  const override = String(query.url || "").trim();
  let host = override || cleanEnv(env, "VERCEL_PROJECT_PRODUCTION_URL") || header(req, "x-forwarded-host") || header(req, "host") || "";
  host = host.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  return host ? `https://${host}` : "";
}

function createSetupHandler(opts) {
  const ctx = makeCtx(opts);
  const env = ctx.env;
  return async function handler(req, res) {
    const q = new URL(req.url || "/", "http://x").searchParams;
    const query = Object.fromEntries(q.entries());
    const secret = cleanEnv(env, "WEBHOOK_SECRET");
    if (!cleanEnv(env, "BOT_TOKEN") || !secret) {
      return send(res, 500, "Pehle Vercel → Settings → Environment Variables mein BOT_TOKEN aur WEBHOOK_SECRET daalo, phir Redeploy karo.");
    }
    if (!SECRET_RE.test(secret)) {
      return send(res, 500, "WEBHOOK_SECRET mein sirf A-Z, a-z, 0-9, _ aur - ho sakte hain (1-256). Badal ke Redeploy karo.");
    }
    if (!safeEqual(query.key, secret)) {
      ctx.log("setup rejected: bad key");
      return send(res, 403, "Galat key. URL ke end mein ?key=<aapka WEBHOOK_SECRET> lagao.");
    }
    const action = (query.action || "set").toLowerCase();
    try {
      if (action === "set") {
        const base = baseUrl(req, env, query);
        if (!base) return send(res, 500, "Deployment ka URL samajh nahi aaya. &url=aapka-project.vercel.app lagao.");
        const hook = `${base}/api/telegram`;
        await tg(ctx, "setWebhook", { url: hook, secret_token: secret, allowed_updates: ["message", "callback_query"], max_connections: 5 });
        let menu = "✅ Menu button (commands list) set";
        try {
          await tg(ctx, "setMyCommands", { commands: BOT_COMMANDS });
          await tg(ctx, "setChatMenuButton", { menu_button: { type: "commands" } });
        } catch (e) { menu = "⚠️ Menu commands set nahi hue (koi baat nahi, /menu chalega)"; ctx.log("menu setup failed"); }
        const info = await tg(ctx, "getWebhookInfo", {});
        ctx.log("webhook set");
        return send(res, 200, [
          "✅ Webhook set ho gaya!",
          `Telegram ab yahan bhejega: ${info.url || hook}`,
          `Pending updates: ${info.pending_update_count || 0}`,
          menu,
          `AI: ${cleanEnv(env, "NVIDIA_API_KEY") ? "on" : "off (NVIDIA_API_KEY optional)"}`,
          "",
          "Ab bot ko /menu bhejo, turant buttons aane chahiye.",
          "Wapas purane (sirf GitHub, har 10 minute schedule par) mode mein jaana ho toh isi URL mein &action=delete lagao.",
        ].join("\n"));
      }
      if (action === "delete") {
        await tg(ctx, "deleteWebhook", { drop_pending_updates: false });
        ctx.log("webhook deleted");
        return send(res, 200, "✅ Webhook hata diya. Ab bot sirf GitHub Actions se chalega (har run pe commands padhega). Wapas lagana ho toh &action=set.");
      }
      if (action === "info") {
        const info = await tg(ctx, "getWebhookInfo", {});
        const lines = [`Webhook URL: ${info.url || "(koi nahi — polling mode)"}`, `Pending updates: ${info.pending_update_count || 0}`];
        if (info.last_error_message) {
          const when = info.last_error_date ? ist(new Date(info.last_error_date * 1000).toISOString()) : "";
          lines.push(`Last error: ${info.last_error_message} ${when}`);
        }
        return send(res, 200, lines.join("\n"));
      }
      return send(res, 400, "action sirf set, info ya delete ho sakta hai.");
    } catch (e) {
      const m = redact(e.message, env);
      ctx.log("setup failed: " + m);
      return send(res, 502, `Telegram ne mana kiya: ${m}\n(BOT_TOKEN sahi hai? Vercel env check karo.)`);
    }
  };
}

module.exports = {
  createTelegramHandler, createSetupHandler, dispatch, loadLive, formatStatus, formatSites, askAI, snapshot,
  safeEqual, redact, shortHash, ist, HELP, MENU, ADD_PROMPT, AI_PROMPT, GET_PROMPT, SECRET_RE, DEFAULT_NVIDIA_MODEL, FALLBACK_NVIDIA_MODEL,
};
