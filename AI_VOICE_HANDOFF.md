# 模型、語音與需求摘要

## 配置與啟動

複製 `.env.example` 為 `.env`，在本地填寫 `OPENAI_API_KEY`。`OPENAI_MODEL` 必須是服務商支持的模型。完整 `/chat/completions` 地址和 `/v1` 基礎地址均可配置。

語音轉寫使用 `SPEECH_MODEL`。`SPEECH_API_KEY` 和 `SPEECH_BASE_URL` 留空時沿用聊天接口的密鑰和基礎地址。瀏覽器會將錄音轉為單聲道 16kHz WAV，再上傳到 `/audio/transcriptions`，最長 60 秒。錄音不保存到服務器磁盤。示例模型配置針對本項目服務商，不保證其他服務商支持；可替換為其實際模型名。

運行 `python server.py`，打開 http://127.0.0.1:8000 。`.env` 每次請求讀取，修改配置後刷新頁面即可；修改 Python 源碼需要重啟服務。無密鑰時界面明確顯示“離線演示”，有密鑰但接口失敗時會顯示錯誤，不靜默降級。

## 使用

1. 用 `jiwen` 選擇預約、申請協助。點擊麥克風並允許瀏覽器使用麥克風。
2. 點擊停止，等轉寫完成。在轉寫框中核對或修改文字，點擊“使用這段文字”，最後點擊發送。
3. 右側摘要顯示已保存字段，未收集信息顯示“待補充”，不是“不需要”。
4. 服務需求和地址確認後，仍是草稿；最終點擊“確認提交”後，才進入社區工作臺。
5. 提交前可用摘要中的“修改需求”“修改地址”。模型超時可重試同一條消息，服務器用 request_id 防止重複執行。

瀏覽器識別作為備選模式，依賴瀏覽器支持及在線識別服務；普通話、粵語、英語選項用於此模式。API 模式由轉寫模型檢測語言。實際真人麥克風音質與權限需要使用者在自己的瀏覽器確認。模擬錄音測試不等同於真人錄音驗收。

## 文件

- `ai_client.py`：模型/語音接口、輸出類型校驗、超時與脫敏錯誤信息。
- `chat.js`：錄音生命週期、轉寫核對、請求重試、草稿恢復、實時摘要。
- `server.py`：權威摘要、最終確認階段、請求回執表、會話讀取接口、事務回滾。
- `test_chat.py`：模型異常回滾、重試冪等、未知信息及最終提交等測試。

數據庫兼容原有服務記錄，自動新增 `request_receipts` 表，不刪除既有表。現有整單分配業務保留。

## 測試

`python -m unittest discover -s . -p "test_*.py"`

本地聯網已驗證聊天模型的自然語言提取，以及語音接口對模擬英文錄音的轉寫。前端錄音使用模擬音頻設備進行端到端測試；普通用戶首次使用仍需授予麥克風權限。瀏覽器刷新可恢復當前草稿，完成或取消後不再恢復。

接口格式參考：[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[語音轉寫](https://developers.openai.com/api/docs/guides/speech-to-text)、[MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)。

`.env`、數據庫、測試錄音不進入 ZIP。不要把密鑰放進前端代碼。
