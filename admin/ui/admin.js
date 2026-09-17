'use strict';
const $ = id => document.getElementById(id);
let csrf = '', data = null, selected = null, dirty = false, busy = false, previewed = null;
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function state() {
  $('controls').disabled = busy;
  $('publish').disabled = busy || dirty || previewed !== data?.revision;
  $('draft-state').textContent = dirty ? '有未保存的修改' : '草稿已保存';
}
function change() { dirty = true; previewed = null; state(); }
async function api(path, method = 'GET', body) {
  const response = await fetch('/navigation-admin/api/' + path, {method, headers: {'Content-Type':'application/json','X-CSRF-Token':csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== 'login') showLogin(); throw new Error(result.error || '操作失败'); }
  return result;
}
function showLogin() { $('login').hidden = false; $('app').hidden = true; csrf = ''; }
function current() { return data.projects.find(p => p.id === selected); }
function renderList() {
  $('projects').replaceChildren();
  data.projects.forEach((p,i) => {
    const row = document.createElement('div'); row.className = 'project-row' + (p.id === selected ? ' selected' : '');
    const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'secondary select'; choose.textContent = p.title + (p.visible ? '' : ' · 已隐藏'); choose.onclick = () => { selected = p.id; render(); }; row.append(choose);
    for (const [step,label] of [[-1,'↑'],[1,'↓']]) {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'secondary move'; b.textContent = label; b.setAttribute('aria-label', label === '↑' ? '上移 '+p.title : '下移 '+p.title); b.disabled = i+step < 0 || i+step >= data.projects.length;
      b.onclick = () => { [data.projects[i],data.projects[i+step]]=[data.projects[i+step],data.projects[i]]; change(); renderList(); }; row.append(b);
    }
    $('projects').append(row);
  });
}
function render() {
  renderList(); const p = current(); $('fields').hidden = !p; $('empty').hidden = !!p;
  $('publication').textContent = data.publishedAt ? '最近发布：'+new Date(data.publishedAt).toLocaleString('zh-CN') : '当前首页内容已导入；尚未通过后台发布';
  if (p) {
    for (const k of ['title','subtitle','url']) $(k).value = p[k];
    $('visible').checked = p.visible; $('visibility-label').textContent = p.visible ? '首页可见' : '已隐藏';
    $('cover-preview').hidden = !p.cover; if (p.cover) $('cover-preview').src = p.cover; else $('cover-preview').removeAttribute('src');
    $('video-state').textContent = p.video ? '已配置轻量视频，保存并预览可查看效果' : '未配置视频，卡片只显示封面';
    $('clear-video').disabled = !p.video;
    $('cover-file').value = ''; $('video-file').value = '';
  }
  state();
}
async function load() { data = await api('projects'); selected = data.projects[0]?.id; dirty = false; previewed = null; $('login').hidden = true; $('app').hidden = false; render(); }
async function action(fn) {
  if (busy) return; busy = true; state();
  try { await fn(); } catch (error) { message(error.message,true); } finally { busy = false; state(); }
}
async function save() { data = await api('projects','PUT',{revision:data.revision,projects:data.projects}); dirty = false; previewed = null; render(); }
$('login-form').onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { const fields = new FormData(event.target); const result = await api('login','POST',{username:fields.get('username'),password:fields.get('password')}); csrf = result.csrf; event.target.elements.password.value = ''; await load(); message('已登录'); } catch (error) { message(error.message,true); } finally { button.disabled = false; }
};
$('logout').onclick = () => action(async () => { await api('logout','POST',{}); showLogin(); message('已退出登录'); });
for (const key of ['title','subtitle','url']) $(key).oninput = () => { current()[key]=$(key).value; change(); if (key==='title') renderList(); };
$('visible').onchange = () => { current().visible=$('visible').checked; change(); renderList(); $('visibility-label').textContent=current().visible?'首页可见':'已隐藏'; };
$('add').onclick = () => { const id=crypto.randomUUID(); data.projects.push({id,title:'新项目',subtitle:'',url:'',cover:'',video:'',visible:true}); selected=id; change(); render(); };
$('remove').onclick = () => { if (!confirm('从草稿移除这个项目？点击发布前，线上首页不会变化；已上传素材会保留。')) return; data.projects=data.projects.filter(p=>p.id!==selected); selected=data.projects[0]?.id; change(); render(); };
$('clear-video').onclick = () => { current().video=''; change(); render(); };
function upload(file,kind) {
  return new Promise((resolve,reject) => {
    const xhr=new XMLHttpRequest(); xhr.open('POST','/navigation-admin/api/upload/'+kind); xhr.setRequestHeader('Content-Type','application/octet-stream'); xhr.setRequestHeader('X-CSRF-Token',csrf); xhr.timeout=120000;
    xhr.upload.onprogress=e=>{ if(e.lengthComputable) message(e.loaded===e.total?'上传完成，正在生成轻量素材，请稍候…':'上传中：'+Math.round(e.loaded/e.total*100)+'%'); };
    xhr.onload=()=>{ try { const result=JSON.parse(xhr.responseText); if(xhr.status>=200&&xhr.status<300) resolve(result); else reject(new Error(result.error||'上传失败')); } catch { reject(new Error('上传未完成，请稍后重试')); } };
    xhr.onerror=xhr.ontimeout=()=>reject(new Error('上传中断或超时，请重试')); xhr.send(file);
  });
}
for (const kind of ['cover','video']) $(kind+'-file').onchange = () => {
  const file=$(kind+'-file').files[0]; if(!file) return;
  const max=kind==='video'?40:15;
  if(file.size>max*1024*1024){ message('文件超过 '+max+' MiB 限制',true); $(kind+'-file').value=''; return; }
  action(async()=>{ const p=current(); const result=await upload(file,kind); p[kind]=result.path; change(); render(); message('素材处理完成，展示文件约 '+Math.round(result.bytes/1024)+' KiB；请保存并预览。'); });
};
$('save').onclick = () => action(async()=>{ await save(); message('草稿已保存，线上首页未改变'); });
$('preview').onclick = () => {
  const tab=window.open('about:blank','_blank'); if(tab) tab.opener=null;
  action(async()=>{ try { if(dirty) await save(); if(!tab) throw new Error('请允许打开预览窗口后重试'); tab.location.href='/navigation-admin/preview'; previewed=data.revision; message('预览已打开。确认封面、视频和链接后，可点击发布到首页。'); } catch(error) { tab?.close(); throw error; } });
};
$('publish').onclick = () => { if(!confirm('确认将当前预览版本发布到首页？')) return; action(async()=>{ data=await api('publish','POST',{revision:data.revision}); render(); message('已发布。刷新公开首页即可查看，旧内容已备份。'); }); };
window.addEventListener('beforeunload',event=>{ if(dirty){event.preventDefault();event.returnValue='';} });
(async()=>{ try { const session=await api('session'); csrf=session.csrf; await load(); } catch { showLogin(); } })();
