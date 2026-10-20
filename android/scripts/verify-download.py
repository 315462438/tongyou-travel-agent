#!/usr/bin/env python3
"""Verify the public, frozen Android beta download without changing server state."""
import hashlib
import argparse
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--release', default='0.1.0-1')
parser.add_argument('--latest', action='store_true', help='Also require the public update feed to point at this APK')
args = parser.parse_args()
release = args.release
assert '/' not in release and '..' not in release
manifest = json.loads((root / 'android/releases' / release / 'release.json').read_text())
url = f'https://17tongyou.com/downloads/android/{release}/' + manifest['apk']
with urllib.request.urlopen(url, timeout=45) as response:
    assert response.status == 200
    assert response.geturl() == url
    assert response.headers.get_content_type() in (
        'application/octet-stream', 'application/vnd.android.package-archive')
    data = response.read()
assert len(data) == manifest['bytes']
assert hashlib.sha256(data).hexdigest() == manifest['sha256']
request = urllib.request.Request(url, headers={'Range': 'bytes=0-3'})
with urllib.request.urlopen(request, timeout=20) as response:
    assert response.status == 206
    assert response.read() == data[:4] == b'PK\x03\x04'
with urllib.request.urlopen('https://17tongyou.com/travel/', timeout=20) as response:
    assert response.status == 200
    assert response.headers.get_content_type() == 'text/html'
if args.latest:
    request=urllib.request.Request('https://17tongyou.com/downloads/android/latest.json',headers={'Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=20) as response:
        assert response.status==200
        latest=json.loads(response.read(16385))
    assert latest['schema_version']==1 and latest['enabled'] is True
    assert latest['application_id']==manifest['application_id'] and latest['platform']=='Android'
    assert latest['version_code']==manifest['version_code'] and latest['version']==manifest['version']
    assert latest['url']==url and latest['sha256']==manifest['sha256'] and latest['bytes']==manifest['bytes']
print(json.dumps({'url': url, 'bytes': len(data), 'sha256': manifest['sha256'],
                  'https_download': 'passed', 'range': 'passed',
                  'web_entry': 'passed', 'latest_feed': 'passed' if args.latest else 'not checked'}, indent=2))
