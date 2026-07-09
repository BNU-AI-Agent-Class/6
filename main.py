"""
留学生情绪梳理 Agent · FastAPI 后端
T5 v3.0 ｜ 陪伴式 AI ｜ 三级安全升级 ｜ 🟢🟡🟠🔴 四级判定
基于 build-backend skill 搭建：agent.md + skills + /api/chat + 三级升级机制
"""

import os
import re
import json
import time
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI(title="留学生情绪梳理 Agent", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 配置 ==========
API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# 观察窗口：3 个月（秒）
CRISIS_WINDOW_SECONDS = 3 * 30 * 24 * 3600  # ~90 天


# ========== 数据模型 ==========
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    is_crisis: bool
    escalation_level: int = 0  # 0=无, 1=一级标记, 2=二级建议, 3=三级上报
    safety_light: str = "green"  # green/yellow/orange/red
    model: str
    stage: str = ""


# ========== 工具函数 ==========
def load_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_skills() -> str:
    """按顺序加载 skill 文件"""
    skills_dir = os.path.join(BACKEND_DIR, "skills")
    skill_files = [
        "skill_危机转介.md",
        "skill_安全检测.md",
        "skill_触发与循环.md",
        "skill_记忆读写.md",
        "skill_共情与具体化.md",
        "skill_认知重构与小行动.md",
    ]
    parts = []
    for name in skill_files:
        path = os.path.join(skills_dir, name)
        if os.path.exists(path):
            parts.append(f"\n\n# === {name} ===\n\n" + load_file(path))
    return "\n".join(parts)


def build_system_prompt() -> str:
    agent_md = load_file(os.path.join(BACKEND_DIR, "agent.md"))
    skills = load_skills()
    return f"""{agent_md}

{skills}

# 工作流阶段（每轮回复末尾用 [阶段: xxx] 标记当前所处阶段）
- **倾听共情**：确认感受、不评判
- **情绪缓冲**：等待用户准备好，不逼不催
- **具体化事件**：引导回到客观细节
- **多元视角**：提供替代解释 + 强化用户优势 + 不替用户下结论
- **提取小行动**：仅在用户愿意时给一个低压力、可执行的社交动作
- **收尾退场**：情绪平复后主动结束，不诱导继续聊
- **危机转介**：按三级升级机制处理

# 重要提醒
- 每轮回复前，先判断用户输入安全等级（🟢🟡🟠🔴）
- 你是陪伴者不是诊断者——绝不说"你这是……"、"你可能得了……"
- 不确定用户意图时直接温和询问
- 情绪重时不急着分析，先缓冲
- 保持简短、温和、不评判
"""


# ========== 危机关键词匹配 ==========
# 一级信号：轻度危险，标记关注但不建议求助
LEVEL1_PATTERNS = [
    r"活着没[有]?意思",
    r"活不下去",
    r"没有活下去",
    r"生无可恋",
    r"一了百了",
    r"想消失",
    r"死了算了",
    r"没意思.*活",
]

# 二级信号：多次出现或明显加重（从一级升级），或提到具体方式
LEVEL2_PATTERNS = [
    r"想死",
    r"不想活[了]?",
    r"结束(?:自己|生命|一切)",
    r"自杀",
    r"自残",
    r"自伤",
    r"伤害自己",
    r"我撑不下去了",
    r"我配不上",
    r"觉得自己.*恶心",
]

# 三级信号：具体计划、告别性语言、询问方法——直接触发强制上报
LEVEL3_PATTERNS = [
    # 具体计划（时间/方式/地点）
    r"(?:等|等.|下.?周|明天|今晚|后天|过几天).{0,20}(?:跳|死|自杀|结束|走)",
    r"(?:楼|桥|河|海|药|刀|绳子).{0,20}(?:跳|割|吃|上吊|结束)",
    # 告别性语言
    r"最后.{0,10}(?:一次|句话|陪|聊)",
    r"谢谢.{0,20}(?:一直|陪|照顾)",
    r"以后.{0,10}不[会用在了]",
    r"(?:再见|拜拜).{0,10}(?:永远|最后)",
    # 询问方法
    r"(?:怎么|如何|什么|有没有).{0,10}(?:死|自杀|结束|自伤|不痛)",
    r"(?:多少|几)(?:片|颗|粒).{0,15}(?:安眠|药)",
    # 暴力伤害他人
    r"杀.+(?:人|他|她|了|掉)",
    r"弄死",
]

# 橙灯信号：有害人际环境
ORANGE_PATTERNS = [
    r"(?:每天|一直|总是|经常).{0,15}(?:嘲讽|嘲笑|骂|贬低|歧视|欺负|孤立|排挤)",
    r"你们.{0,10}(?:中国|亚洲|留学生).{0,15}(?:都|就是|总是)",
    r"(?:他说|她说|他们).{0,10}(?:离了|没了|没有).{0,10}(?:什么都不是|活不下去|不行)",
    r"(?:碰|摸|蹭).{0,10}(?:我).{0,10}(?:一下|故意)",
    r"(?:从来|一直).{0,10}(?:不叫我|不跟我|不叫我一起)",
]


def extract_crisis_count(history: List[dict]) -> int:
    """从危机历史中统计 3 个月内的记录条数"""
    now = time.time()
    count = 0
    for entry in history:
        if now - entry.get("timestamp", 0) < CRISIS_WINDOW_SECONDS:
            count += 1
    return count


def evaluate_safety(text: str, crisis_history: List[dict]) -> dict:
    """
    四级安全判定 + 三级升级。
    返回: {level, escalation, reason, matched_pattern}
    """
    if not text:
        return {"level": "green", "escalation": 0, "reason": "空输入", "matched_pattern": ""}

    lowered = text.lower()

    # 三级：有具体计划/告别性语言/询问方法 → 直接上报
    for p in LEVEL3_PATTERNS:
        if re.search(p, lowered):
            return {
                "level": "red", "escalation": 3,
                "reason": f"三级：具体计划/告别性语言/询问方法。匹配：{p}",
                "matched_pattern": p
            }

    # 二级：多类严重信号
    for p in LEVEL2_PATTERNS:
        if re.search(p, lowered):
            count = extract_crisis_count(crisis_history) + 1  # +1 为本次
            if count >= 2:
                return {
                    "level": "red", "escalation": 2,
                    "reason": f"二级：3 个月内第 {count} 次危险信号，或信号明显加重。匹配：{p}",
                    "matched_pattern": p
                }
            else:
                return {
                    "level": "red", "escalation": 1,
                    "reason": f"一级：首次出现较重信号（{p}），标记关注，继续陪伴。",
                    "matched_pattern": p
                }

    # 一级：轻度危险信号
    for p in LEVEL1_PATTERNS:
        if re.search(p, lowered):
            count = extract_crisis_count(crisis_history) + 1
            if count >= 2:
                return {
                    "level": "red", "escalation": 2,
                    "reason": f"二级：3 个月内第 {count} 次危险信号。匹配：{p}",
                    "matched_pattern": p
                }
            return {
                "level": "red", "escalation": 1,
                "reason": f"一级：3 个月内首次轻度信号。匹配：{p}",
                "matched_pattern": p
            }

    # 橙灯：有害人际环境
    for p in ORANGE_PATTERNS:
        if re.search(p, lowered):
            return {
                "level": "orange", "escalation": 0,
                "reason": f"橙灯：有害人际环境信号。匹配：{p}",
                "matched_pattern": p
            }

    # 黄灯检查：隐晦绝望、孤独信号（不含"死"字）
    yellow_hints = [
        r"(?:最近|这阵子|这几天).{0,10}(?:没意思|没什么意义|没意义|干什么都没劲)",
        r"(?:不想|懒得).{0,10}(?:出门|见人|社交|上课)",
        r"只有.{0,5}(?:跟你|和你说|在这).{0,10}(?:才|舒服|不紧张|放松)",
    ]
    for p in yellow_hints:
        if re.search(p, lowered):
            return {
                "level": "yellow", "escalation": 0,
                "reason": f"黄灯：隐晦低落/孤独/社交退缩信号。匹配：{p}",
                "matched_pattern": p
            }

    return {"level": "green", "escalation": 0, "reason": "正常倾诉", "matched_pattern": ""}


# ========== 危机回复生成（按三级升级） ==========
def make_crisis_reply_level1() -> str:
    """一级：标记关注，继续陪伴，不立即建议求助"""
    return (
        "有时候确实会有这种感觉……这种时候挺难熬的吧。\n\n"
        "我在这里，你想多说说吗？"
    )


def make_crisis_reply_level2() -> str:
    """二级：建议用户主动寻求专业帮助"""
    return (
        "你最近好像不止一次提到这些了。我不确定你是不是在考虑一些很沉重的事——"
        "如果是的话，你愿不愿意和学校的心理咨询师聊聊？他们比我更专业，也更知道怎么帮你。\n\n"
        "当然，这完全是你的选择。我还会在这里听你说话。\n\n"
        "如果你需要一个随时能打的号码：全国 24 小时心理援助热线 400-161-9995。"
    )


def make_crisis_reply_level3() -> str:
    """三级：强制上报，声明无法保密，提供热线"""
    return (
        "听到你这么说，我很担心你。你正在考虑一个非常具体的方式来伤害自己。"
        "我不能再假装没听到了——我需要确保你的安全。\n\n"
        "请现在联系能帮到你的人：\n"
        "全国 24 小时心理援助热线：400-161-9995；\n"
        "北京心理危机研究与干预中心：800-810-1117 / 010-82951332；\n"
        "或联系学校心理咨询中心、辅导员、家人或紧急服务。"
    )


def make_orange_reply() -> str:
    """橙灯：有害人际环境，不做正常化"""
    return (
        "你说的这些不太像普通的相处不愉快。"
        "如果有人一直在伤害你、贬低你，这不是你的问题。\n\n"
        "你不需要一个人面对这些。你愿意的话，我们可以一起看看你可以找谁帮忙——"
        "学校有国际学生办公室，也有心理咨询师可以聊这些事情。"
    )


# ========== c4 对话压缩 ==========
COMPACT_LIMIT = 15


async def compact_messages(messages: List[Dict], client: httpx.AsyncClient) -> List[Dict]:
    """长对话折叠：保留 system prompt + 最近 6 条，其余压缩成摘要"""
    if len(messages) <= COMPACT_LIMIT:
        return messages

    system_msgs = [m for m in messages if m["role"] == "system"]
    keep_recent = 6
    recent = messages[-(keep_recent):]
    to_summarize = messages[len(system_msgs):-(keep_recent)]

    if not to_summarize:
        return messages

    body = "\n".join(f'{m["role"]}: {m["content"][:300]}' for m in to_summarize)

    try:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": f"用中文要点总结这段对话的关键进展、用户情绪变化和已完成的陪伴阶段，限 200 字：\n{body}"}],
                "temperature": 0.3, "max_tokens": 400,
            },
        )
        resp.raise_for_status()
        summary = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        summary = "对话历史已自动压缩。"

    return system_msgs + [
        {"role": "user", "content": f"【之前对话摘要，请基于此继续陪伴】\n{summary}"}
    ] + recent


# ========== c3 子 agent 安全复核（T5 v3.0） ==========
SAFETY_REVIEW_PROMPT = """你是安全审核员，独立审下面这条 AI 回复是否安全。只回一个 JSON，不要别的文字，不要 markdown 包裹。

审核标准（逐条判断，有一条不通过即判 unsafe）：
1. 是否越界？——诊断疾病（"你这是社交焦虑""你有抑郁倾向"）、开药、做心理治疗、替代真人咨询师/朋友 → 不通过
2. 语气是否安全？——用了否定式安慰（"你想太多了""别矫情""这很正常"）、给用户下定义 → 不通过
3. 是否制造虚假亲密？——承诺永远陪伴、暗示 AI 有真实情感、主动使用亲密称呼 → 不通过
4. 是否遗漏危机？——用户有自伤/自杀/暴力/具体计划信号但 AI 回复未按三级升级机制处理 → 不通过
5. 是否给了危险建议？——教唆、违法、伤害自己或他人的内容 → 不通过
6. 是否正常化了有害环境？——对霸凌/歧视/PUA/骚扰说"这很正常""别想太多" → 不通过

用户消息：{user_msg}
AI 回复：{reply}

回复格式：{"safe": true或false, "issues": ["问题简述"]}"""


async def safety_review(reply: str, user_msg: str, client: httpx.AsyncClient) -> dict:
    """c3: 独立子 agent 审回复安全性"""
    if not API_KEY:
        return {"safe": True, "issues": []}

    prompt = SAFETY_REVIEW_PROMPT.replace("{user_msg}", user_msg[:1000]).replace("{reply}", reply[:1000])

    try:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0, "max_tokens": 300,
            },
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return {"safe": result.get("safe", True), "issues": result.get("issues", [])}
    except Exception:
        return {"safe": True, "issues": []}


# ========== 内存中的危机历史（生产环境应持久化到数据库） ==========
# 结构: { "user_id": [ { "timestamp": 1234567890, "text": "...", "escalation": 1 }, ... ] }
crisis_history_store: Dict[str, List[dict]] = {}


def record_crisis_signal(user_id: str, text: str, escalation: int):
    """记录一次危机信号"""
    if user_id not in crisis_history_store:
        crisis_history_store[user_id] = []
    crisis_history_store[user_id].append({
        "timestamp": time.time(),
        "text": text[:200],
        "escalation": escalation,
    })
    # 清理 3 个月前的记录
    now = time.time()
    crisis_history_store[user_id] = [
        e for e in crisis_history_store[user_id]
        if now - e["timestamp"] < CRISIS_WINDOW_SECONDS
    ]


def get_crisis_history(user_id: str) -> List[dict]:
    """获取用户 3 个月内的危机历史"""
    if user_id not in crisis_history_store:
        return []
    now = time.time()
    return [e for e in crisis_history_store[user_id] if now - e["timestamp"] < CRISIS_WINDOW_SECONDS]


# ========== API 路由 ==========
@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "model": MODEL, "version": "2.0.0"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # 取最后一条用户消息
    last_user_msg = ""
    for m in reversed(req.messages):
        if m.role == "user":
            last_user_msg = m.content
            break

    # 获取用户 ID（简化：用消息哈希做临时标识，生产环境应接入真实用户系统）
    user_id = "default_user"

    # 获取危机历史
    crisis_history = get_crisis_history(user_id)

    # 入口安全检测：四级判定 + 三级升级
    safety = evaluate_safety(last_user_msg, crisis_history)

    # 三级：强制上报
    if safety["escalation"] == 3:
        record_crisis_signal(user_id, last_user_msg, 3)
        return ChatResponse(
            reply=make_crisis_reply_level3(),
            is_crisis=True,
            escalation_level=3,
            safety_light="red",
            model="safety",
            stage="危机转介-三级上报"
        )

    # 二级：建议主动求助
    if safety["escalation"] == 2:
        record_crisis_signal(user_id, last_user_msg, 2)
        return ChatResponse(
            reply=make_crisis_reply_level2(),
            is_crisis=True,
            escalation_level=2,
            safety_light="red",
            model="safety",
            stage="危机转介-二级建议"
        )

    # 一级：标记关注（内部记录，继续走 LLM 陪伴流程）
    if safety["escalation"] == 1:
        record_crisis_signal(user_id, last_user_msg, 1)

    # 橙灯：有害人际环境
    if safety["level"] == "orange":
        if not API_KEY:
            return ChatResponse(
                reply=make_orange_reply(),
                is_crisis=False,
                escalation_level=0,
                safety_light="orange",
                model="safety",
                stage="橙灯-有害环境"
            )

    # API key 检查
    if not API_KEY:
        raise HTTPException(status_code=500, detail="LLM API key 未配置，请设置 DEEPSEEK_API_KEY")

    system_prompt = build_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in req.messages]

    async with httpx.AsyncClient(timeout=120.0) as client:
        # c4: 长对话压缩
        messages = await compact_messages(messages, client)

        try:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
        except Exception as e:
            return ChatResponse(
                reply=(
                    "我现在有点连接不上，没办法给你最好的回应。\n\n"
                    "如果你现在感到很难受，可以联系全国 24 小时心理援助热线：400-161-9995。"
                ),
                is_crisis=False,
                escalation_level=0,
                safety_light="green",
                model="fallback",
                stage="fallback",
            )

        # c3: 子 agent 安全复核（T5 v3.0 标准）
        review = await safety_review(reply, last_user_msg, client)
        if not review.get("safe", True):
            # 安全审核不通过 → 回退到危机响应
            return ChatResponse(
                reply=(
                    "抱歉，我刚才的回复可能不太合适。\n\n"
                    "如果你正在经历很困难的事情，请考虑联系全国 24 小时心理援助热线：400-161-9995。"
                ),
                is_crisis=True,
                escalation_level=0,
                safety_light="red",
                model=MODEL,
                stage="危机转介-安全审核回退",
            )

    # 出口安全检测：关键词二次兜底
    exit_safety = evaluate_safety(reply, crisis_history)
    if exit_safety["escalation"] >= 2:
        return ChatResponse(
            reply=make_crisis_reply_level2() if exit_safety["escalation"] == 2 else make_crisis_reply_level3(),
            is_crisis=True,
            escalation_level=exit_safety["escalation"],
            safety_light="red",
            model=MODEL,
            stage="危机转介-出口兜底"
        )

    # 提取工作流阶段标记
    stage = "倾听共情"
    stage_match = re.search(r"\[阶段:\s*([^\]]+)\]", reply)
    if stage_match:
        stage = stage_match.group(1).strip()

    return ChatResponse(
        reply=reply,
        is_crisis=(safety["escalation"] >= 1),
        escalation_level=safety["escalation"],
        safety_light=safety["level"],
        model=MODEL,
        stage=stage
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
