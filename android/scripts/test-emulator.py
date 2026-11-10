#!/usr/bin/env python3
"""Optional device regression: native + fallback tests, with local fixtures only."""
import argparse
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
args = parser.parse_args()
if not args.serial.startswith('emulator-'):
    parser.error('This fixture runner is restricted to emulators.')
root = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get('ANDROID_HOME', str(Path.home() / 'Library/Android/sdk')))
adb = [str(sdk / 'platform-tools/adb'), '-s', args.serial]
subprocess.run([os.environ.get('GRADLE', str(root / 'gradlew')), ':app:assembleDebug', ':app:assembleDebugAndroidTest'], cwd=root, check=True)
for apk in ['debug/app-debug.apk', 'androidTest/debug/app-debug-androidTest.apk']:
    subprocess.run(adb + ['install', '-r', str(root / 'app/build/outputs/apk' / apk)], check=True)
result = subprocess.run(adb + ['shell', 'am', 'instrument', '-w', 'com.tongyou.travel.debug.test/androidx.test.runner.AndroidJUnitRunner'], capture_output=True, text=True, check=True)
print(result.stdout)
match = re.search(r'OK \((\d+) tests\)', result.stdout)
assert match and int(match[1]) >= 10 and 'FAILURES' not in result.stdout, 'Instrumentation did not pass the native suites'
