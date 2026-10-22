#!/usr/bin/env python3
"""Run packaged WebView tests on an explicitly selected emulator (no real accounts)."""
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
assert re.search(r'OK \(20 tests\)', result.stdout), 'Instrumentation did not pass all twenty tests'
