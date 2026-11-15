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
LABELS = {'escort': '陪诊', 'outbound': '去程', 'return_trip': '回程', 'wheelchair': '轮椅'}
QUESTIONS = {'escort': '您需要陪诊吗？', 'outbound': '您需要去程接送吗？', 'return_trip': '您需要回程接送吗？', 'wheelchair': '您需要轮椅吗？'}
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
    return next((x for x in rows('预约列表.csv') if x['预约编号'] == appt_id), None)


def service(c, sid):
    row = c.execute('SELECT * FROM services WHERE service_id=?', (sid,)).fetchone()
    if not row:
        raise ValueError('找不到该服务')
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
    if re.search(r'不需要|不用|不要|没有|否|不是|no|取消|有误|不对|修改', t):
        return False
    if re.search(r'需要|要|是|对|正确|确认|没错|无误|yes|好|可以', t):
        return True
    return None


def extract_services(text, asked):
    result = llm_extract('services', text, asked)
    if result is not None:
        return {k: result[k] for k in FIELDS if type(result.get(k)) is bool}
    # Explicit offline mode: conservative clauses, including suffix negation.
    out = {}
    patterns = {'escort': r'陪诊', 'outbound': r'去程|送.*去医院',
                'return_trip': r'回程|接.*回|送.*回', 'wheelchair': r'轮椅'}
    for clause in re.split(r'[，。；,;]', text):
        for k, pattern in patterns.items():
            if re.search(pattern, clause):
                negative = re.search(r'不需要|不用|不要|没有|不需', clause)
                family = k != 'wheelchair' and re.search(r'弟弟|哥哥|姐姐|妹妹|家人|家属|丈夫|妻子', clause)
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
            return {'back': True, 'reply': reply(c, sid, '好的，请返回主页重新选择一条预约记录。')}
        if answer is None:
            return {'reply': reply(c, sid, '请问您是否要就这条预约申请社区协助？请回答“是”或“否”。')}
        return {'reply': update_stage(c, sid, 'services', '您需要什么帮助？请告诉我是否需要陪诊、去程、回程和轮椅。')}
    if stage in ('services', 'services_correct'):
        missing = next((k for k in FIELDS if s[k] is None), None)
        changes = extract_services(text, missing if stage == 'services' else None)
        for k, val in changes.items():
            c.execute(f'UPDATE services SET {k}=? WHERE service_id=?', (int(val), sid))
        s = service(c, sid)
        if stage == 'services_correct' and not changes:
            return {'reply': reply(c, sid, '请告诉我需要修改哪一项，以及改为需要还是不需要。')}
        missing = next((k for k in FIELDS if s[k] is None), None)
        if missing:
            return {'reply': reply(c, sid, QUESTIONS[missing])}
        return {'reply': update_stage(c, sid, 'services_confirm', f'我记录的是：{service_summary(s)}。请确认以上信息是否无误？')}
    if stage == 'services_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'services_correct', '请告诉我需要修改什么？例如“去程改为需要”。')}
        if answer is None:
            return {'reply': reply(c, sid, '请回答服务需求是否无误；如有误，请说“有误”。')}
        return {'reply': update_stage(c, sid, 'district', '您是哪个区的？')}
    if stage in ('district', 'district_correct'):
        parsed = llm_extract('district', text)
        district = parsed.get('district') if isinstance(parsed, dict) else None
        district = ((district or '') if parsed is not None else text).strip()[:60]
        if not district:
            return {'reply': reply(c, sid, '请告诉我您所在的香港地区。')}
        c.execute('UPDATE services SET district=? WHERE service_id=?', (district, sid))
        if stage == 'district_correct':
            s = service(c, sid)
            return {'reply': update_stage(c, sid, 'address_confirm', f'您所在的地区是{s["district"]}，具体住址是{s["address"]}。请确认是否无误？')}
        return {'reply': update_stage(c, sid, 'address', '您的具体住址是？')}
    if stage in ('address', 'address_correct'):
        parsed = llm_extract('address', text)
        address = parsed.get('address') if isinstance(parsed, dict) else None
        address = ((address or '') if parsed is not None else text).strip()[:200]
        if not address:
            return {'reply': reply(c, sid, '请告诉我您的具体住址。')}
        c.execute('UPDATE services SET address=? WHERE service_id=?', (address, sid))
        s = service(c, sid)
        return {'reply': update_stage(c, sid, 'address_confirm', f'您所在的地区是{s["district"]}，具体住址是{s["address"]}。请确认是否无误？')}
    if stage == 'address_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'address_fix_choice', '请问需要修改地区还是具体住址？')}
        if answer is None:
            return {'reply': reply(c, sid, '请确认地区和住址是否无误。')}
        return {'reply': update_stage(c, sid, 'final_confirm', '信息已记录，请核对右侧需求摘要。确认无误后点击“确认提交”；也可以先修改需求或地址。')}
    if stage == 'final_confirm':
        if text == '修改需求':
            return {'reply': update_stage(c, sid, 'services_correct', '请告诉我需要修改哪些服务需求。')}
        if text == '修改地址':
            return {'reply': update_stage(c, sid, 'address_fix_choice', '请问需要修改地区还是具体住址？')}
        if text != '确认提交':
            return {'reply': reply(c, sid, '请核对需求摘要，点击“确认提交”或选择修改需求、修改地址。')}
        if any(s[k] is None for k in FIELDS) or not s['district'] or not s['address']:
            raise ValueError('信息尚未完整，请继续补充。')
        c.execute("UPDATE services SET status='pending',stage='complete' WHERE service_id=?", (sid,))
        return {'reply': reply(c, sid, '您的申请已提交，社区工作人员将开始处理。'), 'done': True}
    if stage == 'address_fix_choice':
        if '区' in text:
            return {'reply': update_stage(c, sid, 'district_correct', '请告诉我正确的地区。')}
        if '地址' in text or '住址' in text:
            return {'reply': update_stage(c, sid, 'address_correct', '请告诉我正确的具体住址。')}
        return {'reply': reply(c, sid, '请说“地区”或“住址”。')}
    raise ValueError('该对话已结束')


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
    people = [p for p in rows('社区服务人员.csv') if p[col] == '可以预约'
              and (not s['wheelchair'] or p['社区服务机构是否有轮椅'] == '有')]
    preferred_people = [p for p in people if p['社区服务机构区域'] == preferred]
    return [{**p, '服务时间段': slot} for p in (preferred_people or people)]


def public_service_options(request):
    return filter_services(request)


def detail(s):
    dt = datetime.fromisoformat(s['arrival'])
    when = dt.strftime('%Y年%m月%d日 %H:%M')
    parts = [f'您好，您在{when}到{s["hospital"]}的社区协助已安排好。',
             f'服务人员：{s["staff_name"]}；联系电话：{s["staff_phone"]}。',
             f'服务机构：{s["organization"]}（{s["organization_district"]}）。']
    if s['outbound']:
        pickup = (dt - timedelta(hours=1)).strftime('%H:%M')
        parts.append(f'去程：请于当天约{pickup}在{s["address"]}等候。此时间为估计，服务人员会与您确认。')
    if s['escort']:
        parts.append(f'陪诊：请在到院时于{s["hospital"]}正门入口与服务人员会合；如有去程接送，服务人员会陪您入院。')
    if s['return_trip']:
        parts.append(f'回程：就诊结束后，请在{s["hospital"]}正门入口与服务人员会合，返回您的住址。')
    if s['wheelchair']:
        parts.append('您需要的轮椅会由服务机构准备，服务人员会带着轮椅前来协助。')
    parts.append(f'服务时间段：{s["service_slot"]}。如需确认见面位置或时间，请致电服务人员。')
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
        self.send(404, {'error': '未找到页面'})

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            path = urlparse(self.path).path
            limit = 8_100_000 if path == '/api/transcribe' else 20000
            if n < 0 or n > limit: raise ValueError('内容过长')
            data = json.loads(self.rfile.read(n) or b'{}')
            path = urlparse(self.path).path
            if not isinstance(data, dict): raise ValueError('请求格式无效')
            if path == '/api/config':
                self.send(200, ai_client.capabilities()); return
            if path == '/api/transcribe':
                self.send(200, ai_client.transcribe(data)); return
            with db() as c:
                if path in ('/api/start','/api/message'):
                    c.execute('BEGIN IMMEDIATE')
                if path == '/api/user':
                    name = str(data.get('username', '')).strip()
                    if not name: raise ValueError('请输入用户名')
                    appts = [a for a in rows('预约列表.csv') if a['用户名'] == name]
                    services = [dict(x) for x in c.execute("SELECT * FROM services WHERE username=? AND status IN ('pending','processed') ORDER BY started_at DESC", (name,))]
                    result = {'appointments': appts, 'services': services}
                elif path == '/api/start':
                    name, aid = str(data.get('username','')).strip(), str(data.get('appointment_id',''))
                    a = appointment(aid)
                    if not a or a['用户名'] != name: raise ValueError('预约信息不匹配')
                    stamp = datetime.now().astimezone()
                    sid = 'S' + stamp.strftime('%Y%m%d%H%M%S%f')
                    c.execute('INSERT INTO services(service_id,username,appointment_id,hospital,hospital_district,arrival,started_at,stage,status) VALUES(?,?,?,?,?,?,?,?,?)',
                              (sid, name, aid, a['医院'], a['医院所在地区'], a['日期及到院时间'], stamp.isoformat(timespec='seconds'), 'appointment_confirm', 'draft'))
                    msg = f'您好，{name}。请确认：您要为{a["医院"]}、{a["日期及到院时间"].replace("T", " ")}的预约（编号{aid}）申请社区协助吗？'
                    result = {'service_id': sid, 'reply': reply(c, sid, msg), 'summary': snapshot(service(c, sid)), 'capabilities': ai_client.capabilities()}
                elif path == '/api/message':
                    sid = str(data.get('service_id',''))
                    s = service(c, sid)
                    if s['username'] != str(data.get('username','')): raise ValueError('用户与申请不匹配')
                    content = str(data.get('message','')).strip()
                    if not content or len(content) > 1000: raise ValueError('请输入 1–1000 字的消息')
                    rid = str(data.get('request_id','')).strip()
                    if not rid or len(rid) > 80: raise ValueError('请求编号无效，请刷新后重试')
                    cached = c.execute('SELECT content,result FROM request_receipts WHERE service_id=? AND request_id=?',(sid,rid)).fetchone()
                    if cached:
                        if cached['content'] != content: raise ValueError('重试消息与原请求不一致')
                        result = json.loads(cached['result'])
                    else:
                        c.execute('INSERT INTO messages(service_id,role,content,created_at) VALUES(?,?,?,?)', (sid,'user',content,now()))
                        result = advance(c, s, content)
                        result['summary'] = snapshot(service(c,sid))
                        result['capabilities'] = ai_client.capabilities()
                        c.execute('INSERT INTO request_receipts VALUES(?,?,?,?)',(sid,rid,content,json.dumps(result,ensure_ascii=False)))
                elif path == '/api/session':
                    s = service(c, str(data.get('service_id','')))
                    if s['username'] != str(data.get('username','')): raise ValueError('用户与申请不匹配')
                    history = [dict(x) for x in c.execute('SELECT role,content FROM messages WHERE service_id=? ORDER BY id',(s['service_id'],))]
                    result = {'summary':snapshot(s),'messages':history,'capabilities':ai_client.capabilities()}
                elif path == '/api/staff':
                    result = {'pending': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='pending' ORDER BY started_at")],
                              'processed': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='processed' ORDER BY started_at DESC")]}
                elif path == '/api/matches':
                    s = service(c, str(data.get('service_id','')))
                    if s['status'] != 'pending': raise ValueError('此服务已处理')
                    result = {'matches': matches(s), 'public_options': public_service_options(s)}
                elif path == '/api/assign':
                    s = service(c, str(data.get('service_id','')))
                    if s['status'] != 'pending': raise ValueError('此服务已处理')
                    person = next((p for p in matches(s) if p['服务人员名称'] == data.get('name') and p['服务人员联系方式'] == data.get('phone')), None)
                    if not person: raise ValueError('该人员已不符合分配条件')
                    c.execute("UPDATE services SET staff_name=?,staff_phone=?,organization=?,organization_district=?,service_slot=?,status='processed' WHERE service_id=?",
                              (person['服务人员名称'],person['服务人员联系方式'],person['社区服务机构名称'],person['社区服务机构区域'],person['服务时间段'],s['service_id']))
                    result = {'ok': True}
                elif path == '/api/detail':
                    s = service(c, str(data.get('service_id','')))
                    if s['username'] != str(data.get('username','')) or s['status'] != 'processed': raise ValueError('无法查看详情')
                    result = {'text': detail(s)}
                else: raise ValueError('未知操作')
            self.send(200, result)
        except ai_client.ProviderError as e:
            self.send(502, {'error': str(e), 'retryable': True})
        except (ValueError, KeyError, sqlite3.Error) as e:
            self.send(400, {'error': str(e)})
        except Exception as e:
            self.send(500, {'error': '服务器暂时无法完成请求，请重试。'})


if __name__ == '__main__':
    init()
    print('打开 http://127.0.0.1:8000')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
