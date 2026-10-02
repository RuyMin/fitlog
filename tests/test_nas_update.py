import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash') and shutil.which('flock'), 'NAS updater requires Linux bash/flock')
class NasUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        source=Path(__file__).resolve().parents[1]/'deploy/ugreen/update.sh'
        shutil.copyfile(source,self.root/'update.sh')
        (self.root/'.env').write_text('GOOGLE_SPREADSHEET_ID=test\n')
        (self.root/'compose.yml').write_text('services: {}\n')
        fake=self.root/'docker'
        fake.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
a=sys.argv[1:];mode=os.environ['TEST_MODE']
with open(os.environ['TEST_TRACE'],'a') as f:f.write(' '.join(a)+'\\n')
if a[0]=='compose':
 action=a[7]
 if action=='config' and '--images' in a:print('ghcr.io/ruymin/fitlog:latest')
 elif action=='ps':print('container123')
 elif action=='pull' and mode=='pull_failure':sys.exit(1)
 elif action=='exec':
  sys.stdin.read()
  if mode=='backup_failure':sys.exit(1)
 elif action=='up' and mode=='health_failure':sys.exit(1)
elif a[0]=='inspect':
 print(('unhealthy' if mode=='unhealthy' else 'healthy') if 'Health' in a[2] else 'sha256:old')
elif a[:2]==['image','inspect']:print('sha256:old' if mode=='unchanged' else 'sha256:new')
''')
        fake.chmod(0o755)
    def run_update(self,mode):
        env={**os.environ,'PATH':str(self.root)+os.pathsep+os.environ['PATH'],'TEST_MODE':mode,'TEST_TRACE':str(self.root/'trace')}
        result=subprocess.run(['bash',str(self.root/'update.sh')],env=env,capture_output=True,text=True,timeout=10)
        trace=(self.root/'trace').read_text() if (self.root/'trace').exists() else ''
        return result,trace
    def test_unchanged_does_not_backup_or_recreate(self):
        r,t=self.run_update('unchanged');self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn(' exec ',t);self.assertNotIn(' up ',t)
    def test_changed_backs_up_before_up(self):
        r,t=self.run_update('changed');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertLess(t.index(' exec '),t.index(' up '))
        self.assertIn('--wait --wait-timeout 120',t)
        self.assertFalse((self.root/'.update-failed').exists())
    def test_pull_and_backup_failures_leave_container(self):
        for mode in ['pull_failure','backup_failure','unhealthy']:
            with self.subTest(mode=mode):
                (self.root/'trace').write_text('')
                r,t=self.run_update(mode);self.assertNotEqual(r.returncode,0)
                self.assertNotIn(' up ',t)
    def test_failed_health_latches_and_blocks_retry(self):
        r,t=self.run_update('health_failure');self.assertNotEqual(r.returncode,0)
        self.assertTrue((self.root/'.update-failed').exists())
        (self.root/'trace').write_text('')
        r,t=self.run_update('changed');self.assertNotEqual(r.returncode,0);self.assertEqual(t,'')
    def test_missing_env_prevents_docker_calls(self):
        (self.root/'.env').unlink()
        r,t=self.run_update('changed');self.assertNotEqual(r.returncode,0);self.assertEqual(t,'')
