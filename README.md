# 社区就医协助 chatbot

C 组员的家属端与服务目录筛选交接见 [C_HANDOFF.md](C_HANDOFF.md)。公开机构参考复用团队已有目录，预约及分配人员仍是模拟数据。

运行：`python3 server.py`，然后打开 http://127.0.0.1:8000 。只使用 Python 3 标准库，无需安装依赖。

示例用户名：`jiwen`。服务记录和对话保存在同一文件夹下自动创建的 `chatbot.sqlite3` 中，刷新页面后仍保留。用户端与工作人员端读写同一数据库。预约和服务人员示例分别在两个 CSV 中。要接入模型，请填写 `.env` 的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL`（兼容 OpenAI Chat Completions 的基础 URL 或完整端点）。未填写时仍可用内置关键词解析体验流程；复杂自然语言建议配置模型。

本项目为课程演示。示例机构与人员及电话均为虚构，服务时间按预约所在半天筛选；去程时间仅按到院前一小时估算。

安装 Gunicorn：`python3 -m pip install -r requirements.txt`。生产式启动入口：在此目录运行 `gunicorn --bind 127.0.0.1:8000 wsgi:app`。Gunicorn 与本机 `server.py` 共用相同接口和数据库。`.env` 含密钥，应保留在本地且不得提交；需要部署时在服务器环境变量中单独配置。使用 SQLite 时建议只运行一个 Gunicorn worker。


模型、语音输入、实时需求摘要及最终提交说明见 [AI_VOICE_HANDOFF.md](AI_VOICE_HANDOFF.md)。语音需浏览器授予麦克风权限；转写文字可编辑，确认发送后才进入需求提取。
