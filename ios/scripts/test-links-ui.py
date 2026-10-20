#!/usr/bin/env python3
"""Cold/warm OS-link UI tests on an explicitly selected simulator; fixture tokens only."""
import argparse
from pathlib import Path
import subprocess
import sys

p=argparse.ArgumentParser()
p.add_argument('--device', required=True)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
command=['xcodebuild','-project','Tongyou.xcodeproj','-scheme','Tongyou',
         '-destination','id='+a.device,'-derivedDataPath','/tmp/tongyou-ios-links-sim',
         '-parallel-testing-enabled','NO','CODE_SIGNING_ALLOWED=NO','test']
run=subprocess.Popen(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
assert run.stdout is not None
for line in run.stdout:
    print(line,end='',flush=True)
    if line.strip()=='TONGYOU_READY_FOR_URL':
        subprocess.run(['xcrun','simctl','openurl',a.device,'tongyou://ledger/join?token='+'a'*43],check=True,timeout=30)
sys.exit(run.wait())
