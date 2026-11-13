"""Community hospital assistance demo. Run: python3 server.py"""
import csv
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


def env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


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
    """OpenAI-compatible chat completions API. Returns validated JSON or None."""
    env()
    key, url = os.getenv('OPENAI_API_KEY', ''), os.getenv('OPENAI_BASE_URL', '')
    if not key or not url:
        return None
    endpoint = url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'
    prompt = ('只提取用户这句话明确表达的信息。输出JSON对象，不要解释。'
              '对于confirm阶段输出{"yes":true/false/null}。'
              '对于services阶段输出escort,outbound,return_trip,wheelchair四个键，各为true/false/null；'
              '修改时也只输出明确修改的键。对于district阶段输出{"district":字符串或null}；'
              '对于address阶段输出{"address":字符串或null}。'
              f'当前阶段:{stage}。当前询问项目:{missing or "无"}。')
    payload = json.dumps({'model': 'gpt-6-luna', 'temperature': 0,
                          'response_format': {'type': 'json_object'},
                          'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': user_text}]}, ensure_ascii=False).encode()
    req = urllib.request.Request(endpoint, data=payload, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(json.loads(r.read())['choices'][0]['message']['content'])
    except Exception:
        return None


def yesno(text):
    t = text.strip().lower()
    if re.search(r'不需要|不用|不要|没有|否|不是|no|取消|有误|不对|修改', t):
        return False
    if re.search(r'需要|要|是|对|正确|确认|没错|无误|yes|好|可以', t):
        return True
    return None


def extract_services(text, asked):
    result = llm_extract('services', text, asked) or {}
    out = {k: result[k] for k in FIELDS if type(result.get(k)) is bool}
    patterns = {'escort': r'陪诊', 'outbound': r'去程|接我|接送去|送我去',
                'return_trip': r'回程|送我回|接我回', 'wheelchair': r'轮椅'}
    for k, pattern in patterns.items():
        if k not in out:
            m = re.search(r'(不需要|不用|不要|需要|要|有|没有)?\s*(' + pattern + r')', text)
            if m:
                prefix = m.group(1) or text[max(0, m.start()-4):m.start()]
                out[k] = not bool(re.search(r'不需要|不用|不要|没有', prefix))
    if asked and asked not in out:
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
    if stage == 'appointment_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) and type(parsed.get('yes')) is bool else yesno(text)
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
        answer = parsed.get('yes') if isinstance(parsed, dict) and type(parsed.get('yes')) is bool else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'services_correct', '请告诉我需要修改什么？例如“去程改为需要”。')}
        if answer is None:
            return {'reply': reply(c, sid, '请回答服务需求是否无误；如有误，请说“有误”。')}
        return {'reply': update_stage(c, sid, 'district', '您是哪个区的？')}
    if stage in ('district', 'district_correct'):
        parsed = llm_extract('district', text)
        district = parsed.get('district') if isinstance(parsed, dict) else None
        district = (district or text).strip()[:60]
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
        address = (address or text).strip()[:200]
        if not address:
            return {'reply': reply(c, sid, '请告诉我您的具体住址。')}
        c.execute('UPDATE services SET address=? WHERE service_id=?', (address, sid))
        s = service(c, sid)
        return {'reply': update_stage(c, sid, 'address_confirm', f'您所在的地区是{s["district"]}，具体住址是{s["address"]}。请确认是否无误？')}
    if stage == 'address_confirm':
        parsed = llm_extract('confirm', text)
        answer = parsed.get('yes') if isinstance(parsed, dict) and type(parsed.get('yes')) is bool else yesno(text)
        if answer is False:
            return {'reply': update_stage(c, sid, 'address_fix_choice', '请问需要修改地区还是具体住址？')}
        if answer is None:
            return {'reply': reply(c, sid, '请确认地区和住址是否无误。')}
        c.execute("UPDATE services SET status='pending',stage='complete' WHERE service_id=?", (sid,))
        return {'reply': reply(c, sid, '您的申请已收到，我们正在处理。您可以稍后在“我的服务信息”查看。'), 'done': True}
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
            if n > 20000: raise ValueError('内容过长')
            data = json.loads(self.rfile.read(n) or b'{}')
            path = urlparse(self.path).path
            with db() as c:
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
                    result = {'service_id': sid, 'reply': reply(c, sid, msg)}
                elif path == '/api/message':
                    sid = str(data.get('service_id',''))
                    s = service(c, sid)
                    content = str(data.get('message','')).strip()[:1000]
                    if not content: raise ValueError('请输入消息')
                    c.execute('INSERT INTO messages(service_id,role,content,created_at) VALUES(?,?,?,?)', (sid,'user',content,now()))
                    result = advance(c, s, content)
                elif path == '/api/staff':
                    result = {'pending': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='pending' ORDER BY started_at")],
                              'processed': [dict(x) for x in c.execute("SELECT * FROM services WHERE status='processed' ORDER BY started_at DESC")]}
                elif path == '/api/matches':
                    s = service(c, str(data.get('service_id','')))
                    if s['status'] != 'pending': raise ValueError('此服务已处理')
                    result = {'matches': matches(s)}
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
        except (ValueError, KeyError, sqlite3.Error) as e:
            self.send(400, {'error': str(e)})
        except Exception as e:
            self.send(500, {'error': f'服务器错误：{e}'})


if __name__ == '__main__':
    init()
    print('打开 http://127.0.0.1:8000')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
