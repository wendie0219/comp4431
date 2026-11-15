import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import ai_client
import server


class ChatContractTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db_patch=patch.object(server,'DB',Path(self.folder.name)/'test.sqlite3');self.db_patch.start()
        self.config_patch=patch.object(ai_client,'config',return_value={});self.config_patch.start()
        server.init();self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.http.server_port)
        self.start=self.post('start',{'username':'jiwen','appointment_id':'A20261116001'})
        self.sid=self.start['service_id'];self.seq=0
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.config_patch.stop();self.db_patch.stop();self.folder.cleanup()
    def post(self,path,data):
        req=urllib.request.Request(self.base+'/api/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:return json.load(response)
    def say(self,text,rid=None):
        self.seq+=1
        return self.post('message',{'username':'jiwen','service_id':self.sid,'message':text,'request_id':rid or str(self.seq)})
    def test_summary_unknown_review_submit_and_replay(self):
        self.assertIsNone(self.start['summary']['escort'])
        for text in ['是','需要陪诊，需要去程，不需要回程，需要轮椅','是','南区','测试地址','是']:
            result=self.say(text)
        self.assertEqual(result['summary']['stage'],'final_confirm')
        self.assertEqual(result['summary']['status'],'draft')
        self.assertFalse(result['summary']['return_trip'])
        final=self.say('确认提交','submit-once')
        self.assertTrue(final['done'])
        self.assertEqual(final,self.say('确认提交','submit-once'))
        with server.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE content='确认提交'").fetchone()[0],1)
    def test_provider_failure_rolls_back_and_retry_succeeds(self):
        with patch.object(ai_client,'extract',side_effect=ai_client.ProviderError('接口超时')):
            with self.assertRaises(urllib.error.HTTPError) as error:self.say('是','retry-same')
            self.assertEqual(error.exception.code,502)
        with server.db() as c:
            self.assertEqual(server.service(c,self.sid)['stage'],'appointment_confirm')
            self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE role='user'").fetchone()[0],0)
        self.assertEqual(self.say('是','retry-same')['summary']['stage'],'services')
    def test_model_null_is_not_overwritten_by_keywords(self):
        self.say('是')
        with patch.object(ai_client,'extract',return_value={'escort':None,'outbound':None,'return_trip':None,'wheelchair':None}):
            result=self.say('陪诊是什么意思？')
        self.assertIsNone(result['summary']['escort'])
    def test_invalid_model_json_rejected(self):
        with patch.object(ai_client,'config',return_value={'OPENAI_API_KEY':'test','OPENAI_BASE_URL':'https://example.com/v1','OPENAI_MODEL':'test'}),patch.object(ai_client,'request_json',return_value={'choices':[{'message':{'content':'{"escort":"yes"}'}}]}):
            with self.assertRaises(ai_client.ProviderError):ai_client.extract('services','test')


if __name__=='__main__':unittest.main()
