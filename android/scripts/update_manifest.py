"""Public Android update contract; no signing secrets or source paths are published."""
import hashlib
import re

BASE = 'https://17tongyou.com/downloads/android/'

def make_manifest(release, notes, apk_bytes):
    version, code = release['version'], release['version_code']
    if not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', version):
        raise ValueError('Invalid version')
    if type(code) is not int or not 0 < code <= 2147483647:
        raise ValueError('Invalid version code')
    filename = f'17tongyou-android-{version}-{code}.apk'
    assert release['platform'] == 'Android' and release['application_id'] == 'com.tongyou.travel'
    assert release['apk'] == filename
    assert type(release['min_sdk']) is int and 26 <= release['min_sdk'] <= 100
    assert 0 < len(apk_bytes) <= 200 * 1024 * 1024 and len(apk_bytes) == release['bytes']
    assert hashlib.sha256(apk_bytes).hexdigest() == release['sha256']
    assert isinstance(notes, str) and len(notes) <= 2000
    return dict(schema_version=1, enabled=True, platform='Android', application_id='com.tongyou.travel',
                version=version, version_code=code, min_sdk=release['min_sdk'], url=BASE+f'{version}-{code}/'+filename,
                bytes=release['bytes'], sha256=release['sha256'], notes=notes.strip())

# Executed over SSH with only a generated directory name and validated public manifest.
# APK becomes available before latest.json is atomically replaced. Existing URLs are immutable.
REMOTE_PUBLISH = r'''
import fcntl,hashlib,json,os,pathlib,sys
stage=pathlib.Path(sys.argv[1])
root=pathlib.Path('/var/www/html/downloads/android')
root.mkdir(parents=True,exist_ok=True)
manifest=json.loads((stage/'latest.json').read_text())
with (root/'.publish.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    latest=root/'latest.json'
    if latest.exists():
        previous=json.loads(latest.read_text())
        assert previous['version_code']<=manifest['version_code'], 'Refusing to downgrade update feed'
        if previous['version_code']==manifest['version_code']:
            assert previous['sha256']==manifest['sha256'], 'Version code already published with different APK'
    data=(stage/'app.apk').read_bytes()
    assert len(data)==manifest['bytes'] and hashlib.sha256(data).hexdigest()==manifest['sha256']
    folder=root/(manifest['version']+'-'+str(manifest['version_code']))
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/manifest['url'].rsplit('/',1)[1]
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).hexdigest()==manifest['sha256'], 'Immutable APK mismatch'
    else:
        temporary=target.with_suffix('.apk.tmp')
        temporary.write_bytes(data);temporary.chmod(0o644);os.replace(temporary,target)
    temporary=root/'latest.json.tmp'
    temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    temporary.chmod(0o644);os.replace(temporary,latest)
for file in stage.iterdir(): file.unlink()
stage.rmdir()
print('Android APK and update feed published.')
'''
