# 模型、语音与需求摘要

## 配置与启动

复制 `.env.example` 为 `.env`，在本地填写 `OPENAI_API_KEY`。`OPENAI_MODEL` 必须是服务商支持的模型。完整 `/chat/completions` 地址和 `/v1` 基础地址均可配置。

语音转写使用 `SPEECH_MODEL`。`SPEECH_API_KEY` 和 `SPEECH_BASE_URL` 留空时沿用聊天接口的密钥和基础地址。浏览器会将录音转为单声道 16kHz WAV，再上传到 `/audio/transcriptions`，最长 60 秒。录音不保存到服务器磁盘。示例模型配置针对本项目服务商，不保证其他服务商支持；可替换为其实际模型名。

运行 `python server.py`，打开 http://127.0.0.1:8000 。`.env` 每次请求读取，修改配置后刷新页面即可；修改 Python 源码需要重启服务。无密钥时界面明确显示“离线演示”，有密钥但接口失败时会显示错误，不静默降级。

## 使用

1. 用 `jiwen` 选择预约、申请协助。点击麦克风并允许浏览器使用麦克风。
2. 点击停止，等转写完成。在转写框中核对或修改文字，点击“使用这段文字”，最后点击发送。
3. 右侧摘要显示已保存字段，未收集信息显示“待补充”，不是“不需要”。
4. 服务需求和地址确认后，仍是草稿；最终点击“确认提交”后，才进入社区工作台。
5. 提交前可用摘要中的“修改需求”“修改地址”。模型超时可重试同一条消息，服务器用 request_id 防止重复执行。

浏览器识别作为备选模式，依赖浏览器支持及在线识别服务；普通话、粤语、英语选项用于此模式。API 模式由转写模型检测语言。实际真人麦克风音质与权限需要使用者在自己的浏览器确认。模拟录音测试不等同于真人录音验收。

## 文件

- `ai_client.py`：模型/语音接口、输出类型校验、超时与脱敏错误信息。
- `chat.js`：录音生命周期、转写核对、请求重试、草稿恢复、实时摘要。
- `server.py`：权威摘要、最终确认阶段、请求回执表、会话读取接口、事务回滚。
- `test_chat.py`：模型异常回滚、重试幂等、未知信息及最终提交等测试。

数据库兼容原有服务记录，自动新增 `request_receipts` 表，不删除既有表。现有整单分配业务保留。

## 测试

`python -m unittest discover -s . -p "test_*.py"`

本地联网已验证聊天模型的自然语言提取，以及语音接口对模拟英文录音的转写。前端录音使用模拟音频设备进行端到端测试；普通用户首次使用仍需授予麦克风权限。浏览器刷新可恢复当前草稿，完成或取消后不再恢复。

接口格式参考：[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[语音转写](https://developers.openai.com/api/docs/guides/speech-to-text)、[MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)。

`.env`、数据库、测试录音不进入 ZIP。不要把密钥放进前端代码。
