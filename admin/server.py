"""Single-owner project editor. Publishes static HTML; never exposes original uploads."""
import collections
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DATA = Path(os.environ.get('DATA_DIR', '/data'))
SITE = Path(os.environ.get('SITE_DIR', '/app/site'))
UI = Path(__file__).parent / 'ui'
ORIGIN = os.environ.get('PUBLIC_ORIGIN', 'https://cjw32.xyz').rstrip('/')
SECURE = os.environ.get('SECURE_COOKIES', '1') == '1'
COOKIE = '__Secure-nav-session' if SECURE else 'nav-session'
LOCK = threading.RLock()
MEDIA_LOCK = threading.Lock()
LOGIN_LOCK = threading.Lock()
LOGIN_ATTEMPTS = collections.deque()
START = '<!-- PROJECT_CARDS_START -->'
END = '<!-- PROJECT_CARDS_END -->'

class Problem(Exception):
    def __init__(self, status, message): self.status, self.message = status, message

def connect():
    c = sqlite3.connect(DATA / 'content.sqlite3', timeout=10)
    c.row_factory = sqlite3.Row
    return c

def atomic_write(path, body, mode=0o644):
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(body); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def render(projects):
    cards = []
    for p in projects:
        if not p['visible']: continue
        title, subtitle, url, cover, video = [html.escape(p[k], quote=True) for k in ['title','subtitle','url','cover','video']]
        media = f'<video class="project-card-video object-cover w-full h-full absolute inset-0 z-0 opacity-0" muted loop playsinline preload="none" data-preview="{video}" aria-hidden="true"></video>' if video else ''
        cards.append(f'''<article class="project-card fade-in-up group aspect-video">
  <div class="project-card-image-container w-full h-full bg-surface-container-high relative">
    <a class="card-link" href="{url}" aria-label="访问{title}"></a>
    {media}
    <img alt="{title}" class="project-card-image object-cover w-full h-full absolute inset-0 mix-blend-multiply z-10" src="{cover}" decoding="async">
    <div class="project-card-overlay opacity-100 md:opacity-0">
      <a class="project-btn bg-white text-black font-body-md text-label-md px-8 py-3 rounded-full hover:bg-gray-200 transition-colors duration-200 flex items-center gap-2 opacity-100 scale-100 translate-y-0 md:opacity-0 md:scale-90 md:translate-y-10" href="{url}">访问项目 <span class="material-symbols-outlined" style="font-size:18px">arrow_forward</span></a>
      <div class="project-card-info pointer-events-none opacity-100 translate-y-0 md:opacity-0 md:translate-y-20">
        <span class="font-display-lg text-label-md uppercase tracking-widest opacity-80">{subtitle}</span>
        <h2 class="font-display-lg text-headline-lg-mobile">{title}</h2>
      </div>
    </div>
  </div>
</article>''')
    template = (SITE / 'index.html').read_text()
    before, remaining = template.split(START, 1)
    _, after = remaining.split(END, 1)
    return (before + START + '\n' + '\n'.join(cards) + '\n' + END + after).encode()

def document():
    with connect() as c:
        row = c.execute('SELECT * FROM content WHERE id=1').fetchone()
    return {'revision':row['revision'], 'projects':json.loads(row['draft']), 'publishedAt':row['published_at'], 'publishedRevision':row['published_revision']}

def init():
    DATA.mkdir(parents=True, exist_ok=True)
    for d in ['public', 'public/media', 'originals', 'backups', 'incoming']:
        (DATA/d).mkdir(parents=True, exist_ok=True)
        os.chmod(DATA/d, 0o755 if d.startswith('public') else 0o700)
    with connect() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS content(id INTEGER PRIMARY KEY, draft TEXT NOT NULL, published TEXT NOT NULL, revision INTEGER NOT NULL, published_revision INTEGER NOT NULL, published_at TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS media(path TEXT PRIMARY KEY, kind TEXT NOT NULL, original TEXT NOT NULL, bytes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY AUTOINCREMENT, projects TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
        if not c.execute('SELECT 1 FROM content').fetchone():
            seed = (SITE/'admin/seed.json').read_text()
            c.execute('INSERT INTO content VALUES(1,?,?,1,1,NULL)', (seed,seed))
        published = json.loads(c.execute('SELECT published FROM content WHERE id=1').fetchone()[0])
    # Always use the current code template, while keeping the owner's published data.
    atomic_write(DATA/'public/index.html', render(published))

def validate(projects):
    if not isinstance(projects,list) or len(projects)>100: raise Problem(400,'最多支持 100 个项目')
    result=[]; ids=set()
    with connect() as c:
        media={r['path']:r['kind'] for r in c.execute('SELECT path,kind FROM media')}
    seeds=json.loads((SITE/'admin/seed.json').read_text())
    for p in seeds:
        media[p['cover']]='cover'
        if p['video']: media[p['video']]='video'
    for p in projects:
        if not isinstance(p,dict): raise Problem(400,'项目格式错误')
        q={}
        for key,limit in [('id',64),('title',120),('subtitle',160),('url',2048),('cover',250),('video',250)]:
            v=p.get(key,'')
            if not isinstance(v,str) or len(v)>limit or any(ord(ch)<32 for ch in v): raise Problem(400,'项目字段无效或过长')
            q[key]=v.strip()
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',q['id']) or q['id'] in ids: raise Problem(400,'项目标识重复或无效')
        ids.add(q['id'])
        if not q['title']: raise Problem(400,'请填写项目名称')
        u=q['url']; parsed=urlsplit(u)
        if '\\' in u or any(ch.isspace() for ch in u) or not ((u.startswith('/') and not u.startswith('//')) or (parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password)):
            raise Problem(400,'项目地址必须是 HTTPS 网址或以单个 / 开头的站内路径')
        if media.get(q['cover'])!='cover': raise Problem(400,'请上传有效的封面图片')
        if q['video'] and media.get(q['video'])!='video': raise Problem(400,'视频引用无效')
        if not isinstance(p.get('visible'),bool): raise Problem(400,'显示状态无效')
        q['visible']=p['visible'];result.append(q)
    return result

def save_draft(body):
    projects=validate(body.get('projects'))
    with LOCK, connect() as c:
        c.execute('BEGIN IMMEDIATE')
        revision=c.execute('SELECT revision FROM content WHERE id=1').fetchone()[0]
        if body.get('revision')!=revision: raise Problem(409,'草稿已被其他页面修改，请刷新后再编辑')
        c.execute('UPDATE content SET draft=?,revision=revision+1 WHERE id=1',(json.dumps(projects,ensure_ascii=False),))
    return document()

def publish(body):
    with LOCK, connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM content WHERE id=1').fetchone()
        if body.get('revision')!=row['revision']: raise Problem(409,'草稿已经变化，请重新预览后发布')
        now=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        content=render(json.loads(row['draft']))
        old=(DATA/'public/index.html').read_bytes()
        # Durable previous content is also kept as a private, readable backup.
        backup=DATA/'backups'/f'published-{time.time_ns()}.json'
        atomic_write(backup,row['published'].encode(),0o600)
        try:
            c.execute('INSERT INTO versions(projects,created_at) VALUES(?,?)',(row['published'],now))
            c.execute('UPDATE content SET published=draft,published_revision=revision,published_at=? WHERE id=1',(now,))
            atomic_write(DATA/'public/index.html',content)
            c.commit()
        except Exception:
            atomic_write(DATA/'public/index.html',old)
            raise
    return document()

def encode_media(incoming, kind):
    prefix=incoming.read_bytes()[:16] if incoming.stat().st_size<32 else None
    if prefix is None:
        with incoming.open('rb') as f: prefix=f.read(16)
    is_image=prefix.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n')) or (prefix[:4]==b'RIFF' and prefix[8:12]==b'WEBP')
    is_video=prefix[4:8]==b'ftyp' or prefix[:4]==b'\x1aE\xdf\xa3'
    if not (is_image if kind=='cover' else is_video): raise Problem(400,'封面支持 JPG、PNG、WebP；视频支持 MP4、WebM')
    probe=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(incoming)],capture_output=True,timeout=15)
    if probe.returncode: raise Problem(400,'无法读取这个媒体文件')
    info=json.loads(probe.stdout);video=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),{})
    if not video or video.get('width',0)*video.get('height',0)>24000000: raise Problem(400,'媒体尺寸无效或超过 2400 万像素')
    fd,target=tempfile.mkstemp(suffix='.jpg' if kind=='cover' else '.mp4',dir=DATA/'incoming');os.close(fd)
    try:
        args=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-threads','1','-protocol_whitelist','file,pipe','-i',str(incoming),'-map','0:v:0','-map_metadata','-1','-an','-threads','1','-filter_threads','1']
        if kind=='cover': args+=['-frames:v','1','-vf','scale=1280:720:force_original_aspect_ratio=decrease','-c:v','mjpeg','-q:v','3']
        else: args+=['-t','12','-vf',"scale='min(720,iw)':-2,fps=20",'-c:v','libx264','-preset','veryfast','-crf','29','-maxrate','500k','-bufsize','1000k','-pix_fmt','yuv420p','-movflags','+faststart']
        process=subprocess.run(args+[target],capture_output=True,timeout=90)
        if process.returncode: raise Problem(400,'媒体处理失败，请使用常见图片或视频格式')
        blob=Path(target).read_bytes();digest=hashlib.sha256(blob).hexdigest();suffix=Path(target).suffix
        public_path=f'/navigation-media/{digest}{suffix}'
        original_name=hashlib.sha256(incoming.read_bytes()).hexdigest()
        os.replace(incoming,DATA/'originals'/original_name)
        atomic_write(DATA/'public/media'/f'{digest}{suffix}',blob)
        with connect() as c:
            c.execute('INSERT OR REPLACE INTO media VALUES(?,?,?,?)',(public_path,kind,original_name,len(blob)))
        return {'path':public_path,'bytes':len(blob),'kind':kind,'previewSeconds':12 if kind=='video' else None}
    finally:
        Path(target).unlink(missing_ok=True)

class Handler(BaseHTTPRequestHandler):
    server_version='NavigationAdmin'
    def log_message(self,format,*args): pass
    def send(self,status,body,ctype='application/json; charset=utf-8',cookie=None):
        if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        for k,v in [('Content-Type',ctype),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex, nofollow'),('Referrer-Policy','same-origin')]: self.send_header(k,v)
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)
    def body(self,limit=100000):
        try: length=int(self.headers.get('Content-Length','-1'))
        except ValueError: raise Problem(400,'请求长度无效')
        if length<0: raise Problem(411,'需要请求长度')
        if length>limit: raise Problem(413,'文件或内容超过大小限制')
        return length
    def json_body(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise Problem(415,'需要 JSON 格式')
        value=json.loads(self.rfile.read(self.body()))
        if not isinstance(value,dict): raise Problem(400,'请求格式错误')
        return value
    def session(self):
        try:
            cookie=SimpleCookie(self.headers.get('Cookie','')); token=cookie[COOKIE].value
        except (KeyError,ValueError): raise Problem(401,'请先登录')
        with connect() as c: row=c.execute('SELECT * FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row: raise Problem(401,'登录已失效，请重新登录')
        return row
    def origin(self):
        if self.headers.get('Origin')!=ORIGIN: raise Problem(403,'请求来源不匹配')
    def csrf(self,row):
        self.origin()
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),row['csrf']): raise Problem(403,'请刷新页面后重试')
    def login(self):
        self.origin(); body=self.json_body()
        auth_file=DATA/'auth.json'
        if not auth_file.exists(): raise Problem(503,'后台尚未设置密码，请先在服务器执行设置密码命令')
        with LOGIN_LOCK:
            now=time.time()
            while LOGIN_ATTEMPTS and LOGIN_ATTEMPTS[0]<now-60: LOGIN_ATTEMPTS.popleft()
            if len(LOGIN_ATTEMPTS)>=6: raise Problem(429,'登录尝试过多，请稍后再试')
            LOGIN_ATTEMPTS.append(now)
            auth=json.loads(auth_file.read_text()); password=body.get('password','')
            if not isinstance(password,str) or len(password)>256: raise Problem(400,'密码格式无效')
            key=hashlib.scrypt(password.encode(),salt=bytes.fromhex(auth['salt']),n=16384,r=8,p=1).hex()
            if body.get('username')!=auth['username'] or not hmac.compare_digest(key,auth['hash']): raise Problem(401,'账号或密码不正确')
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        with connect() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(now,))
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),csrf,now+8*3600))
        cookie=f'{COOKIE}={token}; Path=/navigation-admin/; HttpOnly; SameSite=Strict; Max-Age=28800'+('; Secure' if SECURE else '')
        self.send(200,{'csrf':csrf,'username':auth['username']},cookie=cookie)
    def route(self,method):
        path=urlsplit(self.path).path
        if method=='GET':
            if path=='/healthz': return self.send(200,{'status':'ok'})
            files={'/navigation-admin/':('index.html','text/html; charset=utf-8'),'/navigation-admin/admin.js':('admin.js','text/javascript; charset=utf-8'),'/navigation-admin/admin.css':('admin.css','text/css; charset=utf-8')}
            if path in files:
                f,ctype=files[path]; return self.send(200,(UI/f).read_bytes(),ctype)
            row=self.session()
            if path=='/navigation-admin/api/session': return self.send(200,{'csrf':row['csrf'],'username':'admin'})
            if path=='/navigation-admin/api/projects': return self.send(200,document())
            if path=='/navigation-admin/preview':
                with LOCK: page=render(document()['projects']).replace(b'<head>', b'<head><base href="/">', 1)
                return self.send(200,page,'text/html; charset=utf-8')
            raise Problem(404,'未找到页面')
        if method=='POST' and path=='/navigation-admin/api/login': return self.login()
        row=self.session(); self.csrf(row)
        if method=='POST' and path=='/navigation-admin/api/logout':
            with connect() as c: c.execute('DELETE FROM sessions WHERE token=?',(row['token'],))
            return self.send(200,{'ok':True},cookie=f'{COOKIE}=; Path=/navigation-admin/; HttpOnly; SameSite=Strict; Max-Age=0'+('; Secure' if SECURE else ''))
        if method=='PUT' and path=='/navigation-admin/api/projects': return self.send(200,save_draft(self.json_body()))
        if method=='POST' and path=='/navigation-admin/api/publish': return self.send(200,publish(self.json_body()))
        if method=='POST' and path in ['/navigation-admin/api/upload/cover','/navigation-admin/api/upload/video']:
            kind=path.rsplit('/',1)[-1]; length=self.body(40*1024*1024 if kind=='video' else 15*1024*1024)
            if shutil.disk_usage(DATA).free<length*3+512*1024*1024: raise Problem(507,'服务器存储空间不足')
            if not MEDIA_LOCK.acquire(blocking=False): raise Problem(409,'另一个媒体文件正在处理，请稍后重试')
            fd,tmp=tempfile.mkstemp(dir=DATA/'incoming');incoming=Path(tmp)
            try:
                with os.fdopen(fd,'wb') as f:
                    remaining=length
                    while remaining:
                        chunk=self.rfile.read(min(65536,remaining))
                        if not chunk: raise Problem(400,'上传中断')
                        f.write(chunk);remaining-=len(chunk)
                return self.send(200,encode_media(incoming,kind))
            finally:
                incoming.unlink(missing_ok=True); MEDIA_LOCK.release()
        raise Problem(404,'未找到操作')
    def handle_request(self,method):
        self.connection.settimeout(120)
        try: self.route(method)
        except Problem as e: self.send(e.status,{'error':e.message})
        except (ValueError,json.JSONDecodeError): self.send(400,{'error':'请求或文件格式错误'})
        except subprocess.TimeoutExpired: self.send(422,{'error':'媒体处理超时，请上传较短或较小的文件'})
        except (BrokenPipeError,ConnectionResetError,TimeoutError): pass
        except Exception:
            self.send(500,{'error':'操作未完成，请稍后重试；已发布页面保持不变'})
    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PUT(self): self.handle_request('PUT')

if __name__=='__main__':
    os.umask(0o077);init()
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
