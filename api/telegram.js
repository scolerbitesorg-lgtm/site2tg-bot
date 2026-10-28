// POST /api/telegram — the Telegram webhook (see lib/webhook.js)
const { createTelegramHandler } = require("../lib/webhook");

module.exports = (req, res) => createTelegramHandler({ env: process.env, fetch: globalThis.fetch })(req, res);
