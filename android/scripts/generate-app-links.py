#!/usr/bin/env python3
import hashlib,json,os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
config=Path(os.environ.get('TONGYOU_ANDROID_SIGNING',str(Path.home()/'.config/17tongyou/android/signing.properties')))
p=dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line)
env=dict(os.environ,TONGYOU_KEY_PASS=p['storePassword'])
cert=subprocess.check_output(['keytool','-exportcert','-keystore',p['storeFile'],'-alias',p['keyAlias'],'-storepass:env','TONGYOU_KEY_PASS'],env=env)
sha=hashlib.sha256(cert).hexdigest().upper();fingerprint=':'.join(sha[i:i+2] for i in range(0,len(sha),2))
statement=[{'relation':['delegate_permission/common.handle_all_urls'],'target':{'namespace':'android_app','package_name':'com.tongyou.travel','sha256_cert_fingerprints':[fingerprint]}}]
target=root/'links/assetlinks.json';target.write_text(json.dumps(statement,indent=2)+'\n')
print('Public App Links statement generated for com.tongyou.travel; no private key exported.')
