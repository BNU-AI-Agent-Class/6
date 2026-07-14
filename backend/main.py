"""
留学生情绪梳理 Agent · FastAPI 后端
T5 v3.4 ｜ 陪伴式 AI ｜ 最小化安全确认 + 紧迫风险转介 ｜ 🟢🟡🟠🔴 四级判定
基于 build-backend skill 搭建：agent.md + skills + /api/chat + 确定性安全边界
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Literal

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI(title="留学生情绪梳理 Agent", version="3.4.0")
logger = logging.getLogger("agent.backend")

# 生产环境通过 CORS_ORIGINS 指定允许的前端 origin，多个值用英文逗号分隔。
# 未配置时保留本地开发兼容性；通配符模式下不允许携带浏览器凭据。
_cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 配置 ==========
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_KEY = OPENROUTER_API_KEY or DEEPSEEK_API_KEY or OPENAI_API_KEY

if os.getenv("LLM_BASE_URL"):
    BASE_URL = os.getenv("LLM_BASE_URL")
elif OPENROUTER_API_KEY:
    BASE_URL = "https://openrouter.ai/api/v1"
elif DEEPSEEK_API_KEY:
    BASE_URL = "https://api.deepseek.com"
else:
    BASE_URL = "https://api.openai.com/v1"

if os.getenv("LLM_MODEL") or os.getenv("MODEL"):
    MODEL = os.getenv("LLM_MODEL") or os.getenv("MODEL")
elif OPENROUTER_API_KEY:
    MODEL = "deepseek/deepseek-v4-flash"
elif DEEPSEEK_API_KEY:
    MODEL = "deepseek-chat"
else:
    MODEL = "gpt-4o-mini"

# 普通回复与复核可使用不同模型；未单独配置时仍保留独立请求与确定性出口门禁。
SAFETY_REVIEW_MODEL = os.getenv("SAFETY_REVIEW_MODEL") or MODEL

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


# ========== 数据模型 ==========
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    emergency_help: bool = False


class ChatResponse(BaseModel):
    reply: str
    is_crisis: bool
    escalation_level: int = 0  # 0=无强制转介, 2=明确意图, 3=迫近危险/具体计划
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
- **危机转介**：仅按后端已确认的红灯二级/三级处理

# 重要提醒
- 每轮回复前，先判断用户输入安全等级（🟢🟡🟠🔴）
- 你是陪伴者不是诊断者——绝不说"你这是……"、"你可能得了……"
- 不确定用户意图时直接温和询问
- 情绪重时不急着分析，先缓冲
- 保持简短、温和、不评判
"""


# ========== 危机关键词匹配 ==========
# 黄灯：被动死亡想法、隐晦危险意象、严重绝望或撑不住，
# 但没有表达明确的当前伤害意图、正在实施或迫近计划。
PASSIVE_RISK_PATTERNS = [
    r"活着没[有]?意思",
    r"活不下去",
    r"没有活下去",
    r"生无可恋",
    r"一了百了",
    r"想消失",
    r"死了算了",
    r"没意思.*活",
    r"我撑不下去了",
    r"(?:真|真的|已经)?受不了(?:了)?",
    r"睡着.{0,10}(?:不用|不必|不要|别).{0,5}(?:再)?醒",
    r"(?:不用|不必|不要).{0,8}(?:再)?醒(?:来|过来)",
    r"死了.{0,12}(?:没人在乎|也不会有人在乎|就好|就好了)",
    r"(?:如果|要是).{0,12}(?:摔|掉|跳)下去.{0,20}(?:不用|不必).{0,10}(?:面对|继续)",
    r"(?:楼|桥|站台).{0,10}(?:高|边).{0,16}(?:开玩笑|哈哈)",
    r"想一些不该想的",
    r"让他们都消失",
    r"(?:什么都不想干|什么都不想做).{0,80}(?:有什么意义|没意义)",
]

# 红灯二级：用户明确表达本人当前自杀、自伤或伤人意图，但没有给出迫近计划。
RED_INTENT_PATTERNS = [
    r"我(?:现在|真的|已经)?(?:很)?想死",
    r"我(?:现在|真的)?不想活[了]?",
    r"我(?:现在|真的|已经)?(?:想|要|准备|打算)(?:去)?(?:自杀|自残|自伤|伤害自己|伤害他人|杀人)",
    r"我想结束(?:自己|生命|这一切)",
    r"(?:忍不住|控制不住).{0,8}(?:自残|自伤|伤害自己|伤害他人)",
    r"我.{0,24}(?:想|要|准备|打算).{0,12}(?:自杀|自残|自伤|伤害自己|伤害他人|杀人|跳楼|从.{0,8}跳下去|拿刀.{0,8}(?:划|割)自己)",
    r"(?:掐|划|割).{0,8}自己.{0,30}(?:印子|伤口|流血)",
]

# 用户可能在咨询、否认或讨论安全规则。仅提到危机词汇不等于本人有危机意图。
THIRD_PARTY_RISK_PATTERN = r"(?:朋友|同学|室友|家人|他|她).{0,48}(?:想死|想消失|自杀|自伤|伤害自己)"

NON_CRISIS_CONTEXT_PATTERNS = [
    r"(?:什么是|如何看待|怎么看|能否|会不会|可以|是否|测试|规则|红线|话题|论文|作业|课程|讲座|新闻).{0,24}(?:自杀|自伤|危机)",
    r"(?:自杀|自伤|危机).{0,24}(?:是什么|怎么办|怎么处理|规则|红线|话题|论文|作业|课程|讲座|新闻|预防)",
    r"(?:我)?(?:没有|并没有|没在|不会|从未|从来没有).{0,8}(?:想死|自杀|自伤|伤害自己|伤害他人)",
    r"(?:我)?不想(?:要)?(?:自杀|自伤|伤害自己|伤害他人)",
    THIRD_PARTY_RISK_PATTERN,
]

# 紧迫红灯：用户主动披露迫近计划、正在实施、无法保证安全或明确索要伤害方法。
# 这些是内部升级证据，不是要求用户必须交代的内容；系统不得追问实施细节。
LEVEL3_PATTERNS = [
    r"(?:今晚|明天|后天|下.?周|过几天|等.+不在).{0,20}(?:准备|打算|计划|决定|要).{0,10}(?:自杀|自伤|跳楼|跳下去|割腕|吞药|上吊|溺水)",
    r"(?:准备|打算|计划|决定).{0,12}(?:跳楼|跳桥|跳下去|割腕|吞药|吃很多药|上吊|溺水)",
    r"(?:已经|正在).{0,8}(?:割腕|吞药|上吊|伤害自己|站在.{0,8}(?:楼顶|桥边))",
    r"(?:已经|刚刚).{0,8}(?:吃|吞)(?:了)?(?:很多|一把|几十|上百)(?:片|颗|粒).{0,6}(?:药|安眠药)",
    r"(?:无法|不能|没法)保证(?:自己|我)?(?:现在)?安全",
    r"(?:不能|没法)保证.{0,8}不(?:自杀|自伤|伤害自己|伤害他人)",
    r"(?:这是|可能是).{0,8}最后一次(?:聊天|见面|联系)",
    r"(?:再见|永别).{0,8}(?:永远|最后一次)",
    r"(?:怎么|如何).{0,8}(?:自杀|自伤|结束生命)",
    r"有没有.{0,8}(?:自杀方法|自伤方法|结束生命的方法|不痛苦的方式)",
    r"(?:多少|几)(?:片|颗|粒).{0,15}(?:安眠|药)",
    r"我(?:准备|打算|计划|决定|要).{0,8}(?:杀人|杀他|杀她|弄死|伤害他人)",
]

# 橙灯信号：有害人际环境
ORANGE_PATTERNS = [
    r"(?:每天|一直|总是|经常).{0,15}(?:嘲讽|嘲笑|骂|贬低|歧视|欺负|孤立|排挤)",
    r"你们.{0,10}(?:中国|亚洲|留学生).{0,15}(?:都|就是|总是)",
    r"(?:他说|她说|他们).{0,10}(?:离了|没了|没有).{0,10}(?:什么都不是|活不下去|不行)",
    r"(?:碰|摸|蹭).{0,10}(?:我).{0,10}(?:一下|故意)",
    r"(?:从来|一直).{0,10}(?:不叫我|不跟我|不叫我一起)",
    r"(?:从来|一直|连续|多次|第[二三四五六七八九十\d]+次).{0,24}(?:没人叫我|不让我加入|孤立|排挤|排除在外)",
    r"(?:男朋友|女朋友|伴侣|对象).{0,16}(?:说|告诉我).{0,24}(?:离开.{0,8}什么都不是|没有(?:他|她).{0,8}活不下去)",
]


def extract_crisis_count(history: List[dict]) -> int:
    """统计当前浏览器传入的会话历史信号；不伪装成跨会话日历窗口。"""
    return len(history)


def has_crisis_signal(text: str) -> bool:
    """判断一条历史消息是否包含需要计入观察窗口的危机信号。"""
    if not text:
        return False
    lowered = text.lower()
    if any(re.search(p, lowered) for p in NON_CRISIS_CONTEXT_PATTERNS):
        return False
    crisis_patterns = PASSIVE_RISK_PATTERNS + RED_INTENT_PATTERNS + LEVEL3_PATTERNS
    return any(re.search(p, lowered) for p in crisis_patterns)


def build_crisis_history_from_messages(messages: List[ChatMessage], last_user_index: int) -> List[dict]:
    """
    B2 无状态实现：不在服务端记账，而是从前端传入的历史 messages 中
    推导本轮之前已经出现过的危机信号。该计数仅限当前会话，不代表日历窗口。
    """
    history = []
    for idx, message in enumerate(messages):
        if idx >= last_user_index:
            break
        if message.role == "user" and has_crisis_signal(message.content):
            history.append({"text": message.content[:200], "escalation": 0})
    return history


def evaluate_safety(text: str, crisis_history: List[dict]) -> dict:
    """
    四级安全判定 + 三级升级。
    返回: {level, escalation, reason, matched_pattern}
    """
    if not text:
        return {"level": "green", "escalation": 0, "reason": "空输入", "matched_pattern": ""}

    lowered = text.lower()

    # 先排除咨询、否认、引用规则等语境，避免把“讨论红线”误判为身处危机。
    if re.search(THIRD_PARTY_RISK_PATTERN, lowered):
        return {"level": "green", "escalation": 0, "reason": "第三方求助语境", "matched_pattern": THIRD_PARTY_RISK_PATTERN}

    if any(re.search(p, lowered) for p in NON_CRISIS_CONTEXT_PATTERNS):
        return {"level": "green", "escalation": 0, "reason": "危机词汇出现在咨询或否认语境", "matched_pattern": ""}

    # 三级：有具体计划/告别性语言/询问方法 → 直接紧急转介
    for p in LEVEL3_PATTERNS:
        if re.search(p, lowered):
            return {
                "level": "red", "escalation": 3,
                "reason": f"三级：具体计划/告别性语言/询问方法。匹配：{p}",
                "matched_pattern": p
            }

    # 二级：明确的本人当前自伤、自杀或伤人意图。
    for p in RED_INTENT_PATTERNS:
        if re.search(p, lowered):
            return {
                "level": "red", "escalation": 2,
                "reason": f"二级：较重危机信号，建议主动寻求专业帮助。匹配：{p}",
                "matched_pattern": p
            }

    # 橙灯优先于被动风险词：控制性关系中的引语不能误判为用户本人黄灯。
    for p in ORANGE_PATTERNS:
        if re.search(p, lowered):
            return {
                "level": "orange", "escalation": 0,
                "reason": f"橙灯：有害人际环境信号。匹配：{p}",
                "matched_pattern": p
            }

    # 黄灯：出现被动死亡愿望或“撑不住”等安全线索，只做最小化直接确认。
    for p in PASSIVE_RISK_PATTERNS:
        if re.search(p, lowered):
            count = extract_crisis_count(crisis_history) + 1
            if count >= 2:
                return {
                    "level": "yellow", "escalation": 0,
                    "reason": f"黄灯：当前会话历史中第 {count} 次安全线索，需要最小化确认当前是否有伤害意图。匹配：{p}",
                    "matched_pattern": p
                }
            return {
                "level": "yellow", "escalation": 0,
                "reason": f"黄灯：出现安全线索，需要最小化确认当前是否有伤害意图。匹配：{p}",
                "matched_pattern": p
            }


    return {"level": "green", "escalation": 0, "reason": "正常倾诉", "matched_pattern": ""}


# ========== 危机回复生成（按三级升级） ==========
def make_yellow_reply() -> str:
    """黄灯：继续倾听，只做一次最小化直接确认，不索要实施细节。"""
    return (
        "听起来你已经难受到有些撑不住了，谢谢你愿意告诉我。"
        "我想直接确认一下：你此刻有没有正在想伤害自己或结束生命？\n\n"
        "你只需要回答“有”“没有”或“不确定”，不用描述任何方法。"
        "无论答案是什么，我都会先听你把感受说完。"
    )


def make_crisis_reply_level2() -> str:
    """二级：明确当前伤害意图，保持对话并建议立即连接真人支持。"""
    return (
        "谢谢你直接告诉我。现在先不用解释细节，我会继续听你说。"
        "我是 AI，不能提供紧急救援或替代真人支持。\n\n"
        "为了让你此刻不必一个人扛着，你能不能先联系一位就在身边或能马上接电话的人？"
        "如果你在中国，也可以拨打全国统一心理援助热线 12356；"
        "如果危险正在逼近，请联系当地紧急服务。"
    )


def make_crisis_reply_level3() -> str:
    """三级：迫近危险，建议立即联系真人、紧急服务与危机资源。"""
    return (
        "谢谢你告诉我。现在最重要的是让你不要独自面对接下来的几分钟。"
        "我是 AI，不能提供紧急救援或替代真人支持。\n\n"
        "请立即联系身边可信任的人并联系当地紧急服务；如果你在中国，"
        "也可以拨打全国统一心理援助热线 12356。"
        "你不用向我描述方法，只要先告诉我：现在有没有一个人可以马上来到你身边？"
    )


def make_orange_reply() -> str:
    """橙灯：有害人际环境，不做正常化"""
    return (
        "你说的这些不太像普通的相处不愉快。"
        "如果有人一直在伤害你、贬低你，这不是你的问题。\n\n"
        "你不需要一个人面对这些。你愿意的话，我们可以一起看看你可以找谁帮忙——"
        "学校有国际学生办公室，也有心理咨询师可以聊这些事情。"
    )


def make_third_party_support_reply() -> str:
    """第三方危机求助：不把风险归到用户本人，但给出可执行的真人支持路径。"""
    return (
        "你愿意认真对待朋友说‘想消失’这件事很重要。不要承诺替对方一直保密，"
        "也不要独自承担判断和救助责任。你可以鼓励对方马上联系一位可信任真人或专业支持；"
        "如果危险正在逼近，请联系当地紧急服务。如果在中国，也可以拨打全国统一心理援助热线 12356。\n\n"
        "我是 AI，不能替你报警或提供紧急救援。你现在知道对方是否处在迫近危险中吗？"
    )


def make_boundary_response(text: str):
    """对明确的诊断、用药、依赖、亲密和伤害诱导给出确定性边界回应。"""
    lowered = (text or "").lower()

    if (
        re.search(r"(?:社交焦虑症|回避型人格障碍|抑郁症|焦虑症|人格障碍)", lowered)
        and re.search(r"(?:是不是|算不算|判断|分析|可能有|得了)", lowered)
    ):
        return (
            "我是 AI，不能诊断你是否患有某种心理疾病或人格障碍，也不应该根据几句话给你贴标签。"
            "如果这些困扰持续影响上课、睡眠或社交，可以请有资质的心理咨询师或医生做专业评估。"
            "如果你愿意，我可以只陪你梳理最近一次具体经历。",
            "边界-拒绝诊断",
        )

    if "药" in lowered and re.search(r"(?:推荐|换|别的药|吃了也不|加量|剂量)", lowered):
        return (
            "我不能推荐、调整或比较药物剂量。安眠药效果或安全问题需要尽快联系开药医生或药师；"
            "如果已经多服、混服或身体不适，请立即联系当地急救。",
            "边界-拒绝用药建议",
        )

    if "我爱你" in lowered and re.search(r"(?:说|能不能|就一句)", lowered):
        return (
            "我理解你想听到被在乎的话，但我是 AI，不能扮演恋人、表达真人情感或承诺永远陪伴。"
            "我可以陪你把此刻的孤单说清楚，也更希望你能联系一个真实可信的人。",
            "边界-拒绝虚假亲密",
        )

    if re.search(r"(?:藏.{0,12}(?:东西|物品)|(?:东西|物品).{0,12}藏)", lowered) and re.search(r"(?:搬走|报复|惩罚)", lowered):
        return (
            "我不能建议你藏室友的东西或用报复逼对方搬走，这可能升级冲突并伤害别人。"
            "如果你愿意，我们可以换成不伤害人的做法，例如明确边界、记录问题，或联系宿舍管理协助。",
            "边界-拒绝伤害共谋",
        )

    if re.search(r"(?:是不是|到底是不是).{0,12}(?:自卑的人|一个自卑)", lowered):
        return (
            "我不能替你判断你是不是‘自卑的人’，也不会根据对话给你下定义。"
            "我们可以只看一个具体场景：当时发生了什么、你怎么理解、还有哪些可能解释，判断权留给你。",
            "边界-拒绝下定义",
        )

    if (
        re.search(r"(?:每天都来找你|只有跟你说话)", lowered)
        and re.search(r"(?:翘.{0,3}课|不想出门|不想见人)", lowered)
    ):
        return (
            "听起来这已经影响到上课和出门了。我是 AI，不能成为你唯一的支持或替代真实关系。"
            "请考虑联系一位可信任同学、辅导员或学校心理咨询师；我可以帮你先想一句怎么开口。",
            "边界-依赖退场",
        )

    if re.search(r"(?:算了.{0,5}不说|不想说了|不说这些了)", lowered):
        return (
            "好，不想说就先不说。我不会追问；你可以换个话题，或者直接结束这次对话。",
            "用户控制-停止追问",
        )

    return None

# 这些话术只应在确定性入口已经判为红灯，或用户明确索要危机资源时出现。
CRISIS_REFERRAL_LANGUAGE_PATTERNS = [
    r"(?:无法|不能).{0,8}(?:替你)?保密",
    r"你现在安全[吗么]",
    r"24\s*小时.{0,8}(?:心理援助|危机|热线)",
    r"400[-—－]161[-—－]9995",
    r"800[-—－]810[-—－]1117",
    r"010[-—－]82951332",
    r"(?:心理援助热线.{0,6})?12356",
    r"(?:联系|拨打).{0,16}(?:紧急服务|危机热线|心理援助热线)",
]

CRISIS_INFO_REQUEST_PATTERNS = [
    r"(?:给|提供|告诉).{0,8}(?:我)?(?:热线|求助资源|危机资源|急救电话)",
    r"(?:热线|求助资源|危机资源|急救电话).{0,8}(?:是|有哪些|多少|号码)",
    r"怎么帮助.{0,12}(?:想自杀|想自伤|有危机).{0,6}(?:朋友|同学|室友|家人|他|她)?",
    r"(?:朋友|同学|室友|家人|他|她).{0,80}(?:想死|想消失|自杀|自伤).{0,40}(?:怎么|如何).{0,8}(?:帮|支持)",
]


def contains_crisis_referral_language(text: str) -> bool:
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in CRISIS_REFERRAL_LANGUAGE_PATTERNS)


def user_requested_crisis_information(text: str) -> bool:
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in CRISIS_INFO_REQUEST_PATTERNS)


def build_runtime_safety_instruction(safety: dict) -> str:
    level = safety["level"]
    if level == "green" and safety.get("reason") == "第三方求助语境":
        action = (
            "本轮是第三方求助语境，不得把朋友或室友的风险误判为用户本人红灯。"
            "应认真说明如何连接可信任真人、专业或紧急资源；不要承诺替用户报警。"
        )
    elif level == "green":
        action = (
            "本轮入口规则暂判为绿灯。不得因旧历史、AI 过去的危机回复或宽泛情绪词自行升级；"
            "但如果最新用户消息本身包含入口规则未覆盖的具体死亡、自伤、伤人或危险意象，"
            "不得忽略，应在回复中做与严重度相称的最小安全确认，交由出口复核再次判定。"
        )
    elif level == "orange":
        action = "本轮是橙灯，只处理有害人际环境并提供一般支持资源，不得改判为自杀/自伤红灯。"
    else:
        action = "严格服从后端给出的安全等级，不自行升级或降级。"
    return f"\n\n# 当前轮后端确定性安全判定\n- level: {level}\n- {action}\n"


def build_model_history(messages: List[ChatMessage]) -> List[Dict[str, str]]:
    """只向模型传递合法对话角色，并剔除旧危机回复，防止普通下一轮被历史话术锚定。"""
    cleaned = []
    for message in messages:
        if message.role == "assistant" and contains_crisis_referral_language(message.content):
            continue
        cleaned.append({"role": message.role, "content": message.content})
    return cleaned


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


# ========== c3 独立请求安全复核（T5 v3.4） ==========
SAFETY_REVIEW_PROMPT = """你是独立的回复安全审核员。后端初判只供参考，你必须同时检查用户最新原话和 AI 回复。只回一个 JSON，不要别的文字，不要 markdown 包裹。

审核标准（逐条判断，有一条不通过即判 unsafe）：
1. 是否越界？——诊断疾病、开药、做心理治疗、替代真人咨询师/朋友 → 不通过
2. 语气是否安全？——否定式安慰、给用户下定义 → 不通过
3. 是否制造虚假亲密？——承诺永远陪伴、暗示 AI 有真实情感、主动使用亲密称呼 → 不通过
4. 是否遗漏危机？——用户原话含明确当前伤害意图、已经实施或迫近危险，但 AI 未转介真人和紧急支持 → 不通过，risk_level=clear
5. 是否遗漏隐晦风险？——用户原话含被动死亡愿望、隐晦自伤/坠落意象或“撑不住”，但 AI 没有做一次最小安全确认 → 不通过，risk_level=possible
6. 是否给了危险建议？——教唆、违法、伤害自己或他人的内容 → 不通过
7. 是否正常化了有害环境？——对霸凌/歧视/PUA/骚扰说“这很正常”“别想太多” → 不通过
8. 是否过度危机转介？——用户只有普通低落且没有死亡/伤害含义，AI 却声明无法保密、主动给危机热线或紧急服务 → 不通过

后端入口初判：{backend_level}
用户消息：{user_msg}
AI 回复：{reply}

回复格式：{"safe": true或false, "issues": ["问题简述"], "risk_level": "none|possible|clear"}"""


async def safety_review(reply: str, user_msg: str, backend_level: str, client: httpx.AsyncClient) -> dict:
    """c3: 独立请求复核回复；复核不可用时按 fail-closed 处理。"""
    if not API_KEY:
        return {"safe": False, "issues": ["安全复核缺少模型凭据"], "risk_level": "unknown"}

    prompt = (
        SAFETY_REVIEW_PROMPT
        .replace("{backend_level}", backend_level)
        .replace("{user_msg}", user_msg[:1000])
        .replace("{reply}", reply[:1000])
    )

    try:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": SAFETY_REVIEW_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0, "max_tokens": 300,
            },
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text[text.find("{"): text.rfind("}") + 1])
        risk_level = result.get("risk_level", "none")
        if risk_level not in {"none", "possible", "clear"}:
            risk_level = "none"
        return {
            "safe": result.get("safe") is True,
            "issues": result.get("issues", []),
            "risk_level": risk_level,
        }
    except Exception:
        logger.exception("Safety review failed")
        return {"safe": False, "issues": ["安全复核不可用"], "risk_level": "unknown"}


# ========== API 路由 ==========
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "model": MODEL, "version": "3.4.0", "has_key": bool(API_KEY)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # 取最后一条用户消息
    last_user_msg = ""
    last_user_index = -1
    for idx in range(len(req.messages) - 1, -1, -1):
        if req.messages[idx].role == "user":
            last_user_msg = req.messages[idx].content
            last_user_index = idx
            break

    # B2 无状态：历史由前端随 messages 带入，后端只统计当前会话内既有安全信号。
    crisis_history = build_crisis_history_from_messages(req.messages, last_user_index)

    # “紧急帮助”按钮是用户主动求助动作，必须确定性进入红灯，不能交给文本猜测或模型。
    if req.emergency_help:
        safety = {
            "level": "red", "escalation": 2,
            "reason": "用户主动点击紧急帮助按钮", "matched_pattern": "emergency_help"
        }
    else:
        safety = evaluate_safety(last_user_msg, crisis_history)

    # 三级：具体或迫近危险，立即转介真人与紧急服务。
    if safety["escalation"] == 3:
        return ChatResponse(
            reply=make_crisis_reply_level3(),
            is_crisis=True,
            escalation_level=3,
            safety_light="red",
            model="safety",
            stage="危机转介-三级紧急转介"
        )

    # 二级：建议主动求助
    if safety["escalation"] == 2:
        return ChatResponse(
            reply=make_crisis_reply_level2(),
            is_crisis=True,
            escalation_level=2,
            safety_light="red",
            model="safety",
            stage="危机转介-二级建议"
        )

    if safety["level"] == "yellow":
        return ChatResponse(
            reply=make_yellow_reply(),
            is_crisis=False,
            escalation_level=0,
            safety_light="yellow",
            model="safety",
            stage="黄灯-确认安全",
        )

    # 黄灯已在上方确定性返回；普通与橙灯继续进入模型生成和出口复核。

    # 橙灯使用确定性回复，避免模型把歧视、霸凌或控制性关系正常化。
    if safety["level"] == "orange":
        return ChatResponse(
            reply=make_orange_reply(), is_crisis=False, escalation_level=0,
            safety_light="orange", model="safety", stage="橙灯-有害环境",
        )

    if safety.get("reason") == "第三方求助语境":
        return ChatResponse(
            reply=make_third_party_support_reply(), is_crisis=False,
            escalation_level=0, safety_light="green", model="safety",
            stage="第三方求助-真人资源",
        )

    boundary_response = make_boundary_response(last_user_msg)
    if boundary_response:
        reply, stage = boundary_response
        return ChatResponse(
            reply=reply, is_crisis=False, escalation_level=0,
            safety_light="green", model="safety", stage=stage,
        )

    # API key 检查：B2 要求优雅降级，前端不因后端配置缺失而白屏。
    if not API_KEY:
        return ChatResponse(
            reply=(
                "我现在还没有连接上模型服务，所以只能先给你一个兜底回应。\n\n"
                "如果你只是想先说说，我可以先陪你把事情放慢一点："
                "刚才最让你难受的是哪一瞬间？"
            ),
            is_crisis=False,
            escalation_level=0,
            safety_light="green",
            model="fallback",
            stage="fallback",
        )

    system_prompt = build_system_prompt() + build_runtime_safety_instruction(safety)
    messages = [{"role": "system", "content": system_prompt}]
    messages += build_model_history(req.messages)

    # 本地环境可能设置失效代理；模型 API 必须直连，不继承 HTTP(S)_PROXY。
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
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
            logger.exception("LLM request failed: %s", type(e).__name__)
            return ChatResponse(
                reply=(
                    "我现在有点连接不上，没办法给你最好的回应。"
                    "你可以先把刚才发生的事写下来，等连接恢复后我们再一起慢慢梳理。"
                ),
                is_crisis=False,
                escalation_level=0,
                safety_light="green",
                model="fallback",
                stage="fallback",
            )

        # c3: 独立请求安全复核（T5 v3.4 标准）
        review = await safety_review(reply, last_user_msg, safety["level"], client)
        if safety["level"] == "green" and safety.get("reason") != "第三方求助语境" and review.get("risk_level") == "clear":
            return ChatResponse(
                reply=make_crisis_reply_level2(), is_crisis=True, escalation_level=2,
                safety_light="red", model="safety-review", stage="出口复核-红灯转介",
            )
        if safety["level"] == "green" and safety.get("reason") != "第三方求助语境" and review.get("risk_level") == "possible":
            return ChatResponse(
                reply=make_yellow_reply(), is_crisis=False, escalation_level=0,
                safety_light="yellow", model="safety-review", stage="出口复核-黄灯确认",
            )
        if not review.get("safe", True):
            # AI 回复不合格不等于用户处于危机；丢弃回复，但保留入口判定的用户安全等级。
            return ChatResponse(
                reply=(
                    "抱歉，刚才生成的回应不够合适，我先不把它发给你。\n\n"
                    "我们换个更稳妥的方式：你愿意先说说，刚才最明显的情绪是什么吗？"
                ),
                is_crisis=False,
                escalation_level=0,
                safety_light=safety["level"],
                model="fallback",
                stage="安全复核-回复回退",
            )

        # 最后一道确定性防线：绿灯普通聊天绝不允许模型自行输出危机转介话术。
        if (
            safety["level"] == "green"
            and contains_crisis_referral_language(reply)
            and not user_requested_crisis_information(last_user_msg)
        ):
            return ChatResponse(
                reply="当然可以。你愿意从今天发生的哪件事开始说起？我会先认真听你说。",
                is_crisis=False,
                escalation_level=0,
                safety_light="green",
                model="fallback",
                stage="安全复核-过度转介回退",
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
