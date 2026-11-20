# CareVisit — Community Follow-up Visit Support Chatbot

CareVisit helps family caregivers request medical accompaniment, transport, and wheelchair support for a follow-up visit. Community staff can review the request and assign a worker. This project was developed for COMP4431.

## Group members

| Student ID | Name |
| --- | --- |
| 23103844d | Yichu LIN |
| 23101574d | Yiran WANG |
| 26009616x | Jiwen ZHANG |

## Additional features and implementation

- **Voice input and transcript review:** Caregivers can use browser speech recognition.  The transcript is editable and enters the chat only after the caregiver sends it.
- **Need extraction and live request summary:** The chatbot records whether the caregiver needs medical accompaniment, an outbound ride, a return ride, and a wheelchair. It asks follow-up questions for unanswered needs. The summary updates after each answer, and the caregiver can revise the needs or address before final submission. 
- **Service filtering:** The system filters the sample staff roster by appointment time and wheelchair requirements, then prioritizes the relevant district.
- **Shared family and staff workflow:** Both views use the same Python HTTP backend and SQLite database. Chat messages and request updates are saved as the conversation progresses. Submitted requests appear in the staff portal, and the family can view and copy the arrangement after staff assign a worker.

## Run locally

Python 3 is required. From the project directory, run:

```bash
python3 server.py
```

Open <http://127.0.0.1:8000> in a browser. The sample username is `jiwen`. Local development uses only the Python standard library, so no package installation is required. The application creates `chatbot.sqlite3` in the project directory to store requests and conversations.

To enable the chat model, copy `.env.example` to a local `.env` file and set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`. You can also set these as environment variables. For API-based speech transcription, set `SPEECH_MODEL` and, if needed, `SPEECH_API_KEY` and `SPEECH_BASE_URL`. The chatbot can still run with built-in keyword matching when no chat model is configured. Do not commit `.env` or API keys.

## Online version and deployment

The project can also be accessed at <https://comp4431-eimc.onrender.com>.
