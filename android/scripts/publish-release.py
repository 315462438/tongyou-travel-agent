#!/usr/bin/env python3
"""Publish validated APK first, then the atomic public update pointer. Run with backend venv."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid
from dotenv import dotenv_values
from update_manifest import make_manifest, REMOTE_PUBLISH

parser=argparse.ArgumentParser()
parser.add_argument('--release',required=True)
parser.add_argument('--notes-file',type=Path,required=True)
args=parser.parse_args()
assert re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}-\d+',args.release)
root=Path(__file__).resolve().parents[2]
folder=root/'android/releases'/args.release
release=json.loads((folder/'release.json').read_text())
assert args.release == f"{release['version']}-{release['version_code']}"
apk=folder/release['apk']
manifest=make_manifest(release,args.notes_file.read_text(),apk.read_bytes())
(folder/'latest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
host=dotenv_values(root/'backend/.env')['DEPLOY_HOST']
stage='/tmp/tongyou-release-'+uuid.uuid4().hex
subprocess.run(['ssh',host,'mkdir -m 700 '+stage],check=True,capture_output=True)
try:
    subprocess.run(['scp',str(apk),host+':'+stage+'/app.apk'],check=True,capture_output=True)
    subprocess.run(['scp',str(folder/'latest.json'),host+':'+stage+'/latest.json'],check=True,capture_output=True)
    completed=subprocess.run(['ssh',host,'sudo python3 - '+stage],input=REMOTE_PUBLISH,text=True,capture_output=True,check=True)
    print(completed.stdout.strip())
except subprocess.CalledProcessError as error:
    # Paths and manifest are public; never dump the configured connection target.
    print('Publication failed; inspect remote staging directory and update feed before retrying.')
    print(error.stderr.decode() if isinstance(error.stderr,bytes) else error.stderr or '')
    raise SystemExit(1)
