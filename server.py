"""Community hospital assistance demo. Run: python3 server.py"""
import csv
import ai_client
from contextvars import ContextVar
from contextlib import contextmanager
CHAT_STATE = ContextVar("chat_state", default={})
from service_directory import filter_services
import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'chatbot.sqlite3'
FIELDS = ['escort', 'outbound', 'return_trip', 'wheelchair']
LABELS = {'escort': '陪診', 'outbound': '去程', 'return_trip': '回程', 'wheelchair': '輪椅'}
QUESTIONS = {'escort': '您需要陪診嗎？', 'outbound': '您需要去程接送嗎？', 'return_trip': '您需要回程接送嗎？', 'wheelchair': '您需要輪椅嗎？'}
DAYS = '一二三四五六日'


@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS services (
          service_id TEXT PRIMARY KEY, username TEXT NOT NULL, appointment_id TEXT NOT NULL,
          hospital TEXT NOT NULL, hospital_district TEXT NOT NULL, arrival TEXT NOT NULL,
          started_at TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
          escort INTEGER, outbound INTEGER, return_trip INTEGER, wheelchair INTEGER,
          district TEXT, address TEXT, staff_name TEXT, staff_phone TEXT,
          organization TEXT, organization_district TEXT, service_slot TEXT
        );
        CREATE TABLE IF NOT EXISTS request_receipts (
          service_id TEXT NOT NULL, request_id TEXT NOT NULL, content TEXT NOT NULL, result TEXT NOT NULL,
          PRIMARY KEY(service_id,request_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(service_id) REFERENCES services(service_id)
        );
        ''')


def rows(filename):
    with (ROOT / filename).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def appointment(appt_id):
    return next((x for x in rows('預約列表.csv') if x['預約編號'] == appt_id), None)


def service(c, sid):
    row = c.execute('SELECT * FROM services WHERE service_id=?', (sid,)).fetchone()
    if not row:
        raise ValueError('找不到該服務')
    return dict(row)


def reply(c, sid, content):
    c.execute('INSERT INTO messages(service_id,role,content,created_at) VALUES(?,?,?,?)', (sid, 'assistant', content, now()))
    return content


def llm_extract(stage, user_text, missing=None):
    return ai_client.extract(stage, user_text, missing, CHAT_STATE.get())


def snapshot(s):
    keys = ['service_id','hospital','arrival','stage','status','district','address'] + FIELDS
    return {k: (None if s.get(k) is None else bool(s[k])) if k in FIELDS else s.get(k) for k in keys}


def yesno(text):
    t = text.strip().lower()
    if re.search(r'不需要|不用|不要|沒有|否|不是|no|取消|有誤|不對|修改', t):
        return False
    if re.search(r'需要|要|是|對|正確|確認|沒錯|無誤|yes|好|可以', t):
        return True
    return None


def extract_services(text, asked):
    result = llm_extract('services', text, asked)
    if result is not None:
        return {k: result[k] for k in FIELDS if type(result.get(k)) is bool}
    # Explicit offline mode: conservative clauses, including suffix negation.
    out = {}
    patterns = {'escort': r'陪診', 'outbound': r'去程|送.*去醫院',
                'return_trip': r'回程|接.*回|送.*回', 'wheelchair': r'輪椅'}
    for clause in re.split(r'[，。；,;]', text):
        for k, pattern in patterns.items():
            if re.search(pattern, clause):
                negative = re.search(r'不需要|不用|不要|沒有|不需', clause)
                family = k != 'wheelchair' and re.search(r'弟弟|哥哥|姐姐|妹妹|家人|家屬|丈夫|妻子', clause)
                out[k] = not bool(negative or family)
    if asked and asked not in out and not out:
        v = yesno(text)
        if v is not None:
            out[asked] = v
    return out


def service_summary(s):
    return '、'.join(f'{LABELS[k]}：{"需要" if s[k] else "不需要"}' for k in FIELDS)


def update_stage(c, sid, stage, content):
    c.execute('UPDATE services SET stage=? WHERE service_id=?', (stage, sid))
    return reply(c, sid, content)


def advance(c, s, text):
    sid, stage = s['service_id'], s['stage']
    CHAT_STATE.set(snapshot(s))
    if stage == 'appointment_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) else yesno(text)
        if answer is False:
            c.execute("UPDATE services SET status='cancelled',stage='cancelled' WHERE service_id=?", (sid,))
            return {'back': True, 'reply': reply(c, sid, '好的，請返回主頁重新選擇一條預約記錄。')}
        if answer is None:
            return {'reply': reply(c, sid, '請問您是否要就這條預約申請社區協助？請回答“是”或“否”。')}
        return {'reply': update_stage(c, sid, 'services', '您需要什麼幫助？請告訴我是否需要陪診、去程、回程和輪椅。')}
    if stage in ('services', 'services_correct'):
        missing = next((k for k in FIELDS if s[k] is None), None)
        changes = extract_services(text, missing if stage == 'services' else None)
        for k, val in changes.items():
            c.execute(f'UPDATE services SET {k}=? WHERE service_id=?', (int(val), sid))
        s = service(c, sid)
        if stage == 'services_correct' and not changes:
            return {'reply': reply(c, sid, '請告訴我需要修改哪一項，以及改為需要還是不需要。')}
        missing = next((k for k in FIELDS if s[k] is None), None)
        if missing:
            return {'reply': reply(c, sid, QUESTIONS[missing])}
        return {'reply': update_stage(c, sid, 'services_confirm', f'我記錄的是：{service_summary(s)}。請確認以上信息是否無誤？')}
    if stage == 'services_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'services_correct', '請告訴我需要修改什麼？例如“去程改為需要”。')}
        if answer is None:
            return {'reply': reply(c, sid, '請回答服務需求是否無誤；如有誤，請說“有誤”。')}
        return {'reply': update_stage(c, sid, 'district', '您是哪個區的？')}
    if stage in ('district', 'district_correct'):
        parsed = llm_extract('district', text)
        district = parsed.get('district') if isinstance(parsed, dict) else None
        district = ((district or '') if parsed is not None else text).strip()[:60]
        if not district:
            return {'reply': reply(c, sid, '請告訴我您所在的香港地區。')}
        c.execute('UPDATE services SET district=? WHERE service_id=?', (district, sid))
        if stage == 'district_correct':
            s = service(c, sid)
            return {'reply': update_stage(c, sid, 'address_confirm', f'您所在的地區是{s["district"]}，具體住址是{s["address"]}。請確認是否無誤？')}
        return {'reply': update_stage(c, sid, 'address', '您的具體住址是？')}
    if stage in ('address', 'address_correct'):
        parsed = llm_extract('address', text)
        address = parsed.get('address') if isinstance(parsed, dict) else None
        address = ((address or '') if parsed is not None else text).strip()[:200]
        if not address:
            return {'reply': reply(c, sid, '請告訴我您的具體住址。')}
        c.execute('UPDATE services SET address=? WHERE service_id=?', (address, sid))
        s = service(c, sid)
        return {'reply': update_stage(c, sid, 'address_confirm', f'您所在的地區是{s["district"]}，具體住址是{s["address"]}。請確認是否無誤？')}
    if stage == 'address_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'address_fix_choice', '請問需要修改地區還是具體住址？')}
        if answer is None:
            return {'reply': reply(c, sid, '請確認地區和住址是否無誤。')}
        return {'reply': update_stage(c, sid, 'final_confirm', '信息已記錄，請核對右側需求摘要。確認無誤後點擊“確認提交”；也可以先修改需求或地址。')}
    if stage == 'final_confirm':
        if text == '修改需求':
            return {'reply': update_stage(c, sid, 'services_correct', '請告訴我需要修改哪些服務需求。')}
        if text == '修改地址':
            return {'reply': update_stage(c, sid, 'address_fix_choice', '請問需要修改地區還是具體住址？')}
        if text != '確認提交':
            return {'reply': reply(c, sid, '請核對需求摘要，點擊“確認提交”或選擇修改需求、修改地址。')}
        if any(s[k] is None for k in FIELDS) or not s['district'] or not s['address']:
            raise ValueError('信息尚未完整，請繼續補充。')
        c.execute("UPDATE services SET status='pending',stage='complete' WHERE service_id=?", (sid,))
        return {'reply': reply(c, sid, '您的申請已提交，社區工作人員將開始處理。'), 'done': True}
    if stage == 'address_fix_choice':
        if '區' in text:
            return {'reply': update_stage(c, sid, 'district_correct', '請告訴我正確的地區。')}
        if '地址' in text or '住址' in text:
            return {'reply': update_stage(c, sid, 'address_correct', '請告訴我正確的具體住址。')}
        return {'reply': reply(c, sid, '請說“地區”或“住址”。')}
    raise ValueError('該對話已結束')


def slot_info(arrival):
    dt = datetime.fromisoformat(arrival)
    half = '上午' if dt.hour < 12 else '下午'
    col = f'周{DAYS[dt.weekday()]}{half}'
    start = dt - timedelta(hours=1 if dt.hour >= 12 else 0)
    end = dt + timedelta(hours=2)
    return col, f'{start:%Y-%m-%d %H:%M}–{end:%H:%M}'


def matches(s):
    col, slot = slot_info(s['arrival'])
    preferred = s['district'] if (s['outbound'] or s['return_trip']) else s['hospital_district']
    people = [p for p in rows('社區服務人員.csv') if p[col] == '可以預約'
              and (not s['wheelchair'] or p['社區服務機構是否有輪椅'] == '有')]
    preferred_people = [p for p in people if p['社區服務機構區域'] == preferred]
    return [{**p, '服務時間段': slot} for p in (preferred_people or people)]


def public_service_options(request):
    return filter_services(request)


def detail(s):
    dt = datetime.fromisoformat(s['arrival'])
    when = dt.strftime('%Y年%m月%d日 %H:%M')
    parts = [f'您好，您在{when}到{s["hospital"]}的社區協助已安排好。',
             f'服務人員：{s["staff_name"]}；聯繫電話：{s["staff_phone"]}。',
             f'服務機構：{s["organization"]}（{s["organization_district"]}）。']
    if s['outbound']:
        pickup = (dt - timedelta(hours=1)).strftime('%H:%M')
        parts.append(f'去程：請於當天約{pickup}在{s["address"]}等候。此時間為估計，服務人員會與您確認。')
    if s['escort']:
        parts.append(f'陪診：請在到院時於{s["hospital"]}正門入口與服務人員會合；如有去程接送，服務人員會陪您入院。')
    if s['return_trip']:
        parts.append(f'回程：就診結束後，請在{s["hospital"]}正門入口與服務人員會合，返回您的住址。')
    if s['wheelchair']:
        parts.append('您需要的輪椅會由服務機構準備，服務人員會帶着輪椅前來協助。')
    parts.append(f'服務時間段：{s["service_slot"]}。如需確認見面位置或時間，請致電服務人員。')
    return '\n'.join(parts)


class Handler(BaseHTTPRequestHandler):
    def send(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/chat.js':
            body = (ROOT / 'chat.js').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if path in ('/', '/index.html'):
            body = (ROOT / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        self.send(404, {'error': '未找到頁面'})

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            path = urlparse(self.path).path
            limit = 8_100_000 if path == '/api/transcribe' else 20000
            if n < 0 or n > limit: raise ValueError('內容過長')
            data = json.loads(self.rfile.read(n) or b'{}')
            path = urlparse(self.path).path
            if not isinstance(data, dict): raise ValueError('請求格式無效')
            if path == '/api/config':
                self.send(200, ai_client.capabilities()); return
            if path == '/api/transcribe':
                self.send(200, ai_client.transcribe(data)); return
            with db() as c:
                if path in ('/api/start','/api/message'):
                    c.execute('BEGIN IMMEDIATE')
                if path == '/api/user':
                    name = str(data.get('username', '')).strip()
                    if not name: raise ValueError('請輸入用戶名')
                    appts = [a for a in rows('預約列表.csv') if a['用戶名'] == name]
                    services = [dict(x) for x in c.execute("SELECT * FROM services WHERE username=? AND status IN ('pending','processed') ORDER BY started_at DESC", (name,))]
                    result = {'appointments': appts, 'services': services}
                elif path == '/api/start':
                    name, aid = str(data.get('username','')).strip(), str(data.get('appointment_id',''))
                    a = appointment(aid)
                    if not a or a['用戶名'] != name: raise ValueError('預約信息不匹配')
                    stamp = datetime.now().astimezone()
                    sid = 'S' + stamp.strftime('%Y%m%d%H%M%S%f')
                    c.execute('INSERT INTO services(service_id,username,appointment_id,hospital,hospital_district,arrival,started_at,stage,status) VALUES(?,?,?,?,?,?,?,?,?)',
                              (sid, name, aid, a['醫院'], a['醫院所在地區'], a['日期及到院時間'], stamp.isoformat(timespec='seconds'), 'appointment_confirm', 'draft'))
                    msg = f'您好，{name}。請確認：您要為{a["醫院"]}、{a["日期及到院時間"].replace("T", " ")}的預約（編號{aid}）申請社區協助嗎？'
                    result = {'service_id': sid, 'reply': reply(c, sid, msg), 'summary': snapshot(service(c, sid)), 'capabilities': ai_client.capabilities()}
                elif path == '/api/message':
                    sid = str(data.get('service_id',''))
                    s = service(c, sid)
                    if s['username'] != str(data.get('username','')): raise ValueError('用戶與申請不匹配')
                    content = str(data.get('message','')).strip()
                    if not content or len(content) > 1000: raise ValueError('請輸入 1–1000 字的消息')
                    rid = str(data.get('request_id','')).strip()
                    if not rid or len(rid) > 80: raise ValueError('請求編號無效，請刷新後重試')
                    cached = c.execute('SELECT content,result FROM request_receipts WHERE service_id=? AND request_id=?',(sid,rid)).fetchone()
                    if cached:
                        if cached['content'] != content: raise ValueError('重試消息與原請求不一致')
                        result = json.loads(cached['result'])
                    else:
                        c.execute('INSERT INTO messages(service_id,role,content,created_at) VALUES(?,?,?,?)', (sid,'user',content,now()))
                        result = advance(c, s, content)
                        result['summary'] = snapshot(service(c,sid))
                        result['capabilities'] = ai_client.capabilities()
                        c.execute('INSERT INTO request_receipts VALUES(?,?,?,?)',(sid,rid,content,json.dumps(result,ensure_ascii=False)))
                elif path == '/api/session':
                    s = service(c, str(data.get('service_id','')))
                    if s['username'] != str(data.get('username','')): raise ValueError('用戶與申請不匹配')
                    history = [dict(x) for x in c.execute('SELECT role,content FROM messages WHERE service_id=? ORDER BY id',(s['service_id'],))]
                    result = {'summary':snapshot(s),'messages':history,'capabilities':ai_client.capabilities()}
                elif path == '/api/staff':
                    result = {'pending': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='pending' ORDER BY started_at")],
                              'processed': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='processed' ORDER BY started_at DESC")]}
                elif path == '/api/matches':
                    s = service(c, str(data.get('service_id','')))
                    if s['status'] != 'pending': raise ValueError('此服務已處理')
                    result = {'matches': matches(s), 'public_options': public_service_options(s)}
                elif path == '/api/assign':
                    s = service(c, str(data.get('service_id','')))
                    if s['status'] != 'pending': raise ValueError('此服務已處理')
                    person = next((p for p in matches(s) if p['服務人員名稱'] == data.get('name') and p['服務人員聯繫方式'] == data.get('phone')), None)
                    if not person: raise ValueError('該人員已不符合分配條件')
                    c.execute("UPDATE services SET staff_name=?,staff_phone=?,organization=?,organization_district=?,service_slot=?,status='processed' WHERE service_id=?",
                              (person['服務人員名稱'],person['服務人員聯繫方式'],person['社區服務機構名稱'],person['社區服務機構區域'],person['服務時間段'],s['service_id']))
                    result = {'ok': True}
                elif path == '/api/detail':
                    s = service(c, str(data.get('service_id','')))
                    if s['username'] != str(data.get('username','')) or s['status'] != 'processed': raise ValueError('無法查看詳情')
                    result = {'text': detail(s)}
                else: raise ValueError('未知操作')
            self.send(200, result)
        except ai_client.ProviderError as e:
            self.send(502, {'error': str(e), 'retryable': True})
        except (ValueError, KeyError, sqlite3.Error) as e:
            self.send(400, {'error': str(e)})
        except Exception as e:
            self.send(500, {'error': '服務器暫時無法完成請求，請重試。'})


if __name__ == '__main__':
    init()
    print('打開 http://127.0.0.1:8000')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
