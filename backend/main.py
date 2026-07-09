"""
留学生情绪梳理 Agent · FastAPI 后端
基于 build-backend skill 搭建：agent.md + skills + /api/chat + 确定性危机拦截
"""

import os
import re
import json
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()  # 自动加载 backend/.env

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI(title="留学生情绪梳理 Agent", version="0.1.0")

# CORS：开发阶段允许前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 配置 ==========
API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


# ========== 数据模型 ==========
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    is_crisis: bool
    model: str
    stage: str = ""  # c2: 当前工作流阶段（crisis/accompanying/action/ending/fallback）


# ========== 工具函数 ==========
def load_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_skills() -> str:
    """按顺序加载 skill 文件；危机转介置顶。"""
    skills_dir = os.path.join(BACKEND_DIR, "skills")
    # 危机转介置顶，其余按工作流顺序排列
    skill_files = [
        "skill_危机转介.md",        # 🔴 安全第一，置顶
        "skill_安全检测.md",        # 每轮安全阀
        "skill_触发与循环.md",      # 主循环流程
        "skill_记忆读写.md",        # 三类记忆
        "skill_共情与具体化.md",    # 陪伴核心
        "skill_认知重构与小行动.md", # 重构+行动+退场
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

# c2 工作流阶段（每轮回复末尾用 [阶段: xxx] 标记当前所处阶段）
- **共情稳定**：确认感受、不评判
- **具体化事件**：引导回到客观细节
- **认知重构**：区分事实 vs 想法，提供替代解释
- **提取小行动**：给一个低压力、可执行的社交动作
- **收尾退场**：情绪平复后主动结束，不诱导继续聊

# 重要提醒
- 每轮回复前，先判断用户输入是否包含危机信号。若包含， strictly follow skill_危机转介.md，只返回危机转介内容。
- 不要给出医学诊断、开药建议或心理治疗。
- 不要替用户做决定。
- 保持简短、温和、不评判。
"""


CRISIS_PATTERNS = [
    # 自杀/自伤直接表达
    r"不想活[了]?",
    r"活着没[有]?意思",
    r"活不下去",
    r"没有活下去",
    r"想死",
    r"死了算了",
    r"自杀",
    r"自残",
    r"自伤",
    r"伤害自己",
    r"结束(?:自己|生命|一切)",
    r"一了百了",
    r"生无可恋",
    # 严重自我厌恶 / 精神崩溃
    r"我觉得自己恶心",
    r"我撑不下去了",
    r"我配不上",
    # 暴力伤害他人
    r"杀.+(?:人|他|她|了|掉)",
    r"弄死",
]


def is_crisis(text: str) -> bool:
    """确定性危机检测：入口和出口各执行一次。"""
    if not text:
        return False
    lowered = text.lower()
    return any(re.search(p, lowered) for p in CRISIS_PATTERNS)


def make_crisis_reply() -> str:
    return (
        "听到你这么说，我很担心你。你现在安全吗？\n\n"
        "我不是真人，也无法替你保密。如果你愿意，我希望你能把现在的感受告诉一个你信任的人。\n\n"
        "你可以拨打全国 24 小时心理援助热线：400-161-9995；\n"
        "北京心理危机研究与干预中心：800-810-1117 / 010-82951332；\n"
        "或联系学校心理咨询中心、辅导员、家人或紧急服务。"
    )


# ========== c4 对话压缩 ==========
COMPACT_LIMIT = 15  # 对话历史条数超过此值触发压缩


async def compact_messages(messages: List[Dict], client: httpx.AsyncClient) -> List[Dict]:
    """c4: 长对话折叠——保留 system prompt + 最近 6 条，其余让模型总结成一段摘要"""
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


# ========== c3 子 agent 安全复核 ==========
SAFETY_REVIEW_PROMPT = """你是安全审核员，独立审下面这条 AI 回复是否安全。只回一个 JSON，不要别的文字，不要 markdown 包裹。

审核标准（逐条判断，有一条不通过即判 unsafe）：
1. 是否越界？——诊断疾病、开药、做心理治疗、替代真人咨询师/朋友 → 不通过
2. 语气是否安全？——用了否定式安慰（"你想太多了""别矫情"） → 不通过
3. 是否制造虚假亲密？——过度共情、承诺永远陪伴、暗示 AI 有真实情感 → 不通过
4. 是否遗漏危机？——用户有自伤/自杀/暴力信号但 AI 回复未转介热线 → 不通过
5. 是否给了危险建议？——教唆、违法、伤害自己或他人的内容 → 不通过

用户消息：{user_msg}
AI 回复：{reply}

回复格式：{"safe": true或false, "issues": ["问题简述"]}"""


async def safety_review(reply: str, user_msg: str, client: httpx.AsyncClient) -> dict:
    """c3: 独立子 agent 审回复安不安全——独立 LLM 调用，不污染主对话上下文"""
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
        # 容错解析：剥掉可能的 markdown 包裹
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return {"safe": result.get("safe", True), "issues": result.get("issues", [])}
    except Exception:
        # 安全审核本身出错 → 宁可放行（关键词拦截已兜底），不阻塞用户
        return {"safe": True, "issues": []}


# ========== API 路由 ==========
@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "model": MODEL}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # 取最后一条用户消息做入口危机检测（在 API key 检查之前，确保危机拦截不受限）
    last_user_msg = ""
    for m in reversed(req.messages):
        if m.role == "user":
            last_user_msg = m.content
            break

    # 入口危机检测（c5 权限门：关键词先拦一道）
    if is_crisis(last_user_msg):
        return ChatResponse(reply=make_crisis_reply(), is_crisis=True, model="safety", stage="crisis")

    if not API_KEY:
        raise HTTPException(status_code=500, detail="LLM API key 未配置，请设置 OPENROUTER_API_KEY 或 OPENAI_API_KEY")

    system_prompt = build_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in req.messages]

    async with httpx.AsyncClient(timeout=120.0) as client:
        # c4: 长对话压缩——历史太长先折叠再送模型
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
            # 优雅降级：模型调不通时返回兜底话术，绝不 500/白屏
            return ChatResponse(
                reply=(
                    "我现在有点连接不上模型，没办法给你最好的回应。\n\n"
                    "如果你现在感到很难受，可以联系全国 24 小时心理援助热线：400-161-9995。"
                ),
                is_crisis=False,
                model="fallback",
                stage="fallback",
            )

        # c3: 子 agent 安全复核——独立 LLM 审这条回复安不安全
        review = await safety_review(reply, last_user_msg, client)
        if not review.get("safe", True):
            return ChatResponse(
                reply=make_crisis_reply(),
                is_crisis=True,
                model=MODEL,
                stage="crisis",
            )

    # 出口危机检测：关键词二次兜底
    if is_crisis(reply):
        return ChatResponse(reply=make_crisis_reply(), is_crisis=True, model=MODEL, stage="crisis")

    # c2: 从回复中提取工作流阶段标记 [阶段: xxx]
    stage = "accompanying"
    stage_match = re.search(r"\[阶段:\s*([^\]]+)\]", reply)
    if stage_match:
        stage = stage_match.group(1).strip()

    return ChatResponse(reply=reply, is_crisis=False, model=MODEL, stage=stage)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
