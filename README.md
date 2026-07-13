# 留学生情绪梳理 Agent

一个面向留学生日常人际摩擦、孤独与情绪困扰的 AI 情绪梳理工具：先接住情绪，再帮助用户澄清事件、需要与可执行的小行动。

## 怎么用

- 前端（GitHub Pages）：https://bnu-ai-agent-class.github.io/6/
- 后端健康检查：https://bnu-agent-6.onrender.com/api/health
- 示例输入：`今天小组讨论时大家没接我的话，我有点孤单，能陪我梳理一下吗？`
- 点击“我需要紧急帮助”可进入危机支持路径；若存在迫近危险，请直接联系身边真人和当地紧急服务。中国境内可拨全国统一心理援助热线 12356。

该工具是 AI，不替代心理咨询、医疗诊断或紧急服务。无需提供真实身份；对话会发送至服务端用于生成回复，并保存在当前浏览器中，请勿输入敏感个人信息。

## 技术架构

- 前端：单文件静态 HTML/CSS/JavaScript，部署在 GitHub Pages。
- 后端：FastAPI + Uvicorn，部署在 Render。
- 模型：OpenRouter 上的 `deepseek/deepseek-v4-flash`，密钥仅保存在 Render 环境变量。
- 安全：确定性危机入口、四级安全灯、模型输出复核、客户端角色过滤和断网降级。

## 本地运行

```powershell
cd backend
Copy-Item .env.example .env
# 在 .env 中填写 OPENROUTER_API_KEY，切勿提交
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

另开终端启动静态前端：

```powershell
cd frontend
python -m http.server 5500
```

然后访问 http://127.0.0.1:5500/。

## 谁做的

- 团队：北京师范大学 AI Agent 课程第6组
- 仓库提交者：Sandrone
- 课程：人本 AI 设计与创新
- 课程指导：郑先隽，北京师范大学心理学部

## 详细文档

- [结项技术文档](./结项技术文档.md)
- [上线检查清单](./checklists/上线检查清单.md)
- [危机测试用例](./T7_危机测试用例表.md)
