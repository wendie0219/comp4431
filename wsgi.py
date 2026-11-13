"""WSGI entry point for: gunicorn wsgi:app"""
from io import BytesIO
from server import Handler, init

init()


class Bridge:
    def __init__(self, environ):
        self.path = environ.get('PATH_INFO', '/')
        self.headers = {'Content-Length': environ.get('CONTENT_LENGTH', '0')}
        self.rfile = environ['wsgi.input']
        self.wfile = BytesIO()
        self.status = '200 OK'
        self.response_headers = []

    def send_response(self, code):
        from http import HTTPStatus
        self.status = f'{code} {HTTPStatus(code).phrase}'

    def send_header(self, key, value):
        self.response_headers.append((key, value))

    def end_headers(self):
        pass

    send = Handler.send


def app(environ, start_response):
    bridge = Bridge(environ)
    if environ.get('REQUEST_METHOD') == 'GET':
        Handler.do_GET(bridge)
    elif environ.get('REQUEST_METHOD') == 'POST':
        Handler.do_POST(bridge)
    else:
        bridge.send(405, {'error': '不支持的请求方法'})
    start_response(bridge.status, bridge.response_headers)
    return [bridge.wfile.getvalue()]
