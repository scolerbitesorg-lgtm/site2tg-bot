// Webhook handler tests: node --test tests/
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { createTelegramHandler, createSetupHandler, decide } = require("../lib/webhook");

const ENV = {
  BOT_TOKEN: "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
  OWNER_ID: "111",
  GH_TOKEN: "github_pat_TESTTOKEN123",
  GH_REPO: "scolerbitesorg-lgtm/site2tg-bot",
  WEBHOOK_SECRET: "s3cret_value-1",
};

function mockFetch(responder) {
  const calls = [];
  const fn = async (url, opts) => {
    const call = { url, opts, body: opts && opts.body ? JSON.parse(opts.body) : null };
    calls.push(call);
    const r = (responder && responder(call)) || {};
    const status = r.status || 200;
    return { status, json: async () => (r.json !== undefined ? r.json : { ok: true, result: {} }) };
  };
  fn.calls = calls;
  return fn;
}

function mockRes() {
  return {
    statusCode: 0, headers: {}, body: "",
    setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
    end(b) { this.body = b || ""; },
  };
}

function req(update, secret, method) {
  return { method: method || "POST", headers: secret === undefined ? {} : { "x-telegram-bot-api-secret-token": secret }, body: update };
}

function msg(text, uid, extra) {
  return { update_id: 1, message: Object.assign({ message_id: 5, text, from: { id: uid }, chat: { id: uid, type: "private" } }, extra || {}) };
}

async function run(env, update, secret, responder) {
  const f = mockFetch(responder);
  const logs = [];
  const res = mockRes();
  await createTelegramHandler({ env, fetch: f, log: (m) => logs.push(m) })(req(update, secret), res);
  return { res, calls: f.calls, logs };
}

test("rejects a request without the right secret header", async () => {
  for (const s of [undefined, "", "wrong", ENV.WEBHOOK_SECRET + "x"]) {
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

test("non-owner is ignored silently", async () => {
  const { res, calls } = await run(ENV, msg("/sync", 999), ENV.WEBHOOK_SECRET);
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(calls.length, 0);
});

test("/help and /start reply instantly, no GitHub call", async () => {
  for (const c of ["/help", "/start", "/help@MyBot"]) {
    const { res, calls } = await run(ENV, msg(c, 111), ENV.WEBHOOK_SECRET);
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(calls.length, 1);
    assert.match(calls[0].url, /^https:\/\/api\.telegram\.org\/bot.+\/sendMessage$/);
    assert.strictEqual(calls[0].body.chat_id, 111);
    assert.match(calls[0].body.text, /site2tg-bot commands/);
  }
});

test("/id replies with owner id", async () => {
  const { calls } = await run(ENV, msg("/id", 111), ENV.WEBHOOK_SECRET);
  assert.strictEqual(calls.length, 1);
  assert.match(calls[0].body.text, /OWNER_ID: 111/);
});

test("heavy commands dispatch bot.yml with the command input, then ack", async () => {
  const { res, calls } = await run(ENV, msg("/addsite https://my.site 5", 111), ENV.WEBHOOK_SECRET,
    (c) => (c.url.includes("api.github.com") ? { status: 204, json: null } : null));
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(calls.length, 2);
  const gh = calls[0];
  assert.strictEqual(gh.url, "https://api.github.com/repos/scolerbitesorg-lgtm/site2tg-bot/actions/workflows/bot.yml/dispatches");
  assert.strictEqual(gh.opts.method, "POST");
  assert.strictEqual(gh.opts.headers.Authorization, "Bearer " + ENV.GH_TOKEN);
  assert.strictEqual(gh.opts.headers.Accept, "application/vnd.github+json");
  assert.ok(gh.opts.headers["User-Agent"]);
  assert.deepStrictEqual(gh.body, { ref: "main", inputs: { command: "/addsite https://my.site 5" } });
  assert.match(calls[1].url, /sendMessage$/);
  assert.match(calls[1].body.text, /^✅ Mil gaya/);
});

test("every dispatch command is forwarded; bot @suffix stripped", async () => {
  for (const c of ["/sync", "/status", "/sites", "/retry", "/removesite x.com", "/SYNC@MyBot"]) {
    const { calls } = await run(ENV, msg(c, 111), ENV.WEBHOOK_SECRET, (k) => (k.url.includes("github") ? { status: 204 } : null));
    assert.strictEqual(calls[0].url.includes("/dispatches"), true, c);
    assert.ok(calls[0].body.inputs.command.startsWith("/"), c);
  }
  const { calls } = await run(ENV, msg("/SYNC@MyBot", 111), ENV.WEBHOOK_SECRET, (k) => (k.url.includes("github") ? { status: 204 } : null));
  assert.strictEqual(calls[0].body.inputs.command, "/sync");
});

test("/addsite without url gets usage instantly, no dispatch", async () => {
  const { calls } = await run(ENV, msg("/addsite", 111), ENV.WEBHOOK_SECRET);
  assert.strictEqual(calls.length, 1);
  assert.match(calls[0].body.text, /Aise likho/);
});

test("GH_REF overrides branch; GH_REPO falls back to Vercel git env", async () => {
  const env = Object.assign({}, ENV, { GH_REPO: "", GH_REF: "dev", VERCEL_GIT_REPO_OWNER: "o", VERCEL_GIT_REPO_SLUG: "r" });
  const { calls } = await run(env, msg("/sync", 111), ENV.WEBHOOK_SECRET, (k) => (k.url.includes("github") ? { status: 204 } : null));
  assert.strictEqual(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/bot.yml/dispatches");
  assert.strictEqual(calls[0].body.ref, "dev");
});

test("dispatch failure is explained to the owner, token never leaked", async () => {
  for (const [status, re] of [[401, /GH_TOKEN galat/], [403, /Read and write/], [404, /GH_REPO/], [422, /accept nahi/]]) {
    const { res, calls, logs } = await run(ENV, msg("/sync", 111), ENV.WEBHOOK_SECRET,
      (k) => (k.url.includes("github") ? { status, json: { message: "nope " + ENV.GH_TOKEN } } : null));
    assert.strictEqual(res.statusCode, 200);
    const text = calls[1].body.text;
    assert.match(text, /^⚠️ Command GitHub tak nahi gayi/);
    assert.match(text, re);
    assert.ok(!text.includes(ENV.GH_TOKEN));
    assert.ok(!logs.join("\n").includes(ENV.GH_TOKEN));
  }
});

test("missing GH_TOKEN is reported, nothing sent to GitHub", async () => {
  const { calls } = await run(Object.assign({}, ENV, { GH_TOKEN: "" }), msg("/sync", 111), ENV.WEBHOOK_SECRET);
  assert.strictEqual(calls.length, 1);
  assert.match(calls[0].body.text, /GH_TOKEN env var nahi hai/);
});

test("setup mode (no OWNER_ID): anyone gets their user id, forwarded channel post gives channel id", async () => {
  const env = Object.assign({}, ENV, { OWNER_ID: "" });
  let r = await run(env, msg("/start", 42), ENV.WEBHOOK_SECRET);
  assert.strictEqual(r.calls.length, 1);
  assert.match(r.calls[0].body.text, /OWNER_ID\): 42/);
  assert.match(r.calls[0].body.text, /post is bot ko forward karo/);
  const fwd = { update_id: 2, message: { message_id: 6, from: { id: 42 }, chat: { id: 42 },
    forward_origin: { type: "channel", chat: { id: -1009876, title: "Backup" } } } };
  r = await run(env, fwd, ENV.WEBHOOK_SECRET);
  assert.match(r.calls[0].body.text, /CHANNEL_ID\): -1009876/);
  r = await run(env, msg("/sync", 42), ENV.WEBHOOK_SECRET);
  assert.ok(r.calls.every((c) => !c.url.includes("github")), "no dispatch in setup mode");
});

test("owner forwarding a channel post gets the channel id; edited messages ignored", () => {
  const d = decide({ message: { from: { id: 111 }, chat: { id: 111 }, forward_from_chat: { id: -1005, title: "C" } } }, ENV);
  assert.match(d.reply, /-1005/);
  assert.strictEqual(d.dispatch, null);
  assert.strictEqual(decide({ edited_message: { from: { id: 111 }, chat: { id: 111 }, text: "/sync" } }, ENV).reply, null);
});

test("raw JSON string body (no body parser) works", async () => {
  const f = mockFetch((k) => (k.url.includes("github") ? { status: 204 } : null));
  const res = mockRes();
  await createTelegramHandler({ env: ENV, fetch: f, log: () => {} })(req(JSON.stringify(msg("/sync", 111)), ENV.WEBHOOK_SECRET), res);
  assert.strictEqual(f.calls[0].body.inputs.command, "/sync");
});

test("GET on webhook is a health check listing missing env names only", async () => {
  const res = mockRes();
  await createTelegramHandler({ env: Object.assign({}, ENV, { GH_TOKEN: "" }), fetch: mockFetch(), log: () => {} })(req(null, undefined, "GET"), res);
  assert.strictEqual(res.statusCode, 200);
  assert.match(res.body, /GH_TOKEN/);
  assert.ok(!res.body.includes(ENV.BOT_TOKEN));
});

// ---------------- /api/setup

async function setup(env, url, headers, responder) {
  const f = mockFetch(responder);
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

test("setup sets webhook to production URL with secret_token", async () => {
  const env = Object.assign({}, ENV, { VERCEL_PROJECT_PRODUCTION_URL: "site2tg-bot.vercel.app" });
  const { res, calls } = await setup(env, "/api/setup?key=" + ENV.WEBHOOK_SECRET, { host: "site2tg-bot-abc123.vercel.app" },
    (c) => (c.url.endsWith("getWebhookInfo") ? { json: { ok: true, result: { url: "https://site2tg-bot.vercel.app/api/telegram", pending_update_count: 2 } } } : null));
  assert.strictEqual(res.statusCode, 200);
  const set = calls.find((c) => c.url.endsWith("/setWebhook"));
  assert.deepStrictEqual(set.body, { url: "https://site2tg-bot.vercel.app/api/telegram", secret_token: ENV.WEBHOOK_SECRET, allowed_updates: ["message"], max_connections: 5 });
  assert.ok(calls.some((c) => c.url.endsWith("/setMyCommands")));
  assert.match(res.body, /Webhook set ho gaya/);
  assert.ok(!res.body.includes(ENV.WEBHOOK_SECRET) && !res.body.includes(ENV.BOT_TOKEN));
});

test("setup falls back to host header, and &url= override", async () => {
  let r = await setup(ENV, "/api/setup?key=" + ENV.WEBHOOK_SECRET, { "x-forwarded-host": "abc.vercel.app" });
  assert.strictEqual(r.calls[0].body.url, "https://abc.vercel.app/api/telegram");
  r = await setup(ENV, "/api/setup?key=" + ENV.WEBHOOK_SECRET + "&url=https://my.domain/", { host: "abc.vercel.app" });
  assert.strictEqual(r.calls[0].body.url, "https://my.domain/api/telegram");
});

test("setup delete and info", async () => {
  let r = await setup(ENV, "/api/setup?key=" + ENV.WEBHOOK_SECRET + "&action=delete");
  assert.ok(r.calls[0].url.endsWith("/deleteWebhook"));
  assert.match(r.res.body, /Webhook hata diya/);
  r = await setup(ENV, "/api/setup?key=" + ENV.WEBHOOK_SECRET + "&action=info", {},
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
  const { res } = await setup(ENV, "/api/setup?key=" + ENV.WEBHOOK_SECRET, { host: "a.vercel.app" },
    () => ({ json: { ok: false, error_code: 401, description: "Unauthorized " + ENV.BOT_TOKEN } }));
  assert.strictEqual(res.statusCode, 502);
  assert.ok(!res.body.includes(ENV.BOT_TOKEN));
  assert.match(res.body, /401/);
});

test("streamed body (req.body undefined) is read", async () => {
  const { Readable } = require("node:stream");
  const r = Readable.from([Buffer.from(JSON.stringify(msg("/status", 111)))]);
  r.method = "POST";
  r.headers = { "x-telegram-bot-api-secret-token": ENV.WEBHOOK_SECRET };
  const f = mockFetch((k) => (k.url.includes("github") ? { status: 204 } : null));
  const res = mockRes();
  await createTelegramHandler({ env: ENV, fetch: f, log: () => {} })(r, res);
  assert.strictEqual(f.calls[0].body.inputs.command, "/status");
});
