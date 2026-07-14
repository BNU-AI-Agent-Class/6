# API 契约卡（BUILD/B2 已完成版）

## 0. B2 结论

**阶段状态：B2 · 后端服务化已完成。**

当前后端已经从本地 agent 装配结果服务化为 FastAPI 接口：

- `GET /api/health`：健康检查，供本地调试和部署平台探活。
- `POST /api/chat`：无状态对话接口，前端传 `messages`；紧急帮助按钮额外传 `emergency_help=true`，后端确定性进入红灯。
- key 只从后端环境变量读取，前端不需要也不能拿到 key。
- 危机信号由用户输入的确定性入口或紧急帮助按钮的显式信号判定；c3 只审核 AI 回复是否越界，不合格回复会被丢弃并安全回退，但不会把普通用户输入改判成红灯。
- 模型未配置或调用失败时返回 `fallback`，HTTP 仍为 200，避免前端白屏。

## 1. 基础信息

| 项 | 内容 |
|---|---|
| 本地基础 URL | `http://localhost:8000` |
| 协议 | 本地 HTTP；上线后 HTTPS |
| 后端框架 | FastAPI |
| 默认启动命令 | `uvicorn main:app --reload --port 8000` |
| CORS | 从 `CORS_ORIGINS` 读取；默认允许本地调试与课程 GitHub Pages origin，不使用通配符 |
| 认证 | B2 阶段暂不做用户登录；模型 key 只在后端环境变量中 |

## 2. 接口一：健康检查

```http
GET /api/health
```

### 成功响应

```json
{
  "status": "ok",
  "model": "deepseek/deepseek-v4-flash",
  "version": "3.4.0",
  "has_key": true
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | 服务状态，正常为 `"ok"` |
| `model` | string | 后端当前配置的模型名 |
| `version` | string | 后端服务版本 |
| `has_key` | boolean | 后端是否读到了模型 API key；用于部署自检，不返回 key 内容 |

## 3. 接口二：对话

```http
POST /api/chat
Content-Type: application/json
```

### 请求体

```json
{
  "messages": [
    {
      "role": "user",
      "content": "今天室友在食堂看到我了，没打招呼"
    }
  ],
  "emergency_help": false
}
```

### 多轮请求示例

前端负责带上历史消息；后端只接受 `user` 和 `assistant`，客户端传入 `system` 会返回 422：

前端和后端都会过滤历史中的危机 AI 回复。过去一轮触发过红灯，不会让之后的普通问候继续沿用危机话术；当前轮安全等级只由最新用户消息与用户历史信号确定。

```json
{
  "messages": [
    {
      "role": "user",
      "content": "今天室友在食堂看到我了，没打招呼"
    },
    {
      "role": "assistant",
      "content": "那一瞬间像是被晾在旁边了，确实会难受。"
    },
    {
      "role": "user",
      "content": "对，我就觉得是不是他们不想理我"
    }
  ]
}
```

### 请求字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `messages` | array | 是 | 对话历史，由前端维护并传入 |
| `messages[].role` | string | 是 | 只能是 `"user"` 或 `"assistant"`；`"system"` 由后端保留并注入，客户端传入会被拒绝 |
| `messages[].content` | string | 是 | 消息正文 |
| `emergency_help` | boolean | 否 | 默认为 `false`；仅紧急帮助按钮传 `true`，后端立即返回确定性红灯转介 |

### 紧急帮助按钮请求

按钮不再依赖自然语言关键词猜测，而是发送显式信号：

```json
{
  "messages": [{"role": "user", "content": "我现在需要紧急帮助。"}],
  "emergency_help": true
}
```

## 4. 正常响应

```json
{
  "reply": "那种被忽视的感觉确实挺难受的，尤其是你已经看见他们了，却没有得到回应。我们先不急着判断他们是不是不想理你，可以先一起回到当时那个场景：他们当时是在聊天、看手机，还是已经注意到你了？\n\n[阶段: 具体化事件]",
  "is_crisis": false,
  "escalation_level": 0,
  "safety_light": "green",
  "model": "deepseek/deepseek-v4-flash",
  "stage": "具体化事件"
}
```

### 响应字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `reply` | string | 给用户展示的本轮回复 |
| `is_crisis` | boolean | 是否触发危机相关流程 |
| `escalation_level` | number | 危机升级等级：`0` 无强制转介（含绿/黄/橙灯）、`2` 明确当前伤害意图、`3` 已采取行为/无法保证安全/主动披露的迫近危险 |
| `safety_light` | string | 安全灯：`green`、`yellow`、`orange`、`red` |
| `model` | string | 实际使用模型；安全拦截为 `"safety"`，降级为 `"fallback"` |
| `stage` | string | 当前工作流阶段，例如 `倾听共情`、`具体化事件`、`危机转介-二级建议`、`fallback` |

## 5. 安全分级响应

### 黄灯关注示例

用户表达被动死亡愿望或明确“撑不住”，但没有当前伤害意图时，只做一次最小化确认，不标记为红色危机：

```json
{
  "reply": "听起来你已经难受到有些撑不住了，谢谢你愿意告诉我。我想直接确认一下：你此刻有没有正在想伤害自己或结束生命？\n\n你只需要回答‘有’‘没有’或‘不确定’，不用描述任何方法。无论答案是什么，我都会先听你把感受说完。",
  "is_crisis": false,
  "escalation_level": 0,
  "safety_light": "yellow",
  "model": "safety",
  "stage": "黄灯-确认安全"
}
```

### 二级危机示例

用户明确表达本人当前自杀、自伤或伤人意图时：

```json
{
  "reply": "谢谢你直接告诉我。现在先不用解释细节，我会继续听你说。我是 AI，不能提供紧急救援或替代真人支持。\n\n为了让你此刻不必一个人扛着，你能不能先联系一位就在身边或能马上接电话的人？如果你在中国，也可以拨打全国统一心理援助热线 12356；如果危险正在逼近，请联系当地紧急服务。",
  "is_crisis": true,
  "escalation_level": 2,
  "safety_light": "red",
  "model": "safety",
  "stage": "危机转介-二级建议"
}
```

### 三级危机示例

用户已采取伤害行为、明确无法保证安全，或主动披露可立即执行的迫近危险时：

```json
{
  "reply": "谢谢你告诉我。现在最重要的是让你不要独自面对接下来的几分钟。我是 AI，不能提供紧急救援或替代真人支持。\n\n请立即联系身边可信任的人并联系当地紧急服务；如果你在中国，也可以拨打全国统一心理援助热线 12356。你不用向我描述方法，只要先告诉我：现在有没有一个人可以马上来到你身边？",
  "is_crisis": true,
  "escalation_level": 3,
  "safety_light": "red",
  "model": "safety",
  "stage": "危机转介-三级紧急转介"
}
```

## 6. 橙灯响应

用户描述霸凌、歧视、性骚扰、PUA、系统性孤立、持续贬低等有害人际环境时：

```json
{
  "reply": "你说的这些不太像普通的相处不愉快。如果有人一直在伤害你、贬低你，这不是你的问题。\n\n你不需要一个人面对这些。你愿意的话，我们可以一起看看你可以找谁帮忙——学校有国际学生办公室，也有心理咨询师可以聊这些事情。",
  "is_crisis": false,
  "escalation_level": 0,
  "safety_light": "orange",
  "model": "safety",
  "stage": "橙灯-有害环境"
}
```

## 7. 优雅降级约定

### key 未配置

后端未读取到 `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 时，`POST /api/chat` 不抛 500，而是返回：

```json
{
  "reply": "我现在还没有连接上模型服务，所以只能先给你一个兜底回应。\n\n如果你只是想先说说，我可以先陪你把事情放慢一点：刚才最让你难受的是哪一瞬间？",
  "is_crisis": false,
  "escalation_level": 0,
  "safety_light": "green",
  "model": "fallback",
  "stage": "fallback"
}
```

### 模型调用失败

模型超时、网络错误或服务异常时，HTTP 仍返回 200，并使用：

```json
{
  "model": "fallback",
  "stage": "fallback"
}
```

前端只需要正常展示 `reply`，不需要把用户带到错误页。

## 8. 错误响应

| 场景 | HTTP 状态 | 说明 |
|---|---|---|
| 请求 JSON 格式错误 | 422 | FastAPI/Pydantic 自动校验 |
| `messages` 缺失或类型错误 | 422 | 前端应修正请求体 |
| 模型 key 未配置 | 200 | 返回 `model:"fallback"`，不白屏 |
| 模型调用失败 | 200 | 返回 `model:"fallback"`，不白屏 |
| 危机输入 | 200 | 返回 `model:"safety"` 与转介话术 |

## 9. 环境变量

这些变量只放在后端本地 `.env` 或部署平台 Variables，不能出现在前端。

| 变量 | 必填 | 作用 | 示例 |
|---|---|---|---|
| `OPENROUTER_API_KEY` | 三选一 | OpenRouter API key | `YOUR_OPENROUTER_API_KEY` |
| `DEEPSEEK_API_KEY` | 三选一 | DeepSeek API key | `YOUR_DEEPSEEK_API_KEY` |
| `OPENAI_API_KEY` | 三选一 | OpenAI 兼容 API key | `YOUR_OPENAI_API_KEY` |
| `LLM_BASE_URL` | 否 | OpenAI 兼容接口 base URL | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | 否 | 模型名 | `deepseek/deepseek-v4-flash` |
| `SAFETY_REVIEW_MODEL` | 否 | 出口复核模型；留空时使用 LLM_MODEL 的独立请求 | `deepseek/deepseek-v4-flash` |
| `MODEL` | 否 | `LLM_MODEL` 的兼容别名 | OpenRouter 默认 `deepseek/deepseek-v4-flash` |

## 10. 前端调用示例

```javascript
const res = await fetch("http://localhost:8000/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    messages: [
      { role: "user", content: "今天室友在食堂看到我了，没打招呼" }
    ]
  })
});

const data = await res.json();

// 前端只展示 reply；根据 safety_light/is_crisis/stage 调整 UI 状态。
console.log(data.reply);
console.log(data.safety_light, data.is_crisis, data.stage);
```

## 11. B2 门禁检查

| B2 门禁项 | 状态 | 说明 |
|---|---|---|
| `POST /api/chat` 收 `messages` 并返回 `reply` | 通过 | `ChatRequest` / `ChatResponse` 已定义 |
| `GET /api/health` 返回 ok | 通过 | 返回 `status/model/version/has_key` |
| key 走环境变量 | 通过 | 读取 `OPENROUTER_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY` |
| 前端不需要传 system prompt | 通过 | 后端自动注入 `agent.md + skills` |
| 去掉 bash 等危险工具 | 通过 | 后端无用户可达 shell 工具 |
| CORS 已开启 | 通过 | `CORS_ORIGINS` 限制本地与 Pages origin，不使用 `*` |
| 模型失败有 fallback | 通过 | key 缺失或模型调用失败均返回 `model:"fallback"` |
| 危机输入确定性拦截 | 通过 | 入口确定性判断最新用户消息；出口独立检查最新用户原话与 AI 回复，可补捉遗漏风险，异常时 fail-closed |
| API 契约卡已填完 | 通过 | 本文件即 B2 产出物 |

---

*本卡根据 `Dev_depoly_guide` 的 BUILD/B2 要求，以及当前 `backend/main.py`、`backend/.env.example` 更新。*
