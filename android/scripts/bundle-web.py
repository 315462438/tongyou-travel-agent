#!/usr/bin/env python3
"""Build an APK-owned web snapshot without touching frontend/dist or the server."""
import hashlib
import json
from pathlib import Path
import subprocess

android = Path(__file__).resolve().parents[1]
root = android.parent
output = android / 'app/build/generated/webAssets'
web = output / 'web'
subprocess.run(['npx', 'tsc', '-b'], cwd=root / 'frontend', check=True)
subprocess.run(['npx', 'vite', 'build', '--target', 'chrome111', '--outDir', str(web), '--emptyOutDir'], cwd=root / 'frontend', check=True)
# Instrumentation tests use a separate debug-only fixture; production contains only this snapshot.
files = {str(p.relative_to(web)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(web.rglob('*')) if p.is_file()}
(output / 'web-manifest.json').write_text(json.dumps(files, ensure_ascii=False, indent=2))
print(f'Android web snapshot: {len(files)} files, no website deployment')
