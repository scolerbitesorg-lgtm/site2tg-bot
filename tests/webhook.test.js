// Webhook tests (mocked HTTP): node --test tests/webhook.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const W = require("../lib/webhook");
const { createTelegramHandler, createSetupHandler, formatStatus, shortHash, snapshot } = W;

const ENV = {
  BOT_TOKEN: "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
  OWNER_ID: "111",
  GH_TOKEN: "github_pat_TESTTOKEN123",
  GH_REPO: "scolerbitesorg-lgtm/site2tg-bot",
  WEBHOOK_SECRET: "s3cret_value-1",
};
const NOW = Date.parse("2026-10-28T09:00:00Z");

const STATE = {
  sites: [
    { url: "https://f-droid.org/en/packages/org.fdroid.fdroid/", adapter: "generic", limit: 3 },
    { url: "https://videoclasses.vercel.app/", adapter: "tgvideo", limit: 5 },
    { url: "https://my.site/files/", adapter: "generic", limit: 3, depth: 5 },
  ],
  sent: { "https://f-droid.org/en/packages/org.fdroid.fdroid/": ["a", "b", "c"] },
  files_sent_total: 3,
  last_sync: "2026-10-28T08:32:00Z",
  last_result: "3 bheji, 0 fail, 0 badi files ruki",
  big_pending: { "x:9": { site: "s", name: "lecture.mp4", size: 90000000 } },
  fails: { "x:1": 3, "x:2": 1 },
  errors: [{ at: "2026-10-28T08:30:00Z", msg: "https://e.com: list failed: HTTP 500" }],
  sync_requested: false,
};
const RUNS = [
  { status: "in_progress", conclusion: null, display_title: "cmd /sync", event: "workflow_dispatch", created_at: "2026-10-28T08:58:00Z", run_started_at: "2026-10-28T08:58:10Z" },
  { status: "completed", conclusion: "success", display_title: "site2tg-bot", event: "schedule", created_at: "2026-10-28T08:17:00Z", updated_at: "2026-10-28T08:18:00Z" },
];

// default fake internet: Telegram ok, GitHub dispatch 204, repo reads ok
function net(over) {
  return (c) => {
    if (over) { const r = over(c); if (r) return r; }
    if (c.url.startsWith("https://api.telegram.org/")) return { json: { ok: true, result: c.url.endsWith("/sendMessage") ? { message_id: 501 } : true } };
    if (c.url.endsWith("/dispatches")) return { status: 204, json: null };
    if (c.url.includes("/contents/state.json")) return { text: JSON.stringify(STATE) };
    if (c.url.includes("/runs?")) return { json: { workflow_runs: RUNS } };
    return { status: 599 };
  };
}

function mockFetch(responder) {
  const calls = [];
  const fn = async (url, opts) => {
    const call = { url, opts, method: (opts && opts.method) || "GET", body: opts && opts.body ? JSON.parse(opts.body) : null };
    calls.push(call);
    const r = (responder && responder(call)) || {};
    if (r.throw) throw r.throw;
    const status = r.status || 200;
    return {
      status,
      json: async () => (r.json !== undefined ? r.json : JSON.parse(r.text || "{}")),
      text: async () => (r.text !== undefined ? r.text : JSON.stringify(r.json || {})),
    };
  };
  fn.calls = calls;
  return fn;
}

function mockRes() {
  return { statusCode: 0, headers: {}, body: "", setHeader(k, v) { this.headers[k.toLowerCase()] = v; }, end(b) { this.body = b || ""; } };
}

function msg(text, uid, extra) {
  return { update_id: 1, message: Object.assign({ message_id: 5, text, from: { id: uid }, chat: { id: uid, type: "private" } }, extra || {}) };
}
function cb(data, uid) {
  return { update_id: 2, callback_query: { id: "cbq1", data, from: { id: uid }, message: { message_id: 9, chat: { id: uid } } } };
}

async function run(env, update, secret, over) {
  const f = mockFetch(net(over));
  const logs = [];
  const res = mockRes();
  const r = { method: "POST", headers: secret === undefined ? {} : { "x-telegram-bot-api-secret-token": secret }, body: update };
  await createTelegramHandler({ env, fetch: f, log: (m) => logs.push(m), now: () => NOW })(r, res);
  const tgCalls = (m) => f.calls.filter((c) => c.url.endsWith("/" + m));
  return { res, calls: f.calls, logs, tg: tgCalls, sent: tgCalls("sendMessage").map((c) => c.body) };
}
const S = ENV.WEBHOOK_SECRET;

// ---------------------------------------------------------------- auth

test("rejects a request without the right secret header", async () => {
  for (const s of [undefined, "", "wrong", S + "x"]) {
    const { res, calls } = await run(ENV, msg("/sync", 111), s);
    assert.strictEqual(res.statusCode, 401);
    assert.strictEqual(calls.length, 0);
  }
});

test("500 when WEBHOOK_SECRET or BOT_TOKEN missing (never accept unauthenticated)", async () => {
  const { res, calls } = await run(Object.assign({}, ENV, { WEBHOOK_SECRET: "" }), msg("/sync", 111), "");
  assert.strictEqual(res.statusCode, 500);
  assert.strictEqual(calls.length, 0);
});

test("non-owner messages and buttons are ignored", async () => {
  let r = await run(ENV, msg("/sync", 999), S);
  assert.strictEqual(r.res.statusCode, 200);
  assert.strictEqual(r.calls.length, 0);
  r = await run(ENV, cb("m:sync", 999), S);
  assert.ok(r.calls.every((c) => !c.url.includes("github")));
  assert.strictEqual(r.tg("answerCallbackQuery").length, 1);
  assert.strictEqual(r.sent.length, 0);
});

// ---------------------------------------------------------------- instant replies + menu

test("/start, /menu, /help reply instantly with the inline menu, no GitHub call", async () => {
  for (const c of ["/start", "/menu", "/help", "/menu@MyBot"]) {
    const { sent, calls } = await run(ENV, msg(c, 111), S);
    assert.strictEqual(calls.length, 1, c);
    assert.strictEqual(sent[0].chat_id, 111);
    const kb = sent[0].reply_markup.inline_keyboard.flat().map((b) => b.callback_data);
    assert.deepStrictEqual(kb.sort(), ["m:add", "m:ai", "m:get", "m:help", "m:retry", "m:rm", "m:sites", "m:status", "m:sync", "m:addplaylist", "m:addyoutube", "m:youtubes", "m:removeyoutube", "m:yt"].sort());
  }
});

test("/id replies with owner id", async () => {
  const { sent } = await run(ENV, msg("/id", 111), S);
  assert.match(sent[0].text, /OWNER_ID: 111/);
});

// ---------------------------------------------------------------- live status from the repo

test("/status is answered from the repo instantly (state.json + runs), no dispatch", async () => {
  const { sent, calls } = await run(ENV, msg("/status", 111), S);
  const st = calls.find((c) => c.url.includes("/contents/state.json"));
  assert.strictEqual(st.url, "https://api.github.com/repos/scolerbitesorg-lgtm/site2tg-bot/contents/state.json?ref=main");
  assert.strictEqual(st.opts.headers.Accept, "application/vnd.github.raw+json");
  assert.strictEqual(st.opts.headers.Authorization, "Bearer " + ENV.GH_TOKEN);
  assert.ok(calls.some((c) => c.url === "https://api.github.com/repos/scolerbitesorg-lgtm/site2tg-bot/actions/workflows/bot.yml/runs?per_page=6"));
  assert.ok(!calls.some((c) => c.url.endsWith("/dispatches")));
  const t = sent[0].text;
  assert.match(t, /Live status/);
  assert.match(t, /Websites: 3/);
  assert.match(t, /Total files bheji: 3/);
  assert.match(t, /Last sync: 28 Oct 02:02 PM IST \(28 min pehle\)/);
  assert.match(t, /lecture\.mp4 \(85\.8 MB\)/);
  assert.match(t, /1 files 3 baar fail/);
  assert.match(t, /HTTP 500/);
  assert.match(t, /abhi 1 run chal/);
  assert.match(t, /▶️ \/sync — chal raha hai \(2 min pehle start\)/);
  assert.match(t, /✅ auto sync — 28 Oct 01:48 PM IST \(success\)/);
});

test("/sites lists sites with counts", async () => {
  const { sent } = await run(ENV, msg("/sites", 111), S);
  assert.match(sent[0].text, /1\. https:\/\/f-droid\.org\/en\/packages\/org\.fdroid\.fdroid\/ \(generic, max 3\/sync\) — 3 files bheji/);
  assert.match(sent[0].text, /2\. https:\/\/videoclasses\.vercel\.app\/ \(tgvideo, max 5\/sync\) — 0 files bheji/);
  assert.match(sent[0].text, /3\. https:\/\/my\.site\/files\/ \(generic, max 3\/sync, 5 level andar\) — 0 files bheji/);
});

test("status read failing (token without Contents: read) falls back to a GitHub run", async () => {
  const { sent, calls } = await run(ENV, msg("/status", 111), S, (c) => (c.url.includes("api.github.com") && c.method === "GET" ? { status: 403 } : null));
  assert.match(sent[0].text, /Contents: Read/);
  const d = calls.find((c) => c.url.endsWith("/dispatches"));
  assert.deepStrictEqual(d.body.inputs, { command: "/status", ack_message_id: "501" });
});

test("status with state but runs unreadable still answers", () => {
  const t = formatStatus({ state: STATE, runs: null, runsError: "runs padh nahi paya: x" }, NOW);
  assert.match(t, /Websites: 3/);
  assert.match(t, /runs padh nahi paya/);
});

// ---------------------------------------------------------------- state-changing → ⏳ + dispatch

test("action commands: ⏳ message first, then dispatch bot.yml with command + ack_message_id", async () => {
  const { calls } = await run(ENV, msg("/addsite https://my.site 5", 111), S);
  assert.strictEqual(calls.length, 2);
  assert.match(calls[0].url, /\/sendMessage$/);
  assert.match(calls[0].body.text, /^⏳/);
  const gh = calls[1];
  assert.strictEqual(gh.url, "https://api.github.com/repos/scolerbitesorg-lgtm/site2tg-bot/actions/workflows/bot.yml/dispatches");
  assert.strictEqual(gh.opts.method, "POST");
  assert.strictEqual(gh.opts.headers.Authorization, "Bearer " + ENV.GH_TOKEN);
  assert.strictEqual(gh.opts.headers.Accept, "application/vnd.github+json");
  assert.strictEqual(gh.opts.headers["X-GitHub-Api-Version"], "2022-11-28");
  assert.ok(gh.opts.headers["User-Agent"]);
  assert.deepStrictEqual(gh.body, { ref: "main", inputs: { command: "/addsite https://my.site 5", ack_message_id: "501" } });
});

test("each action command is forwarded; @suffix stripped; usage when url missing", async () => {
  for (const [c, want] of [["/sync", "/sync"], ["/retry", "/retry"], ["/removesite x.com", "/removesite x.com"], ["/SYNC@MyBot", "/sync"]]) {
    const { calls } = await run(ENV, msg(c, 111), S);
    assert.strictEqual(calls.find((k) => k.url.endsWith("/dispatches")).body.inputs.command, want);
  }
  for (const c of ["/addsite", "/removesite"]) {
    const { calls, sent } = await run(ENV, msg(c, 111), S);
    assert.strictEqual(calls.length, 1);
    assert.match(sent[0].text, /Aise likho/);
  }
});

test("GH_REF overrides branch; GH_REPO falls back to Vercel git env", async () => {
  const env = Object.assign({}, ENV, { GH_REPO: "", GH_REF: "dev", VERCEL_GIT_REPO_OWNER: "o", VERCEL_GIT_REPO_SLUG: "r" });
  const { calls } = await run(env, msg("/sync", 111), S);
  const d = calls.find((k) => k.url.endsWith("/dispatches"));
  assert.strictEqual(d.url, "https://api.github.com/repos/o/r/actions/workflows/bot.yml/dispatches");
  assert.strictEqual(d.body.ref, "dev");
});

test("dispatch failure edits the ⏳ message into an explanation, token never leaked", async () => {
  for (const [status, re] of [[401, /GH_TOKEN galat/], [403, /Read and write/], [404, /GH_REPO/], [422, /accept nahi/]]) {
    const { res, tg, logs } = await run(ENV, msg("/sync", 111), S,
      (c) => (c.url.endsWith("/dispatches") ? { status, json: { message: "nope " + ENV.GH_TOKEN } } : null));
    assert.strictEqual(res.statusCode, 200);
    const e = tg("editMessageText")[0].body;
    assert.strictEqual(e.message_id, 501);
    assert.match(e.text, /^⚠️ Command GitHub tak nahi gayi/);
    assert.match(e.text, re);
    assert.ok(!e.text.includes(ENV.GH_TOKEN) && !logs.join("\n").includes(ENV.GH_TOKEN));
  }
});

test("missing GH_TOKEN is reported, nothing sent to GitHub", async () => {
  const { calls, tg } = await run(Object.assign({}, ENV, { GH_TOKEN: "" }), msg("/sync", 111), S);
  assert.ok(!calls.some((c) => c.url.includes("github")));
  assert.match(tg("editMessageText")[0].body.text, /GH_TOKEN env var nahi hai/);
});

// ---------------------------------------------------------------- buttons (callback_query)

test("buttons: status/sync/retry/help each do the right thing and stop the spinner", async () => {
  let r = await run(ENV, cb("m:status", 111), S);
  assert.strictEqual(r.tg("answerCallbackQuery")[0].body.callback_query_id, "cbq1");
  assert.match(r.sent[0].text, /Live status/);
  r = await run(ENV, cb("m:sync", 111), S);
  assert.strictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/sync");
  r = await run(ENV, cb("m:retry", 111), S);
  assert.strictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/retry");
  r = await run(ENV, cb("m:help", 111), S);
  assert.match(r.sent[0].text, /site2tg-bot/);
  r = await run(ENV, cb("m:sites", 111), S);
  assert.match(r.sent[0].text, /Websites:/);
});

test("➕ Add site asks for a URL (force_reply) and the reply becomes /addsite", async () => {
  let r = await run(ENV, cb("m:add", 111), S);
  const prompt = r.sent[0];
  assert.ok(prompt.text.startsWith(W.ADD_PROMPT));
  assert.strictEqual(prompt.reply_markup.force_reply, true);
  r = await run(ENV, msg("https://new.site 4", 111, { reply_to_message: { message_id: 8, from: { id: 1, is_bot: true }, text: prompt.text } }), S);
  assert.deepStrictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs, { command: "/addsite https://new.site 4", ack_message_id: "501" });
  r = await run(ENV, msg("hello there", 111, { reply_to_message: { message_id: 8, from: { id: 1, is_bot: true }, text: prompt.text } }), S);
  assert.match(r.sent[0].text, /URL nahi lag raha/);
  assert.ok(!r.calls.some((c) => c.url.endsWith("/dispatches")));
});

test("🗑 Remove site lists sites as buttons; tapping one dispatches /removesite <exact url>", async () => {
  let r = await run(ENV, cb("m:rm", 111), S);
  const rows = r.sent[0].reply_markup.inline_keyboard;
  assert.strictEqual(rows.length, 4); // 3 sites + cancel
  const data = rows[1][0].callback_data;
  assert.strictEqual(data, "rm:" + shortHash("https://videoclasses.vercel.app/"));
  assert.ok(Buffer.byteLength(data) <= 64);
  r = await run(ENV, cb(data, 111), S);
  assert.strictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/removesite https://videoclasses.vercel.app/");
  r = await run(ENV, cb("rm:deadbeef00", 111), S);
  assert.match(r.sent[0].text, /ab list mein nahi/);
});

test("YouTube menu buttons ask for input and reply dispatches the matching command", async () => {
  const cases = [
    ["m:addplaylist", "📺 Public YouTube playlist", "https://www.youtube.com/playlist?list=PL1234567890abcd", "/addplaylist https://www.youtube.com/playlist?list=PL1234567890abcd"],
    ["m:addyoutube", "▶️ Public YouTube channel", "https://www.youtube.com/@sample", "/addyoutube https://www.youtube.com/@sample"],
    ["m:removeyoutube", "🗑 Tracked YouTube playlist/channel", "PL1234567890abcd", "/removeyoutube PL1234567890abcd"],
    ["m:yt", "🔗 YouTube video", "https://www.youtube.com/watch?v=abcdefghijk", "/yt https://www.youtube.com/watch?v=abcdefghijk"],
  ];
  for (const [button, promptStart, value, command] of cases) {
    const opened = await run(ENV, cb(button, 111), S);
    const prompt = opened.sent[0];
    assert.ok(prompt.text.startsWith(promptStart), button);
    assert.strictEqual(prompt.reply_markup.force_reply, true, button);
    const replied = await run(ENV, msg(value, 111, {
      reply_to_message: { message_id: 8, from: { id: 1, is_bot: true }, text: prompt.text },
    }), S);
    assert.strictEqual(replied.calls.find((call) => call.url.endsWith("/dispatches")).body.inputs.command, command, button);
  }
});

test("YouTube trackers button and /youtubes answer live from state.json (no GitHub run)", async () => {
  const over = (c) => (c.url.includes("/contents/state.json") ? { text: JSON.stringify(Object.assign({}, STATE, {
    youtube_sources: [{ kind: "playlist", id: "PL1234567890abcd", url: "https://www.youtube.com/playlist?list=PL1234567890abcd" }],
    youtube_seen: { "playlist:PL1234567890abcd": ["a", "b"] }, youtube_pending: { "playlist:PL1234567890abcd": [{ id: "c" }] },
  })) } : null);
  for (const u of [cb("m:youtubes", 111), msg("/youtubes", 111)]) {
    const r = await run(ENV, u, S, over);
    assert.ok(!r.calls.some((c) => c.url.endsWith("/dispatches")));
    assert.match(r.sent[0].text, /Playlist — https:\/\/www\.youtube\.com\/playlist\?list=PL1234567890abcd\n {3}Post hue: 2 · line mein: 1/);
  }
});

test("unknown/old button gets a gentle message", async () => {
  const r = await run(ENV, cb("zzz", 111), S);
  assert.match(r.sent[0].text, /purana hai/);
});

// ---------------------------------------------------------------- AI

const AI_ENV = Object.assign({}, ENV, { NVIDIA_API_KEY: "nvapi-TESTKEY1234567890" });

test("AI off: plain text and 🤖 button explain how to enable, no NVIDIA call", async () => {
  let r = await run(ENV, msg("kitni files gayi?", 111), S);
  assert.match(r.sent[0].text, /NVIDIA_API_KEY/);
  assert.ok(!r.calls.some((c) => c.url.includes("nvidia")));
  r = await run(ENV, cb("m:ai", 111), S);
  assert.match(r.sent[0].text, /build\.nvidia\.com/);
});

test("AI on: question + live status snapshot go to NVIDIA chat completions, answer relayed", async () => {
  const r = await run(AI_ENV, msg("kitni files gayi?", 111), S,
    (c) => (c.url.includes("nvidia") ? { json: { choices: [{ message: { content: "Abhi tak 3 files gayi hain 👍" } }] } } : null));
  const ai = r.calls.find((c) => c.url.includes("nvidia"));
  assert.strictEqual(ai.url, "https://integrate.api.nvidia.com/v1/chat/completions");
  assert.strictEqual(ai.opts.headers.Authorization, "Bearer " + AI_ENV.NVIDIA_API_KEY);
  assert.strictEqual(ai.body.model, W.DEFAULT_NVIDIA_MODEL);
  assert.strictEqual(ai.body.messages[0].role, "system");
  assert.match(ai.body.messages[0].content, /khud koi action nahi/);
  const user = ai.body.messages[1].content;
  assert.match(user, /"files_sent_total":3/);
  assert.match(user, /lecture\.mp4/);
  assert.match(user, /Sawal: kitni files gayi\?/);
  assert.ok(!user.includes(ENV.GH_TOKEN) && !user.includes(ENV.BOT_TOKEN));
  assert.strictEqual(r.tg("sendChatAction").length, 1);
  assert.strictEqual(r.sent[0].text, "Abhi tak 3 files gayi hain 👍");
});

test("AI: NVIDIA_MODEL / NVIDIA_BASE_URL respected; 404 model falls back once", async () => {
  const env = Object.assign({}, AI_ENV, { NVIDIA_MODEL: "x/missing", NVIDIA_BASE_URL: "https://my.nim/v1/" });
  const r = await run(env, msg("hi", 111), S, (c) => {
    if (!c.url.startsWith("https://my.nim/")) return null;
    return c.body.model === "x/missing" ? { status: 404 } : { json: { choices: [{ message: { content: "ok" } }] } };
  });
  const ai = r.calls.filter((c) => c.url === "https://my.nim/v1/chat/completions");
  assert.deepStrictEqual(ai.map((c) => c.body.model), ["x/missing", W.FALLBACK_NVIDIA_MODEL]);
  assert.strictEqual(r.sent[0].text, "ok");
});

test("AI errors become friendly messages (timeout, bad key, rate limit), key never leaked", async () => {
  const timeout = Object.assign(new Error("t"), { name: "TimeoutError" });
  for (const [over, re] of [[{ throw: timeout }, /time pe jawab nahi/], [{ status: 401 }, /NVIDIA_API_KEY galat/], [{ status: 429 }, /free limit/], [{ status: 500 }, /HTTP 500/], [{ json: { choices: [] } }, /khaali/]]) {
    const r = await run(AI_ENV, msg("hi", 111), S, (c) => (c.url.includes("nvidia") ? over : null));
    assert.match(r.sent[0].text, re);
    assert.ok(!JSON.stringify(r.sent).includes(AI_ENV.NVIDIA_API_KEY));
  }
});

test("/ai <question> works; plain text that is a forwarded channel post gives channel id instead", async () => {
  let r = await run(AI_ENV, msg("/ai status kya hai", 111), S, (c) => (c.url.includes("nvidia") ? { json: { choices: [{ message: { content: "sab theek" } }] } } : null));
  assert.match(r.calls.find((c) => c.url.includes("nvidia")).body.messages[1].content, /Sawal: status kya hai/);
  r = await run(AI_ENV, msg("", 111, { forward_origin: { type: "channel", chat: { id: -1005, title: "C" } } }), S);
  assert.match(r.sent[0].text, /-1005/);
  assert.ok(!r.calls.some((c) => c.url.includes("nvidia")));
});

test("snapshot stays compact", () => {
  const big = Object.assign({}, STATE, { errors: Array.from({ length: 50 }, (_, i) => ({ at: "2026-10-28T08:00:00Z", msg: "e".repeat(400) + i })) });
  assert.ok(snapshot({ state: big, runs: RUNS }, NOW).length <= 3500);
});

// ---------------------------------------------------------------- setup mode + misc

test("setup mode (no OWNER_ID): anyone gets their user id, forwarded channel post gives channel id", async () => {
  const env = Object.assign({}, ENV, { OWNER_ID: "" });
  let r = await run(env, msg("/start", 42), S);
  assert.match(r.sent[0].text, /OWNER_ID\): 42/);
  assert.match(r.sent[0].text, /post is bot ko forward karo/);
  const fwd = { update_id: 2, message: { message_id: 6, from: { id: 42 }, chat: { id: 42 }, forward_origin: { type: "channel", chat: { id: -1009876, title: "Backup" } } } };
  r = await run(env, fwd, S);
  assert.match(r.sent[0].text, /CHANNEL_ID\): -1009876/);
  r = await run(env, msg("/sync", 42), S);
  assert.ok(r.calls.every((c) => !c.url.includes("github")), "no dispatch in setup mode");
});

test("raw JSON string body and streamed body both work", async () => {
  const f = mockFetch(net());
  let res = mockRes();
  await createTelegramHandler({ env: ENV, fetch: f, log: () => {} })({ method: "POST", headers: { "x-telegram-bot-api-secret-token": S }, body: JSON.stringify(msg("/sync", 111)) }, res);
  assert.strictEqual(f.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/sync");
  const { Readable } = require("node:stream");
  const rs = Readable.from([Buffer.from(JSON.stringify(msg("/retry", 111)))]);
  rs.method = "POST";
  rs.headers = { "x-telegram-bot-api-secret-token": S };
  const f2 = mockFetch(net());
  res = mockRes();
  await createTelegramHandler({ env: ENV, fetch: f2, log: () => {} })(rs, res);
  assert.strictEqual(f2.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/retry");
});

test("a crash inside handling still answers 200 (so Telegram doesn't re-deliver)", async () => {
  const { res } = await run(ENV, msg("/sync", 111), S, (c) => (c.url.includes("telegram") ? { throw: new Error("boom") } : null));
  assert.strictEqual(res.statusCode, 200);
});

test("GET on webhook is a health check listing missing env names only", async () => {
  const res = mockRes();
  await createTelegramHandler({ env: Object.assign({}, ENV, { GH_TOKEN: "" }), fetch: mockFetch(), log: () => {} })({ method: "GET", headers: {} }, res);
  assert.strictEqual(res.statusCode, 200);
  assert.match(res.body, /GH_TOKEN/);
  assert.match(res.body, /AI: off/);
  assert.ok(!res.body.includes(ENV.BOT_TOKEN));
});

// ---------------------------------------------------------------- /api/setup

async function setup(env, url, headers, over) {
  const f = mockFetch(over || net());
  const res = mockRes();
  await createSetupHandler({ env, fetch: f, log: () => {} })({ method: "GET", url, headers: headers || {} }, res);
  return { res, calls: f.calls };
}

test("setup needs the right key", async () => {
  for (const u of ["/api/setup", "/api/setup?key=nope"]) {
    const { res, calls } = await setup(ENV, u);
    assert.strictEqual(res.statusCode, 403);
    assert.strictEqual(calls.length, 0);
  }
});

test("setup sets webhook (message + callback_query) on the production URL, plus the command menu", async () => {
  const env = Object.assign({}, ENV, { VERCEL_PROJECT_PRODUCTION_URL: "site2tg-bot.vercel.app" });
  const { res, calls } = await setup(env, "/api/setup?key=" + S, { host: "site2tg-bot-abc123.vercel.app" },
    (c) => (c.url.endsWith("getWebhookInfo") ? { json: { ok: true, result: { url: "https://site2tg-bot.vercel.app/api/telegram", pending_update_count: 2 } } } : { json: { ok: true, result: true } }));
  assert.strictEqual(res.statusCode, 200);
  const set = calls.find((c) => c.url.endsWith("/setWebhook"));
  assert.deepStrictEqual(set.body, { url: "https://site2tg-bot.vercel.app/api/telegram", secret_token: S, allowed_updates: ["message", "callback_query"], max_connections: 5 });
  const cmds = calls.find((c) => c.url.endsWith("/setMyCommands")).body.commands.map((c) => c.command);
  assert.deepStrictEqual(cmds, ["menu", "status", "sites", "ai", "get", "addsite", "removesite", "sync", "addplaylist", "addyoutube", "youtubes", "removeyoutube", "yt", "retry", "id", "help"]);
  assert.deepStrictEqual(calls.find((c) => c.url.endsWith("/setChatMenuButton")).body, { menu_button: { type: "commands" } });
  assert.match(res.body, /Webhook set ho gaya/);
  assert.ok(!res.body.includes(S) && !res.body.includes(ENV.BOT_TOKEN));
});

test("setup falls back to host header, and &url= override", async () => {
  let r = await setup(ENV, "/api/setup?key=" + S, { "x-forwarded-host": "abc.vercel.app" });
  assert.strictEqual(r.calls[0].body.url, "https://abc.vercel.app/api/telegram");
  r = await setup(ENV, "/api/setup?key=" + S + "&url=https://my.domain/", { host: "abc.vercel.app" });
  assert.strictEqual(r.calls[0].body.url, "https://my.domain/api/telegram");
});

test("setup delete and info", async () => {
  let r = await setup(ENV, "/api/setup?key=" + S + "&action=delete");
  assert.ok(r.calls[0].url.endsWith("/deleteWebhook"));
  assert.match(r.res.body, /Webhook hata diya/);
  r = await setup(ENV, "/api/setup?key=" + S + "&action=info", {},
    () => ({ json: { ok: true, result: { url: "", pending_update_count: 0, last_error_message: "Wrong response from the webhook: 401 Unauthorized", last_error_date: 1761640000 } } }));
  assert.match(r.res.body, /polling mode/);
  assert.match(r.res.body, /401 Unauthorized/);
});

test("setup rejects a WEBHOOK_SECRET Telegram won't accept", async () => {
  const bad = "has space!";
  const { res, calls } = await setup(Object.assign({}, ENV, { WEBHOOK_SECRET: bad }), "/api/setup?key=" + encodeURIComponent(bad));
  assert.strictEqual(res.statusCode, 500);
  assert.strictEqual(calls.length, 0);
});

test("Telegram error during setup is shown without the token", async () => {
  const { res } = await setup(ENV, "/api/setup?key=" + S, { host: "a.vercel.app" },
    () => ({ json: { ok: false, error_code: 401, description: "Unauthorized " + ENV.BOT_TOKEN } }));
  assert.strictEqual(res.statusCode, 502);
  assert.ok(!res.body.includes(ENV.BOT_TOKEN));
  assert.match(res.body, /401/);
});

// ---------------------------------------------------------------- /get + per-type channels

test("/get <link> dispatches at once with ⏳; streams/YouTube refused instantly; usage without link", async () => {
  let r = await run(ENV, msg("/get https://cdn.x.com/v.mp4", 111), S);
  assert.match(r.sent[0].text, /^⏳ File download/);
  assert.deepStrictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs, { command: "/get https://cdn.x.com/v.mp4", ack_message_id: "501" });
  for (const u of ["https://x.com/live/index.m3u8", "https://x.com/a.m3u8?token=1", "https://www.youtube.com/watch?v=1", "https://youtu.be/abc", "https://x.com/v.mpd"]) {
    r = await run(ENV, msg("/get " + u, 111), S);
    assert.match(r.sent[0].text, /stream\/YouTube|YouTube video download nahi/, u);
    assert.ok(!r.calls.some((c) => c.url.endsWith("/dispatches")), u);
  }
  r = await run(ENV, msg("/get", 111), S);
  assert.match(r.sent[0].text, /Aise likho: \/get/);
});

test("📥 Download link button asks for a link; the reply becomes /get", async () => {
  let r = await run(ENV, cb("m:get", 111), S);
  const prompt = r.sent[0];
  assert.ok(prompt.text.startsWith(W.GET_PROMPT));
  assert.strictEqual(prompt.reply_markup.force_reply, true);
  const reply = (text) => msg(text, 111, { reply_to_message: { message_id: 8, from: { id: 1, is_bot: true }, text: prompt.text } });
  r = await run(ENV, reply("https://cdn.x.com/app.apk"), S);
  assert.strictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body.inputs.command, "/get https://cdn.x.com/app.apk");
  r = await run(ENV, reply("https://youtu.be/xyz"), S);
  assert.match(r.sent[0].text, /\/yt <link>/);
  r = await run(ENV, reply("https://x.com/a.m3u8"), S);
  assert.match(r.sent[0].text, /stream\/YouTube/);
  r = await run(ENV, reply("not a link"), S);
  assert.match(r.sent[0].text, /link nahi lag raha/);
});

test("status shows channel routing and the last /get from state.json", () => {
  const st = Object.assign({}, STATE, { routing: "videos → alag video channel, baaki files → main channel", last_get: { at: "2026-10-28T08:55:00Z", name: "a.apk", size: 12582912 } });
  const t = formatStatus({ state: st, runs: [] }, NOW);
  assert.match(t, /Channels: videos → alag video channel, baaki files → main channel/);
  assert.match(t, /Last \/get: a\.apk \(12\.0 MB\), 28 Oct 02:25 PM IST/);
});

// ---------------------------------------------------------------- 2026-10-29: link hints, why-0 notes

test("a bare link without a command gets the right command suggested, not the AI", async () => {
  const cases = [
    ["https://youtu.be/mWlmcjwV44o?si=Rz", /\/yt https:\/\/youtu\.be/],
    ["https://www.youtube.com/playlist?list=PL1234567890abcd", /\/addplaylist/],
    ["https://www.youtube.com/@StudyIQ", /\/addyoutube/],
    ["https://cdn.x.com/v.mp4", /\/get https:\/\/cdn\.x\.com\/v\.mp4/],
    ["https://x.com/live/index.m3u8", /stream/],
    ["https://examhint.com/p/7/videos", /\/addsite https:\/\/examhint\.com/],
  ];
  for (const [text, re] of cases) {
    const r = await run(Object.assign({}, ENV, { NVIDIA_API_KEY: "nvapi-x" }), msg(text, 111), S);
    assert.match(r.sent[0].text, re, text);
    assert.ok(!r.calls.some((c) => c.url.includes("nvidia") || c.url.endsWith("/dispatches")), text);
  }
  assert.strictEqual(W.linkHint("site kab sync hogi?"), null);
});

test("status and sites explain why a site gave 0, and count YouTube links found on a site", () => {
  const st = Object.assign({}, STATE, {
    sites: [{ url: "https://spidyiq.vercel.app/course/9854/English", adapter: "generic", depth: 5 },
            { url: "https://examhint.com/p/7/video-lectures", adapter: "generic", depth: 5 }],
    site_notes: { "https://spidyiq.vercel.app/course/9854/English": "ye site JavaScript app hai" },
    youtube_seen: { "site:examhint.com/p/7/video-lectures": ["a", "b"] },
    youtube_pending: { "site:examhint.com/p/7/video-lectures": [{ id: "c" }, { id: "d" }] },
  });
  const t = formatStatus({ state: st, runs: RUNS }, NOW);
  assert.match(t, /spidyiq[^\n]*\n0 kyun: ye site JavaScript app hai/);
  assert.match(t, /YouTube links line mein: 2/);
  assert.match(t, /Last auto-sync \(GitHub schedule\): 28 Oct 01:47 PM IST/);
  const s = W.formatSites(st);
  assert.match(s, /examhint[^\n]*YouTube links: 2 post, 2 line mein/);
  assert.match(s, /⚠️ 0 kyun: ye site JavaScript app hai/);
});

test("/api/tick: needs its own key, skips while a run is active or fresh, else starts a plain run", async () => {
  const TK = "tick_key_1234567890";
  const call = async (env, path, over) => {
    const f = mockFetch(net(over));
    const res = mockRes();
    await W.createTickHandler({ env, fetch: f, log: () => {}, now: () => NOW })({ method: "GET", url: path, headers: {} }, res);
    return { res, calls: f.calls };
  };
  let r = await call(ENV, "/api/tick?key=" + TK);
  assert.strictEqual(r.res.statusCode, 404);
  const env = Object.assign({}, ENV, { TICK_KEY: TK });
  r = await call(env, "/api/tick?key=" + ENV.WEBHOOK_SECRET);
  assert.strictEqual(r.res.statusCode, 403);
  assert.strictEqual(r.calls.length, 0);
  r = await call(env, "/api/tick?key=" + TK);                       // RUNS has one in_progress
  assert.match(r.res.body, /pehle se chal raha/);
  assert.ok(!r.calls.some((c) => c.url.endsWith("/dispatches")));
  const old = [{ status: "completed", conclusion: "success", event: "schedule", created_at: "2026-10-28T08:20:00Z" }];
  r = await call(env, "/api/tick?key=" + TK, (c) => (c.url.includes("/runs?") ? { json: { workflow_runs: old } } : null));
  assert.strictEqual(r.res.statusCode, 200);
  assert.deepStrictEqual(r.calls.find((c) => c.url.endsWith("/dispatches")).body, { ref: "main", inputs: { command: "" } });
  const fresh = [{ status: "completed", conclusion: "success", event: "schedule", created_at: "2026-10-28T08:55:00Z" }];
  r = await call(env, "/api/tick?key=" + TK, (c) => (c.url.includes("/runs?") ? { json: { workflow_runs: fresh } } : null));
  assert.match(r.res.body, /10 min/);
});
