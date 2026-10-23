"""Transfer-integrity regressions; all fixtures use temporary dummy files."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "client_bundle_verifier", Path(__file__).resolve().parents[1] / "verify_bundle.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class BundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = {}
        for name in sorted(verifier.REQUIRED_FILES):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"dummy transfer fixture")
            self.manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.write_manifest(self.manifest)

    def write_manifest(self, value):
        (self.root / "MANIFEST.json").write_text(json.dumps(value), encoding="utf-8")

    def test_complete_package_passes(self):
        self.assertEqual(verifier.verify(self.root), len(self.manifest))

    def test_empty_and_non_object_manifests_fail(self):
        for value in ({}, [], None, "manifest", 5):
            with self.subTest(value=value):
                self.write_manifest(value)
                with self.assertRaisesRegex(ValueError, "missing required"):
                    verifier.verify(self.root)

    def test_required_source_and_pairing_cannot_be_omitted(self):
        for name in ("diagnose.py", "credentials/token.txt", "credentials/server-cert.pem",
                     "credentials/pairing.json", "src/rl_client/client.py"):
            with self.subTest(name=name):
                manifest = dict(self.manifest)
                del manifest[name]
                self.write_manifest(manifest)
                with self.assertRaisesRegex(ValueError, "missing required"):
                    verifier.verify(self.root)

    def test_missing_file_fails(self):
        (self.root / "diagnose.py").unlink()
        with self.assertRaisesRegex(ValueError, "missing or outside"):
            verifier.verify(self.root)

    def test_changed_file_fails(self):
        (self.root / "diagnose.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verifier.verify(self.root)

    def test_malformed_checksums_fail(self):
        for digest in (None, [], 0, "", "0" * 63, "g" * 64):
            with self.subTest(digest=digest):
                self.write_manifest(dict(self.manifest, **{"diagnose.py": digest}))
                with self.assertRaisesRegex(ValueError, "invalid SHA-256"):
                    verifier.verify(self.root)

    def test_noncanonical_and_escaping_paths_fail(self):
        for name in ("../outside.py", "/outside.py", "C:/outside.py", "package\\outside.py",
                     "./diagnose.py", "package//outside.py", ""):
            with self.subTest(name=name):
                self.write_manifest(dict(self.manifest, **{name: "0" * 64}))
                with self.assertRaisesRegex(ValueError, "invalid package path"):
                    verifier.verify(self.root)

    def test_unlisted_source_or_pairing_fails(self):
        for name in ("extra.py", "extra.CMD", "credentials/extra.pem", "credentials/logs/extra.pem"):
            with self.subTest(name=name):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"unlisted")
                try:
                    with self.assertRaisesRegex(ValueError, "not listed in manifest"):
                        verifier.verify(self.root)
                finally:
                    target.unlink()

    def test_private_server_key_fails_even_if_manifested(self):
        name = "credentials/server-key.pem"
        target = self.root / name
        target.write_bytes(b"dummy key")
        with self.assertRaisesRegex(ValueError, "private key"):
            verifier.verify(self.root)
        self.write_manifest(dict(self.manifest, **{
            name: hashlib.sha256(target.read_bytes()).hexdigest()}))
        with self.assertRaisesRegex(ValueError, "private key"):
            verifier.verify(self.root)

    def test_private_key_inside_generated_named_credentials_folder_fails(self):
        target = self.root / "credentials/.venv/server-key.pem"
        target.parent.mkdir()
        target.write_bytes(b"dummy key")
        with self.assertRaisesRegex(ValueError, "private key"):
            verifier.verify(self.root)

    def test_generated_runtime_files_do_not_invalidate_package(self):
        for folder in ("__pycache__", ".venv", "runs", "checkpoints", "logs"):
            target = self.root / folder / "generated.json"
            target.parent.mkdir()
            target.write_text("{}", encoding="utf-8")
        self.assertEqual(verifier.verify(self.root), len(self.manifest))
