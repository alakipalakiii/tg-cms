"""Local-only Windows launcher contracts; no provider credentials or operations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'local-tools' / 'mahoon-local.ps1'


@unittest.skipUnless(os.name == 'nt', 'Windows entry points')
class PortableLaunchers(unittest.TestCase):
    def test_powershell_parses_without_errors(self):
        result = subprocess.run([
            'powershell.exe', '-NoProfile', '-Command',
            '$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:MAHOON_TEST_SCRIPT,[ref]$null,[ref]$e); if($e.Count){exit 1}',
        ], env={**os.environ, 'MAHOON_TEST_SCRIPT': str(SCRIPT)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='mahoon-launcher-') as other:
            result = subprocess.run(
                [os.environ['COMSPEC'], '/d', '/c', 'call', str(ROOT / 'MAHOON-START.cmd')],
                cwd=other, env={**os.environ, 'MAHOON_NONINTERACTIVE': '1'},
                capture_output=True, text=True, encoding='utf8', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(ROOT), result.stdout)

    def test_no_production_mode_is_accepted(self):
        result = subprocess.run([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(SCRIPT), '-Mode', 'Deploy',
        ], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)

    def test_scripts_have_no_old_machine_paths(self):
        for path in [SCRIPT, *ROOT.glob('MAHOON-*.cmd')]:
            text = path.read_text(encoding='utf8')
            for old in ('C:\\Users\\', 'C:/Users/', 'mahoon-finalize', 'm11e-r86b-runner-clean'):
                self.assertNotIn(old, text, str(path))


if __name__ == '__main__':
    unittest.main()
