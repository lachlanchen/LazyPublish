"""WeUI uses a class suffix instead of the HTML disabled attribute."""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for the embedded JavaScript check')
class DisabledButtonTests(unittest.TestCase):
    def test_all_readiness_scripts_recognize_weui_disabled_suffix(self):
        source = Path(__file__).resolve().parents[1] / 'pub_shipinhao.py'
        scripts = [ast.literal_eval(n.value) for n in ast.parse(source.read_text()).body
                   if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                   and isinstance(n.value.value, str) and 'function isDisabled(el)' in n.value.value]
        self.assertEqual(len(scripts), 3)
        for script in scripts:
            with self.subTest(script=script[:50]):
                function = re.search(r'function isDisabled\(el\) \{.*?\n\}', script, re.S).group()
                program = function + '''
const button = (className, disabled=false, attr=null) =>
  ({className, disabled, getAttribute: () => attr});
console.log(JSON.stringify([
  isDisabled(button('weui-desktop-btn weui-desktop-btn_disabled')),
  isDisabled(button('ant-btn ant-btn-disabled')),
  isDisabled(button('disabled')),
  isDisabled(button('weui-desktop-btn weui-desktop-btn_primary')),
  isDisabled(button('weui-desktop-btn', true)),
  isDisabled(button('weui-desktop-btn', false, '')),
  isDisabled(null)
]));
'''
                result = subprocess.run(['node', '-e', program], check=True,
                                        text=True, capture_output=True)
                self.assertEqual(json.loads(result.stdout),
                                 [True, True, True, False, True, True, True])


if __name__ == '__main__':
    unittest.main()
