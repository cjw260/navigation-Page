import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../decode/index.html',import.meta.url),'utf8');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{hidden:true,value:'',textContent:'',listeners:{},classList:{toggle(){}},removeAttribute(k){delete this[k];},addEventListener(n,f){this.listeners[n]=f;},focus(){}});return elements.get(id);};
const context=vm.createContext({URL,TextDecoder,Uint8Array,atob,btoa,document:{getElementById:element},navigator:{clipboard:{writeText:async()=>{}}}});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
const decode=input=>context.decodeInput(input);
const encode=text=>Buffer.from(text).toString('base64');
test('complete cc URL and Chinese UTF-8 metadata',()=>{
 const payload={title:'中文标题',link:'https://example.com/path?q=1&x=2'};
 const result=decode('https://example.org/t?cc='+encodeURIComponent(encode(JSON.stringify(payload))));
 assert.equal(result.link,payload.link);assert.match(result.formatted,/中文标题/);
});
test('raw Base64, unpadded Base64URL, percent-encoding',()=>{
 const data=JSON.stringify({link:'https://example.com/中文'});
 for(const encoded of [encode(data),Buffer.from(data).toString('base64url'),encodeURIComponent(encode(data))])assert.equal(decode(encoded).link,'https://example.com/%E4%B8%AD%E6%96%87');
});
test('literal plus signs in cc',()=>{
 const text=JSON.stringify({title:'>>>???',link:'https://example.com/'});
 assert.ok(encode(text).includes('+'));assert.equal(decode('https://example.org/?cc='+encode(text)).link,'https://example.com/');
});
test('decoded plain URL and JSON string',()=>{
 for(const text of ['https://example.com/',JSON.stringify('https://example.com/')])assert.equal(decode(encode(text)).link,'https://example.com/');
});
test('dangerous schemes, credentials, relative links are not clickable',()=>{
 for(const link of ['javascript:alert(1)','data:text/html,x','//example.com/','https://user:pass@example.com/','ftp://example.com/'])assert.equal(decode(encode(JSON.stringify({link}))).link,null);
});
test('arbitrary text, missing link and non-string values',()=>{
 for(const text of ['hello 中文','null','12','{"title":"only"}','{"link":{"url":"https://example.com/"}}']){const r=decode(encode(text));assert.equal(r.link,null);assert.ok(r.formatted);}
});
test('empty, missing cc, invalid Base64, binary, oversized input',()=>{
 for(const input of ['','https://example.com/','a','***','%ZZ','/w==','x'.repeat(200001)])assert.throws(()=>decode(input));
});
test('UI text rendering, stale result invalidation, example and clear',()=>{
 element('input').value=encode(JSON.stringify({link:'https://example.com/',title:'<img src=x onerror=alert(1)>'}));
 element('decode-form').listeners.submit({preventDefault(){}});
 assert.equal(element('open').href,'https://example.com/');assert.equal(element('result').hidden,false);assert.match(element('raw').textContent,/<img/);
 element('input').listeners.input();assert.equal(element('result').hidden,true);assert.equal(element('open').href,undefined);
 element('example').listeners.click();assert.equal(element('destination').textContent,'https://example.com/');
 element('clear').listeners.click();assert.equal(element('input').value,'');assert.equal(element('result').hidden,true);
});
test('no external assets, persistence, requests or HTML interpolation',()=>{
 assert.doesNotMatch(html,/<script[^>]+src=|<link[^>]+href=|\bfetch\s*\(|XMLHttpRequest|localStorage|sessionStorage|innerHTML\s*=/i);assert.match(html,/connect-src 'none'/);
});
