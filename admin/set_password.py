#!/usr/bin/env python3
"""Run interactively inside the admin container; no public setup endpoint."""
import getpass
import hashlib
import json
import secrets
import server

password=getpass.getpass('设置后台密码（至少 12 位，不会显示）：')
if len(password)<12 or len(password)>256: raise SystemExit('密码长度必须是 12–256 位')
if getpass.getpass('再次输入密码：')!=password: raise SystemExit('两次密码不一致，未修改')
salt=secrets.token_bytes(16)
body={'username':'admin','salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()}
with server.LOCK,server.connect() as c:
    server.atomic_write(server.DATA/'auth.json',json.dumps(body).encode(),0o600)
    c.execute('DELETE FROM sessions')
print('CJW_NAV_ADMIN_READY — 账号：admin；已退出所有旧会话。')
