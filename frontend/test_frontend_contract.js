const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync("index.html", "utf8");

assert(html.includes('const STORE_KEY = "bnu-agent-ui-v5"'), "must use clean v5 storage");
assert(html.includes('const PRODUCTION_BACKEND = "https://bnu-agent-6.onrender.com"'), "must use the Render production backend");
assert(html.includes("我是 AI 情绪梳理伙伴"), "must disclose the AI identity on the first screen");
assert(html.includes("经过本项目后端并交给其配置的模型服务商"), "must disclose the full model data path");
assert(html.includes("永久清空回收站"), "must allow permanent deletion of recycled chats");
assert(html.includes("永久清除全部本地对话与设置"), "must allow permanent deletion of all local data");
assert(html.includes("localStorage.removeItem(STORE_KEY)"), "all-data deletion must remove persisted state");
assert(html.includes("state.deleted = []"), "recycle-bin deletion must clear deleted conversations");
assert(html.includes("全国统一心理援助热线 <strong>12356</strong>"), "must display the current national hotline");
assert(!html.includes('const STORE_KEY = "bnu-agent-ui-v4"'), "must not load the previous failed session");
assert(html.includes('const REQUIRED_BACKEND_VERSION = "3.4.0"'), "must reject stale backend processes");
assert(html.includes("ensureBackendVersion"), "must perform a backend version handshake before chat");
assert(html.includes("emergency_help: emergencyHelp"), "must send the emergency button as a deterministic API flag");
assert(html.includes('{ emergencyHelp: true }'), "emergency button must opt into the deterministic red path");
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
