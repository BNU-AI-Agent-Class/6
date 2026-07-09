# API 契约卡

## 基础信息

- 基础 URL：`http://localhost:8000`
- 协议：HTTP/1.1（开发）/ HTTPS（生产）
- CORS：开发阶段允许所有来源

## 接口列表

### 1. 健康检查

- **GET** `/api/health`
- **响应**：
  ```json
  {
    "status": "ok",
    "model": "anthropic/claude-3.5-sonnet"
  }
  ```

### 2. 对话

- **POST** `/api/chat`
- **Content-Type**：`application/json`
- **请求体**：
  ```json
  {
    "messages": [
      {"role": "user", "content": "今天室友在食堂看到我了，没打招呼"}
    ]
  }
  ```
  注意：前端无需传 `system` 消息，后端自动注入 `agent.md` + skills。
- **响应体**：
  ```json
  {
    "reply": "这种被忽视的感觉确实很难受...",
    "is_crisis": false,
    "model": "anthropic/claude-sonnet-4",
    "stage": "具体化事件"
  }
  ```
  危机触发时：
  ```json
  {
    "reply": "听到你这么说，我很担心你...",
    "is_crisis": true,
    "model": "safety",
    "stage": "crisis"
  }
  ```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `messages` | array | 对话历史，每项含 `role` 和 `content` |
| `role` | string | `"user"` / `"assistant"`（无需传 system） |
| `content` | string | 消息内容 |
| `reply` | string | AI 本轮回复 |
| `is_crisis` | boolean | 是否触发危机转介 |
| `model` | string | 实际使用的模型名，或 `"safety"`（危机拦截）/ `"fallback"`（降级） |
| `stage` | string | c2 工作流阶段：`"crisis"` / `"accompanying"` / `"共情稳定"` / `"具体化事件"` / `"认知重构"` / `"提取小行动"` / `"收尾退场"` / `"fallback"` |

## 错误处理

- key 未配置：HTTP 500，`{"detail":"LLM API key 未配置..."}`
- LLM 调用失败：返回 `model: "fallback"` + `stage: "fallback"` 兜底话术，不抛异常
- c3 安全复核判定不安全：自动切换为 `is_crisis: true` + `stage: "crisis"` + 热线转介
- 请求格式错误：FastAPI 自动返回 422

## 前端调用示例

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
console.log(data.reply, data.is_crisis);
```
