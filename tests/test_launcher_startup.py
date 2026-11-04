"""Exercise the actual PowerShell startup checks without launching CARLA."""
from pathlib import Path
import subprocess
import unittest


class LauncherStartupTests(unittest.TestCase):
    def run_check(self, body):
        helper = Path(__file__).resolve().parents[1] / 'scripts/carla_startup_state.ps1'
        quoted = str(helper).replace("'", "''")
        script = "$ErrorActionPreference='Stop'; . '" + quoted + "'; " + body
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_live_owned_handle_does_not_depend_on_process_listing(self):
        self.run_check("$p=[pscustomobject]@{HasExited=$false}; "
                       "if (-not (Test-CarlaStartupAlive $p { throw 'CIM must not be queried' })) { exit 1 }")

    def test_shipping_child_can_outlive_bootstrap(self):
        self.run_check("$p=[pscustomobject]@{HasExited=$true}; "
                       "if (-not (Test-CarlaStartupAlive $p { [pscustomobject]@{Id=123} })) { exit 1 }")

    def test_confirmed_exit_includes_native_error_code(self):
        self.run_check("$p=[pscustomobject]@{HasExited=$true;ExitCode=-1073741515;Id=123}; "
                       "if (Test-CarlaStartupAlive $p {}) { exit 1 }; "
                       "$detail=Get-CarlaStartupExitDetail $p; "
                       "if ($detail -notmatch '0xC0000135') { throw $detail }")
