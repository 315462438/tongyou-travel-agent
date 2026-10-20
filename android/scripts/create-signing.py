#!/usr/bin/env python3
"""One-time private release key. Never overwrite a key used by installed APKs."""
import os
from pathlib import Path
import secrets
import subprocess

folder = Path.home() / '.config/17tongyou/android'
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
folder.chmod(0o700)
store = folder / 'release.jks'
config = folder / 'signing.properties'
if store.exists() or config.exists():
    if not (store.exists() and config.exists()):
        raise SystemExit('Incomplete signing files; restore backup instead of generating a replacement.')
    print('Existing signing key retained.')
else:
    password = secrets.token_urlsafe(40)
    env = dict(os.environ, TONGYOU_KEY_PASS=password)
    subprocess.run(['keytool', '-genkeypair', '-keystore', str(store), '-storetype', 'PKCS12',
        '-storepass:env', 'TONGYOU_KEY_PASS', '-keypass:env', 'TONGYOU_KEY_PASS',
        '-alias', 'tongyou-release', '-keyalg', 'RSA', '-keysize', '3072', '-validity', '10000',
        '-dname', 'CN=17Tongyou Android, OU=Mobile, O=17Tongyou, C=CN'], env=env, check=True)
    store.chmod(0o600)
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(f'storeFile={store}\nstorePassword={password}\nkeyAlias=tongyou-release\nkeyPassword={password}\n')
    print('Private signing key created outside the repository. Back up ~/.config/17tongyou/android securely.')
