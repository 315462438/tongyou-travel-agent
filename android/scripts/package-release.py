#!/usr/bin/env python3
"""Validate and publish only the Android artifact into its versioned local folder."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
config = (root / 'app/build.gradle').read_text()
version = re.search(r"versionName '([^']+)'", config)[1]
code = int(re.search(r'versionCode (\d+)', config)[1])
sdk = Path(os.environ.get('ANDROID_HOME', str(Path.home() / 'Library/Android/sdk')))
apk = root / 'app/build/outputs/apk/release/app-release.apk'
signer = sdk / 'build-tools/35.0.0/apksigner'
verification = subprocess.check_output([str(signer), 'verify', '--verbose', '--print-certs', str(apk)], text=True)
badging = subprocess.check_output([str(sdk / 'build-tools/35.0.0/aapt'), 'dump', 'badging', str(apk)], text=True)
assert "name='com.tongyou.travel'" in badging and f"versionCode='{code}'" in badging
assert 'application-debuggable' not in badging
association = json.loads((root / 'links/assetlinks.json').read_text())[0]
cert_sha = re.search(r'Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]+)', verification)[1].upper()
assert cert_sha == association['target']['sha256_cert_fingerprints'][0].replace(':','')
assert 'android.intent.action.VIEW' in subprocess.check_output([str(sdk / 'build-tools/35.0.0/aapt'), 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
with zipfile.ZipFile(apk) as z:
    assert 'assets/web/index.html' in z.namelist()
    assert 'assets/android-test.html' not in z.namelist()
    manifest = json.loads(z.read('assets/web-manifest.json'))
    for file, sha in manifest.items():
        assert hashlib.sha256(z.read('assets/web/' + file)).hexdigest() == sha, file
folder = root / 'releases' / f'{version}-{code}'
folder.mkdir(parents=True, exist_ok=True)
destination = folder / f'17tongyou-android-{version}-{code}.apk'
shutil.copy2(apk, destination)
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
(folder / 'SHA256SUMS.txt').write_text(f'{digest}  {destination.name}\n')
(folder / 'signature.txt').write_text(verification)
metadata = dict(platform='Android', application_id='com.tongyou.travel', version=version, version_code=code,
    min_sdk=int(re.search(r"sdkVersion:'(\d+)'",badging)[1]),
    built_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), apk=destination.name,
    bytes=destination.stat().st_size, sha256=digest, web_files=len(manifest),
    backend='https://17tongyou.com/travel/api', web_snapshot=manifest,
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
    source_has_uncommitted_changes=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()))
(folder / 'release.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
(folder / '安装说明.txt').write_text('''17同游 Android 好友测试版
1. 将 APK 文件发送到安卓手机，在浏览器或文件管理器打开。
2. 按系统提示允许此次来源安装应用；安装完成后可以关闭该权限。
3. 打开「17同游」，用已有账号登录；新用户需按注册页提示提供邀请码。
4. 使用的是正式服务器数据，请用自己的账号，删除行程/账本会实际生效。
5. 更新时直接安装新版 APK，不要先卸载；同签名更新可保留登录。
6. 需要联网。Android 8+；若提示 WebView 过旧，先更新系统 WebView/浏览器。
7. 华为 HarmonyOS 5+ 兼容方式需另测，本包不是鸿蒙原生应用。
8. 反馈时提供手机型号、系统版本、“我的”底部的 Android 版本及具体操作。

只发送 APK 和本说明给朋友，不要发送签名密钥或私有配置。
''')
print(json.dumps({k:metadata[k] for k in ['version','version_code','bytes','sha256']},ensure_ascii=False,indent=2))
print(destination)
