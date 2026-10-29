// GET /api/tick?key=<TICK_KEY>  (optional)
// For a free outside pinger such as cron-job.org: starts a normal sync run on
// GitHub when none is running, because GitHub's own schedule often runs late
// or skips. Needs the env var TICK_KEY (its own random key, not WEBHOOK_SECRET).
const { createTickHandler } = require("../lib/webhook");

module.exports = (req, res) => createTickHandler({ env: process.env, fetch: globalThis.fetch })(req, res);
