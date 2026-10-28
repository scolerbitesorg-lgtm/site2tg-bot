// site2tg-bot Vercel front-end (Node, no dependencies).
// Telegram -> POST /api/telegram (this webhook) -> instant reply for cheap
// commands, and for heavy ones a workflow_dispatch of .github/workflows/bot.yml
// with input `command`, so GitHub Actions does the work and replies.
// Secrets come only from Vercel env vars and are never logged or echoed.
"use strict";

const crypto = require("crypto");

const DISPATCH_COMMANDS = ["/addsite", "/removesite", "/sync", "/retry", "/status", "/sites"];
const NEEDS_ARG = { "/addsite": "Aise likho: /addsite https://meri-site.com 3", "/removesite": "Aise likho: /removesite https://meri-site.com" };
const SECRET_RE = /^[A-Za-z0-9_-]{1,256}$/;
const WORKFLOW_FILE = "bot.yml";

const HELP = `🤖 site2tg-bot commands

/addsite <url> [limit] — nayi website jodo (limit = ek sync mein max nayi files, default 3)
/removesite <url> — website hatao
/sites — saari websites ki list
/sync — abhi sync karo
/status — kitni files gayi, last sync, errors
/retry — jo files 3 baar fail hui, unhe dobara try karo
/id — aapka OWNER_ID
/help — ye message

⚡ Bot hamesha online hai: har command ka "mil gaya" turant aata hai. Asli kaam (download/upload, list, status) GitHub pe hota hai, uska jawab 1-3 min mein aata hai.`;

const ACK = {
  "/sync": "✅ Mil gaya, sync GitHub pe start ho raha hai. Nayi files aur result 1-3 min mein aayenge.",
  "/addsite": "✅ Mil gaya, site check karke jod raha hoon. 1-3 min mein confirm aayega, phir files aani shuru.",
  "/removesite": "✅ Mil gaya, site hata raha hoon. 1-3 min mein confirm aayega.",
  "/status": "✅ Mil gaya, status la raha hoon, 1-3 min mein aayega.",
  "/sites": "✅ Mil gaya, list la raha hoon, 1-3 min mein aayegi.",
  "/retry": "✅ Mil gaya, fail hui files dobara try hongi. 1-3 min mein confirm aayega.",
};
const BUSY_NOTE = "\n(Agar pehle se koi sync chal raha hai toh uske khatam hone ke baad hoga.)";

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

function send(res, status, text, type) {
  res.statusCode = status;
  res.setHeader("Content-Type", (type || "text/plain") + "; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(text);
}

// never let a token reach a log line or a chat reply
function redact(text, env) {
  let s = String(text);
  for (const k of ["BOT_TOKEN", "GH_TOKEN", "WEBHOOK_SECRET"]) {
    const v = cleanEnv(env, k);
    if (v.length >= 4) s = s.split(v).join("***");
  }
  return s.replace(/\b\d{6,}:[A-Za-z0-9_-]{30,}\b/g, "***").slice(0, 500);
}

async function tg(fetchFn, env, method, payload) {
  const token = cleanEnv(env, "BOT_TOKEN");
  const r = await fetchFn(`https://api.telegram.org/bot${token}/${method}`, {
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

function ghRepo(env) {
  const repo = cleanEnv(env, "GH_REPO");
  if (repo) return repo;
  const owner = cleanEnv(env, "VERCEL_GIT_REPO_OWNER");
  const slug = cleanEnv(env, "VERCEL_GIT_REPO_SLUG");
  return owner && slug ? `${owner}/${slug}` : "";
}

const DISPATCH_HINT = {
  401: "GH_TOKEN galat hai ya expire ho gaya. Naya token banao aur Vercel env mein daalo (phir Redeploy).",
  403: "GH_TOKEN ko is repo pe \"Actions: Read and write\" permission chahiye.",
  404: "Repo ya workflow nahi mila. GH_REPO check karo (scolerbitesorg-lgtm/site2tg-bot) aur token mein ye repo select hai ya nahi.",
  422: "GitHub ne command accept nahi ki (branch ya workflow inputs). GH_REF / bot.yml check karo.",
};

async function dispatch(fetchFn, env, commandText) {
  const repo = ghRepo(env);
  const token = cleanEnv(env, "GH_TOKEN");
  if (!repo || !token) {
    return { ok: false, why: `Vercel pe ${!token ? "GH_TOKEN" : "GH_REPO"} env var nahi hai. Settings → Environment Variables mein daalo, phir Redeploy.` };
  }
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const body = { ref: cleanEnv(env, "GH_REF") || "main", inputs: { command: String(commandText).slice(0, 1000) } };
  let r;
  try {
    r = await fetchFn(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "site2tg-bot-webhook",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });
  } catch (e) {
    return { ok: false, why: `GitHub tak pahunch nahi paya (${e.name || "network error"}). Thodi der baad dobara bhejo.` };
  }
  if (r.status >= 200 && r.status < 300) return { ok: true, status: r.status };
  return { ok: false, status: r.status, why: DISPATCH_HINT[r.status] || `GitHub ne mana kiya (HTTP ${r.status}).` };
}

function setupReply(msg) {
  const lines = [`👤 Aapka user id (OWNER_ID): ${(msg.from || {}).id}`];
  const origin = msg.forward_origin || {};
  const chat = origin.chat || msg.forward_from_chat || {};
  if (chat.id) lines.push(`📢 Channel id (CHANNEL_ID): ${chat.id}  (${chat.title || ""})`);
  else lines.push("Channel id ke liye: apne channel ki koi bhi post is bot ko forward karo.");
  lines.push("OWNER_ID ko GitHub Secrets aur Vercel env vars dono mein daalo, CHANNEL_ID sirf GitHub Secrets mein. Phir Vercel pe Redeploy.");
  return lines.join("\n");
}

// Decide what to do with one Telegram update. Returns
// { reply: string|null, dispatch: string|null, note } — pure, no network.
function decide(update, env) {
  const msg = (update && (update.message || update.edited_message)) || null;
  if (!msg || !msg.chat) return { reply: null, dispatch: null, note: "no message" };
  if (update.edited_message) return { reply: null, dispatch: null, note: "edited message ignored" };
  const owner = cleanEnv(env, "OWNER_ID");
  const sender = String((msg.from || {}).id || "");
  if (!owner) return { reply: setupReply(msg), dispatch: null, note: "setup mode" };
  if (sender !== owner) return { reply: null, dispatch: null, note: "non-owner ignored" };

  const text = String(msg.text || "").trim();
  const origin = msg.forward_origin || {};
  const fchat = origin.chat || msg.forward_from_chat || {};
  if (!text.startsWith("/")) {
    if (fchat.id) return { reply: `📢 Is channel ki id (CHANNEL_ID): ${fchat.id}  (${fchat.title || ""})`, dispatch: null, note: "channel id" };
    return { reply: "Commands ke liye /help bhejo.", dispatch: null, note: "plain text" };
  }
  const parts = text.split(/\s+/);
  const cmd = parts[0].split("@")[0].toLowerCase();
  const arg = text.slice(parts[0].length).trim();
  if (cmd === "/start" || cmd === "/help") return { reply: HELP, dispatch: null, note: cmd };
  if (cmd === "/id") {
    const ch = cleanEnv(env, "CHANNEL_ID");
    return { reply: `OWNER_ID: ${owner}\nCHANNEL_ID: ${ch || "(GitHub Secrets mein hai)"}`, dispatch: null, note: cmd };
  }
  if (DISPATCH_COMMANDS.includes(cmd)) {
    if (NEEDS_ARG[cmd] && !arg) return { reply: NEEDS_ARG[cmd], dispatch: null, note: "usage" };
    const normalized = arg ? `${cmd} ${arg}` : cmd;
    return { reply: ACK[cmd] + BUSY_NOTE, dispatch: normalized, note: cmd };
  }
  return { reply: "Ye command nahi pata. /help dekho.", dispatch: null, note: "unknown" };
}

function createTelegramHandler({ env, fetch: fetchFn, log }) {
  const logger = log || ((m) => console.log(m));
  return async function handler(req, res) {
    const secret = cleanEnv(env, "WEBHOOK_SECRET");
    if (req.method !== "POST") {
      const need = ["BOT_TOKEN", "WEBHOOK_SECRET", "OWNER_ID", "GH_TOKEN"].filter((k) => !cleanEnv(env, k));
      if (!ghRepo(env)) need.push("GH_REPO");
      return send(res, 200, need.length
        ? `site2tg-bot webhook chal raha hai, par ye env vars missing hain: ${need.join(", ")}`
        : "site2tg-bot webhook chal raha hai ✅ (ye URL Telegram ke liye hai)");
    }
    if (!secret || !cleanEnv(env, "BOT_TOKEN")) {
      logger("config error: BOT_TOKEN or WEBHOOK_SECRET missing");
      return send(res, 500, "not configured");
    }
    if (!safeEqual(header(req, "x-telegram-bot-api-secret-token"), secret)) {
      logger("rejected: bad or missing secret header");
      return send(res, 401, "unauthorized");
    }
    const update = await readJson(req);
    if (!update) return send(res, 200, "ok");
    const d = decide(update, env);
    const chatId = update.message && update.message.chat && update.message.chat.id;
    let reply = d.reply;
    if (d.dispatch) {
      const r = await dispatch(fetchFn, env, d.dispatch);
      logger(`dispatch ${d.note}: ${r.ok ? "ok" : "failed " + (r.status || "")}`);
      if (!r.ok) reply = `⚠️ Command GitHub tak nahi gayi: ${r.why}`;
    } else {
      logger(`update: ${d.note}`);
    }
    if (reply && chatId !== undefined) {
      try {
        await tg(fetchFn, env, "sendMessage", { chat_id: chatId, text: reply.slice(0, 4000), disable_web_page_preview: true });
      } catch (e) {
        logger("reply failed: " + redact(e.message, env));
      }
    }
    // always 200 for a verified update, so Telegram doesn't redeliver (and re-dispatch)
    return send(res, 200, "ok");
  };
}

const BOT_COMMANDS = [
  ["addsite", "nayi website jodo"], ["removesite", "website hatao"], ["sites", "saari websites"],
  ["sync", "abhi sync karo"], ["status", "status dekho"], ["retry", "fail files dobara"],
  ["id", "apna id"], ["help", "help"],
].map(([command, description]) => ({ command, description }));

function baseUrl(req, env, query) {
  const override = String(query.url || "").trim();
  let host = override || cleanEnv(env, "VERCEL_PROJECT_PRODUCTION_URL") || header(req, "x-forwarded-host") || header(req, "host") || "";
  host = host.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  return host ? `https://${host}` : "";
}

function createSetupHandler({ env, fetch: fetchFn, log }) {
  const logger = log || ((m) => console.log(m));
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
      logger("setup rejected: bad key");
      return send(res, 403, "Galat key. URL ke end mein ?key=<aapka WEBHOOK_SECRET> lagao.");
    }
    const action = (query.action || "set").toLowerCase();
    try {
      if (action === "set") {
        const base = baseUrl(req, env, query);
        if (!base) return send(res, 500, "Deployment ka URL samajh nahi aaya. &url=aapka-project.vercel.app lagao.");
        const hook = `${base}/api/telegram`;
        await tg(fetchFn, env, "setWebhook", { url: hook, secret_token: secret, allowed_updates: ["message"], max_connections: 5 });
        try { await tg(fetchFn, env, "setMyCommands", { commands: BOT_COMMANDS }); } catch (e) { logger("setMyCommands failed"); }
        const info = await tg(fetchFn, env, "getWebhookInfo", {});
        logger("webhook set");
        return send(res, 200, [
          "✅ Webhook set ho gaya!",
          `Telegram ab yahan bhejega: ${info.url || hook}`,
          `Pending updates: ${info.pending_update_count || 0}`,
          "",
          "Ab bot ko /help bhejo, turant jawab aana chahiye.",
          "Wapas purane (sirf GitHub, har ghante) mode mein jaana ho toh isi URL mein &action=delete lagao.",
        ].join("\n"));
      }
      if (action === "delete") {
        await tg(fetchFn, env, "deleteWebhook", { drop_pending_updates: false });
        logger("webhook deleted");
        return send(res, 200, "✅ Webhook hata diya. Ab bot sirf GitHub Actions se chalega (har run pe commands padhega). Wapas lagana ho toh &action=set.");
      }
      if (action === "info") {
        const info = await tg(fetchFn, env, "getWebhookInfo", {});
        const lines = [`Webhook URL: ${info.url || "(koi nahi — polling mode)"}`, `Pending updates: ${info.pending_update_count || 0}`];
        if (info.last_error_message) {
          const when = info.last_error_date ? new Date(info.last_error_date * 1000).toISOString() : "";
          lines.push(`Last error: ${info.last_error_message} ${when}`);
        }
        return send(res, 200, lines.join("\n"));
      }
      return send(res, 400, "action sirf set, info ya delete ho sakta hai.");
    } catch (e) {
      const m = redact(e.message, env);
      logger("setup failed: " + m);
      return send(res, 502, `Telegram ne mana kiya: ${m}\n(BOT_TOKEN sahi hai? Vercel env check karo.)`);
    }
  };
}

module.exports = { decide, dispatch, createTelegramHandler, createSetupHandler, safeEqual, redact, HELP, DISPATCH_COMMANDS, SECRET_RE };
