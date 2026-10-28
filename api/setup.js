// GET /api/setup?key=<WEBHOOK_SECRET>[&action=set|info|delete]
// Opens in a phone browser: points Telegram at this deployment (setWebhook),
// shows webhook status, or switches back to polling-only (deleteWebhook).
const { createSetupHandler } = require("../lib/webhook");

module.exports = (req, res) => createSetupHandler({ env: process.env, fetch: globalThis.fetch })(req, res);
