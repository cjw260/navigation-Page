import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('navigation_admin',ROOT/'admin/server.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();app.DATA=Path(self.tmp.name);app.SITE=ROOT;app.SECURE=False;app.COOKIE='nav-session';app.LOGIN_ATTEMPTS.clear();app.init()
        salt=b'synthetic-test-salt'
        auth={'username':'admin','salt':salt.hex(),'hash':hashlib.scrypt(b'test-password-only',salt=salt,n=16384,r=8,p=1).hex()}
        app.atomic_write(app.DATA/'auth.json',json.dumps(auth).encode(),0o600)
        self.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);app.ORIGIN=f'http://127.0.0.1:{self.http.server_port}'
        self.thread=threading.Thread(target=self.http.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start()
        self.cookie='';self.csrf=''
    def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,method='GET',body=None,auth=True,origin=True,csrf=True,raw=False):
        headers={}
        if auth and self.cookie:headers['Cookie']=self.cookie
        if origin:headers['Origin']=app.ORIGIN
        if csrf:headers['X-CSRF-Token']=self.csrf
        if body is not None:
            headers['Content-Type']='application/octet-stream' if raw else 'application/json';body=body if raw else json.dumps(body).encode()
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=100);c.request(method,'/navigation-admin/'+path,body,headers);r=c.getresponse();b=r.read();h=dict(r.getheaders());status=r.status;c.close()
        return status,h,json.loads(b) if h.get('Content-Type','').startswith('application/json') else b
    def login(self):
        status,h,b=self.request('api/login','POST',{'username':'admin','password':'test-password-only'});self.assertEqual(status,200);self.cookie=h['Set-Cookie'].split(';')[0];self.csrf=b['csrf'];return h
    def test_requires_login_and_has_no_public_password_setup(self):
        self.assertEqual(self.request('api/projects')[0],401)
        self.assertEqual(self.request('api/publish','POST',{'revision':1})[0],401)
        (app.DATA/'auth.json').unlink();self.assertEqual(self.request('api/login','POST',{'username':'admin','password':'x'})[0],503)
    def test_sessions_csrf_origin_and_logout(self):
        h=self.login();self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
        self.assertEqual(self.request('api/publish','POST',{'revision':1},origin=False)[0],403)
        self.assertEqual(self.request('api/publish','POST',{'revision':1},csrf=False)[0],403)
        self.assertEqual(self.request('api/logout','POST',{})[0],200);self.assertEqual(self.request('api/projects')[0],401)
    def test_draft_preview_publish_and_restart_preserve_data(self):
        self.login();before=(app.DATA/'public/index.html').read_bytes();doc=app.document();doc['projects'][0]['title']='简历 <script>不执行</script>';doc['projects'][0]['url']='https://resume.cjw32.xyz/'
        status,_,saved=self.request('api/projects','PUT',doc);self.assertEqual(status,200);self.assertEqual((app.DATA/'public/index.html').read_bytes(),before)
        status,h,preview=self.request('preview');self.assertEqual(status,200);self.assertIn(b'&lt;script&gt;',preview);self.assertIn(b'<base href="/">',preview);self.assertIn('noindex',h['X-Robots-Tag'])
        self.assertEqual(self.request('api/publish','POST',{'revision':saved['revision']})[0],200)
        content=(app.DATA/'public/index.html').read_bytes();self.assertNotEqual(content,before);app.init();self.assertEqual((app.DATA/'public/index.html').read_bytes(),content);self.assertEqual(len(list((app.DATA/'backups').glob('*.json'))),1)
    def test_stale_edit_or_publish_is_rejected(self):
        self.login();doc=app.document();self.assertEqual(self.request('api/projects','PUT',doc)[0],200);self.assertEqual(self.request('api/projects','PUT',doc)[0],409);self.assertEqual(self.request('api/publish','POST',{'revision':1})[0],409)
    def test_unsafe_links_and_arbitrary_media_are_rejected(self):
        for url in ['javascript:alert(1)','//evil.example/','/\\evil.example','https://user:pass@evil.example/','data:text/html,bad']:
            doc=app.document();doc['projects'][0]['url']=url
            with self.assertRaises(app.Problem):app.validate(doc['projects'])
        doc=app.document();doc['projects'][0]['cover']='/etc/passwd'
        with self.assertRaises(app.Problem):app.validate(doc['projects'])
    def test_publish_failure_retains_previous_page_and_state(self):
        doc=app.document();doc['projects'][0]['title']='changed';saved=app.save_draft(doc);before=(app.DATA/'public/index.html').read_bytes()
        original=app.atomic_write
        def fail_once(path,body,mode=0o644):
            if path.name=='index.html' and b'changed' in body:raise OSError('simulated write failure')
            return original(path,body,mode)
        with patch.object(app,'atomic_write',side_effect=fail_once):
            with self.assertRaises(OSError):app.publish({'revision':saved['revision']})
        self.assertEqual((app.DATA/'public/index.html').read_bytes(),before);self.assertEqual(app.document()['publishedRevision'],1)
    def test_hidden_and_sorted_projects_render_correctly(self):
        doc=app.document();projects=doc['projects'][::-1];projects[1]['visible']=False;body=app.render(projects).decode();cards=body.split(app.START)[1].split(app.END)[0]
        self.assertLess(cards.index('个人博客'),cards.index('协同思维导图'));self.assertNotIn('协同表格工具',cards);self.assertIn('data-preview=',cards);self.assertNotIn('<source',cards)
    def test_invalid_upload_and_private_files_are_not_exposed(self):
        self.login();self.assertEqual(self.request('api/upload/video','POST',b'#EXTM3U\nhttp://localhost/',raw=True)[0],400)
        self.assertEqual(self.request('../auth.json')[0],404)
        self.assertEqual(self.request('api/upload/cover','POST',b'<svg onload="alert(1)"></svg>',raw=True)[0],400)
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg not installed')
    def test_real_video_and_cover_upload_transcode_and_original_retention(self):
        self.login();src=app.DATA/'fixture.mp4'
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=20','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(src)],check=True)
        status,_,media=self.request('api/upload/video','POST',src.read_bytes(),raw=True);self.assertEqual(status,200);self.assertRegex(media['path'],r'^/navigation-media/[a-f0-9]{64}\.mp4$');self.assertEqual(len(list((app.DATA/'originals').iterdir())),1)
        image=app.DATA/'fixture.png';subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(src),'-frames:v','1',str(image)],check=True)
        status,_,cover=self.request('api/upload/cover','POST',image.read_bytes(),raw=True);self.assertEqual(status,200);self.assertTrue(cover['path'].endswith('.jpg'));doc=app.document();doc['projects'][0].update(video=media['path'],cover=cover['path']);self.assertEqual(self.request('api/projects','PUT',doc)[0],200)

if __name__=='__main__':unittest.main()
