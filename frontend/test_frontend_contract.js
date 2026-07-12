const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync("index.html", "utf8");

assert(html.includes('const STORE_KEY = "bnu-agent-ui-v5"'), "must use clean v5 storage");
assert(!html.includes('const STORE_KEY = "bnu-agent-ui-v4"'), "must not load the previous failed session");
assert(html.includes('const REQUIRED_BACKEND_VERSION = "3.3.0"'), "must reject stale backend processes");
assert(html.includes("ensureBackendVersion"), "must perform a backend version handshake before chat");
assert(html.includes('message.role !== "user" && message.role !== "assistant"'), "must filter client roles");
assert(html.includes("message.options && message.options.crisis"), "must filter old crisis assistant replies");
assert(!html.includes('const note = "请优先联系真人支持'), "must not append a duplicate crisis card");
assert(html.includes("--claude-yellow: #d7a06d"), "must define Claude yellow");
assert(html.includes("background: var(--claude-yellow)"), "avatars must use Claude yellow");
assert(html.includes("function isExplicitLocalCrisis"), "must distinguish explicit offline crisis");

const localGuard = html.match(/function isExplicitLocalCrisis\(text\) \{([\s\S]*?)\n    \}/);
assert(localGuard, "offline crisis guard must exist");
assert(!localGuard[1].includes("撑不下去"), "passive distress must not be marked red offline");

const script = html.match(/<script>([\s\S]*?)<\/script>/);
assert(script, "inline script must exist");
new Function(script[1]);

console.log("frontend_contract=ok");
