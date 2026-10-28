import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
spec=importlib.util.spec_from_file_location('client_security',Path(__file__).parents[1]/'check_client_security.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ClientSecurityTests(unittest.TestCase):
    def test_apk_server_key_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'app.apk'
            with zipfile.ZipFile(p,'w') as z:z.writestr('classes.dex',b'NEIS_API_KEY')
            with patch('sys.argv',['check','--apk',str(p),'--pages',str(Path(folder)/'pages')]):
                with self.assertRaises(SystemExit):module.main()
    def test_actual_key_in_pages_is_rejected_without_echo(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NEIS_API_KEY':'one-private-test-key'}):
            (Path(folder)/'schools.json').write_text('one-private-test-key')
            with patch('sys.argv',['check','--pages',folder]):
                with self.assertRaises(SystemExit) as e:module.main()
                self.assertNotIn('one-private-test-key',str(e.exception))
    def test_clean_outputs_pass(self):
        with tempfile.TemporaryDirectory() as folder,patch('sys.argv',['check','--pages',folder]),patch('sys.stdout',new_callable=io.StringIO) as output:
            (Path(folder)/'index.html').write_text('学校')
            module.main();self.assertIn('passed',output.getvalue())
