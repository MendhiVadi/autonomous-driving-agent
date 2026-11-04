"""Exercise the same Windows PowerShell used by the double-click launcher."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows launcher")
class StartupTests(unittest.TestCase):
    def run_check(self, body):
        helper = Path(__file__).resolve().parents[1] / "scripts/carla_startup_state.ps1"
        script = "$ErrorActionPreference='Stop'; . '" + str(helper).replace("'", "''") + "'; " + body
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failed_native_probe_is_retryable_with_stop_error_preference(self):
        # powershell.exe rejects the Python command-line flags on stderr.
        # This deterministically tests the native-error path without using a port.
        self.run_check(
            "$ready=Test-CarlaRpcReady -PythonPath 'powershell.exe'; "
            "if ($ready -ne $false) { throw 'Failed probe was treated as ready' }; "
            "if ($ErrorActionPreference -ne 'Stop') { throw 'Preference leaked' }")

    def test_successful_probe_output_cannot_pollute_boolean_result(self):
        self.run_check(
            "function fakePython { Write-Output 'diagnostic'; $global:LASTEXITCODE=0 }; "
            "$ready=Test-CarlaRpcReady -PythonPath 'fakePython'; "
            "if ($ready -isnot [bool] -or -not $ready) { throw 'Expected one true boolean' }")

    def test_failed_probe_output_cannot_be_mistaken_for_readiness(self):
        self.run_check(
            "function fakePython { Write-Output 'diagnostic'; $global:LASTEXITCODE=1 }; "
            "$ready=Test-CarlaRpcReady -PythonPath 'fakePython'; "
            "if ($ready -isnot [bool] -or $ready) { throw 'Expected one false boolean' }")

    def test_native_stderr_does_not_abort_a_successful_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "drive.log"
            python = sys.executable.replace("'", "''")
            target = str(log).replace("'", "''")
            self.run_check(
                f"Invoke-CarlaLoggedClient -PythonPath '{python}' "
                "-Arguments @('-I','-B','-c','import sys;sys.stderr.write(chr(119)+chr(10));print(123)') "
                f"-LogPath '{target}'; "
                "if ($ErrorActionPreference -ne 'Stop') { throw 'Preference leaked' }")
            self.assertIn("123", log.read_text(encoding="utf-16"))

    def test_nonzero_client_exit_is_still_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = sys.executable.replace("'", "''")
            target = str(Path(temporary) / "failure.log").replace("'", "''")
            self.run_check(
                "$failed=$false; try { "
                f"Invoke-CarlaLoggedClient -PythonPath '{python}' "
                "-Arguments @('-I','-B','-c','import sys;sys.exit(7)') "
                f"-LogPath '{target}'"
                " } catch { $failed=$_.Exception.Message -match 'code 7' }; "
                "if (-not $failed) { throw 'Client failure was lost' }")
