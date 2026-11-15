"""Local development launcher; use the existing DB unless CAREVISIT_DB is set."""
import os
from pathlib import Path
import server

if os.getenv('CAREVISIT_DB'):
    server.DB = Path(os.environ['CAREVISIT_DB'])
server.init()
print('CareVisit: http://127.0.0.1:8000', flush=True)
server.ThreadingHTTPServer(('127.0.0.1',8000),server.Handler).serve_forever()
