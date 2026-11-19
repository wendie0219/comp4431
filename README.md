# 社區就醫協助 chatbot

C 組員的家屬端與服務目錄篩選交接見 [C_HANDOFF.md](C_HANDOFF.md)。公開機構參考複用團隊已有目錄，預約及分配人員仍是模擬數據。

運行：`python3 server.py`，然後打開 http://127.0.0.1:8000 。只使用 Python 3 標準庫，無需安裝依賴。

示例用戶名：`jiwen`。服務記錄和對話保存在同一文件夾下自動創建的 `chatbot.sqlite3` 中，刷新頁面後仍保留。用戶端與工作人員端讀寫同一數據庫。預約和服務人員示例分別在兩個 CSV 中。要接入模型，請填寫 `.env` 的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL`（兼容 OpenAI Chat Completions 的基礎 URL 或完整端點）。未填寫時仍可用內置關鍵詞解析體驗流程；複雜自然語言建議配置模型。

本項目為課程演示。示例機構與人員及電話均為虛構，服務時間按預約所在半天篩選；去程時間僅按到院前一小時估算。

安裝 Gunicorn：`python3 -m pip install -r requirements.txt`。生產式啟動入口：在此目錄運行 `gunicorn --bind 127.0.0.1:8000 wsgi:app`。Gunicorn 與本機 `server.py` 共用相同接口和數據庫。`.env` 含密鑰，應保留在本地且不得提交；需要部署時在服務器環境變量中單獨配置。使用 SQLite 時建議只運行一個 Gunicorn worker。


模型、語音輸入、實時需求摘要及最終提交說明見 [AI_VOICE_HANDOFF.md](AI_VOICE_HANDOFF.md)。語音需瀏覽器授予麥克風權限；轉寫文字可編輯，確認發送後才進入需求提取。
