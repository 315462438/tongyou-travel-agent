import hashlib
import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from update_manifest import make_manifest, REMOTE_PUBLISH

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.apk=b'PK fixture'
        self.release=dict(platform='Android',application_id='com.tongyou.travel',version='0.6.0',version_code=9,min_sdk=26,
                          apk='17tongyou-android-0.6.0-9.apk',bytes=len(self.apk),sha256=hashlib.sha256(self.apk).hexdigest())
    def test_public_contract(self):
        m=make_manifest(self.release,'主题与更新',self.apk)
        self.assertEqual(m['url'],'https://17tongyou.com/downloads/android/0.6.0-9/17tongyou-android-0.6.0-9.apk')
        self.assertEqual(m['min_sdk'],26)
        self.assertTrue(m['enabled'])
        self.assertEqual(set(m),{'schema_version','enabled','platform','application_id','version','version_code','min_sdk','url','bytes','sha256','notes'})
    def test_corrupt_apk_refused(self):
        with self.assertRaises(AssertionError):make_manifest(self.release,'',b'other')
    def test_wrong_package_or_artifact_refused(self):
        for key,value in [('application_id','com.tongyou.travel.debug'),('apk','other.apk'),('bytes',0),('min_sdk',0)]:
            with self.assertRaises(AssertionError):make_manifest({**self.release,key:value},'',self.apk)
    def test_bad_version_refused(self):
        for key,value in [('version','../oops'),('version_code',-1),('version_code',2147483648)]:
            with self.assertRaises(ValueError):make_manifest({**self.release,key:value},'',self.apk)

    def test_atomic_publish_immutable_apk_and_monotonic_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'public'
            script=REMOTE_PUBLISH.replace("'/var/www/html/downloads/android'",repr(str(root)))
            def publish(manifest, data):
                stage=Path(tempfile.mkdtemp(dir=tmp))
                (stage/'latest.json').write_text(json.dumps(manifest))
                (stage/'app.apk').write_bytes(data)
                return subprocess.run([sys.executable,'-c',script,str(stage)],capture_output=True)
            m=make_manifest(self.release,'体验改进',self.apk)
            self.assertEqual(publish(m,self.apk).returncode,0)
            target=root/'0.6.0-9'/self.release['apk']
            self.assertEqual(target.read_bytes(),self.apk)
            self.assertEqual(json.loads((root/'latest.json').read_text()),m)
            self.assertEqual(publish(m,self.apk).returncode,0)  # idempotent retry
            original=(root/'latest.json').read_bytes()
            # Failed upload cannot announce a new version or change the existing APK.
            self.assertNotEqual(publish({**m,'version_code':10},b'broken').returncode,0)
            self.assertNotEqual(publish({**m,'version_code':8},self.apk).returncode,0)
            self.assertNotEqual(publish({**m,'sha256':'b'*64},self.apk).returncode,0)
            self.assertEqual((root/'latest.json').read_bytes(),original)
            self.assertEqual(target.read_bytes(),self.apk)

if __name__=='__main__':unittest.main()
