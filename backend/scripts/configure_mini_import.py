"""Set the mini-program secret locally without echoing it or placing it in shell history."""
import getpass
import os
import re
import secrets
from pathlib import Path
from dotenv import dotenv_values, set_key
path = Path(__file__).resolve().parents[1] / '.env'
value = getpass.getpass('粘贴刚生成的 AppSecret（输入不显示）：').strip()
if not re.fullmatch(r'[0-9a-fA-F]{32}', value):
    raise SystemExit('格式不正确，未保存。')
set_key(path, 'MINI_IMPORT_APP_SECRET', value)
set_key(path, 'MINI_IMPORT_APP_ID', 'wxd8ed1e6543fc69e7')
if not dotenv_values(path).get('MINI_IMPORT_TOKEN_SECRET'):
    set_key(path, 'MINI_IMPORT_TOKEN_SECRET', secrets.token_hex(32))
set_key(path, 'MINI_IMPORT_ENABLED', 'true')
os.chmod(path, 0o600)
print('已保存到本机后端环境配置；密钥未写入源码。')
