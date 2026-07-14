const { chromium } = require("playwright");

const FRONTEND_URL = process.env.FRONTEND_URL || "http://127.0.0.1:5500";
const EDGE_PATH = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function reset(page) {
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
}

async function send(page, text) {
  const repliesBefore = await page.locator(".message.assistant:not(.thinking)").count();
  await page.locator("#input").fill(text);
  await page.locator("#sendButton").click();
  await page.waitForFunction(
    (count) => document.querySelectorAll(".message.assistant:not(.thinking)").length > count,
    repliesBefore,
    { timeout: 150000 }
  );
  return page.locator(".message.assistant:not(.thinking)").last();
}

async function clickEmergency(page) {
  const repliesBefore = await page.locator(".message.assistant:not(.thinking)").count();
  await page.locator("#crisisButton").click();
  await page.waitForFunction(
    (count) => document.querySelectorAll(".message.assistant:not(.thinking)").length > count,
    repliesBefore,
    { timeout: 150000 }
  );
  return page.locator(".message.assistant:not(.thinking)").last();
}

async function main() {
  const browser = await chromium.launch({
    executablePath: EDGE_PATH,
    headless: true,
  });

  const results = {};
  try {
    const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pageErrors = [];
    desktop.on("pageerror", (error) => pageErrors.push(error.message));
    await reset(desktop);

    assert(await desktop.locator("#crisisButton").isVisible(), "危机求助按钮不可见");
    const bodyText = await desktop.locator("body").innerText();
    assert(bodyText.includes("我是 AI 情绪梳理伙伴"), "页面没有明确 AI 身份");
    assert(
      bodyText.includes("对话会经过本项目后端并交给其配置的模型服务商"),
      "页面没有完整披露后端与模型服务商数据路径"
    );

    const normal = await send(desktop, "你好，你能帮我梳理一下情绪吗");
    const normalText = await normal.innerText();
    assert(!(await normal.evaluate((node) => node.classList.contains("crisis"))), "普通倾诉被误标为危机");
    assert(!/12356|心理援助热线/.test(normalText), "普通倾诉错误出现热线");

    await desktop.locator("#newChat").click();
    const crisis = await clickEmergency(desktop);
    const crisisText = await crisis.innerText();
    assert(await crisis.evaluate((node) => node.classList.contains("crisis")), "紧急帮助按钮未标红");
    assert(crisisText.includes("12356"), "紧急帮助按钮回复缺少 12356");
    assert(pageErrors.length === 0, `桌面页面错误: ${pageErrors.join("; ")}`);
    await desktop.screenshot({ path: "..\\.runlogs\\b4-desktop.png", fullPage: true });
    results.desktop = "normal_and_emergency_button_ok";

    const offline = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await offline.route("**:8000/**", (route) => route.abort("failed"));
    await offline.route("https://bnu-agent-6.onrender.com/**", (route) => route.abort("failed"));
    await reset(offline);
    const fallback = await send(offline, "今天有点难过，想找人聊聊");
    const fallbackText = await fallback.innerText();
    assert(fallbackText.includes("连接暂时中断"), "后端断线未显示中性兜底");
    assert(!(await fallback.evaluate((node) => node.classList.contains("crisis"))), "普通断线兜底被标红");
    assert(!fallbackText.includes("12356"), "普通断线兜底错误出现热线");
    await offline.locator("#newChat").click();
    const crisisFallback = await clickEmergency(offline);
    const crisisFallbackText = await crisisFallback.innerText();
    assert(await crisisFallback.evaluate((node) => node.classList.contains("crisis")), "断线时明确危机未标红");
    assert(crisisFallbackText.includes("12356"), "断线时明确危机缺少 12356");
    results.offline = "neutral_and_crisis_fallback_ok";

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
    await reset(mobile);
    await mobile.locator("#collapseSidebar").click();
    const collapsedWidth = await mobile.locator(".sidebar").evaluate((node) => node.getBoundingClientRect().width);
    assert(collapsedWidth === 0, `移动端侧边栏收起宽度不是 0: ${collapsedWidth}`);
    const mobileReply = await send(mobile, "今天在小组讨论时有点孤单");
    assert((await mobileReply.innerText()).trim().length > 0, "移动端没有收到回复");
    const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert(overflow <= 1, `移动端存在横向溢出: ${overflow}px`);
    await mobile.screenshot({ path: "..\\.runlogs\\b4-mobile.png", fullPage: true });
    results.mobile = "chat_sidebar_overflow_ok";

    console.log(JSON.stringify(results));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
