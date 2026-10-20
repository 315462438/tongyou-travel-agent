#!/usr/bin/env python3
"""Deploy the public domain association only; no app/backend/site deployment or restart."""
import base64,json,subprocess,urllib.request
from pathlib import Path
from dotenv import dotenv_values
root=Path(__file__).resolve().parents[2]
statements=json.loads((root/'android/links/assetlinks.json').read_text())
assert len(statements)==1 and statements[0]['target']['package_name']=='com.tongyou.travel'
payload=base64.b64encode(json.dumps(statements).encode()).decode()
remote='''import base64,json,os,time
from pathlib import Path
incoming=json.loads(base64.b64decode('''+repr(payload)+'''))
p=Path('/var/www/html/.well-known/assetlinks.json')
p.parent.mkdir(parents=True,exist_ok=True)
previous=json.loads(p.read_text()) if p.exists() else []
assert isinstance(previous,list)
merged=[s for s in previous if s.get('target',{}).get('package_name')!='com.tongyou.travel']+incoming
if p.exists():
 backup=p.with_name('assetlinks.json.backup-'+time.strftime('%Y%m%d%H%M%S'))
 backup.write_bytes(p.read_bytes())
tmp=p.with_name('assetlinks.json.tmp')
tmp.write_text(json.dumps(merged,indent=2)+'\\n');tmp.chmod(0o644);os.replace(tmp,p)
print(json.dumps({'association_deployed':True,'statements':len(merged),'backend_restarted':False,'web_ui_deployed':False}))
'''
host=dotenv_values(root/'backend/.env')['DEPLOY_HOST']
subprocess.run(['ssh','-o','ConnectTimeout=12',host,'sudo python3 -'],input=remote,text=True,check=True,timeout=30)
url='https://17tongyou.com/.well-known/assetlinks.json'
with urllib.request.urlopen(url,timeout=20) as response:
 assert response.status==200 and response.geturl()==url
 assert response.headers.get_content_type()=='application/json'
 result=json.load(response)
 assert statements[0] in result
print('HTTPS association verified: 200, JSON, no redirect, release certificate matches.')
