"""Release packaging tests. Fake ELF headers do not prove executable compatibility."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/release.py'
spec = importlib.util.spec_from_file_location('native_release', MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'native').mkdir()
        (self.root / 'VERSION').write_text('0.1.0\n', encoding='utf-8')
        (self.root / 'native/Cargo.toml').write_text('[package]\nname="test"\nversion="0.1.0"\n', encoding='utf-8')
        (self.root / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n## 0.1.0\n\n### New Features\n\n- Нативный kit без Python.\n', encoding='utf-8')
        header = bytearray(64)
        header[:4] = b'\x7fELF'
        header[4:6] = bytes((2, 1))
        header[7] = 9
        header[18:20] = b'\x3e\x00'
        self.binary = self.root / 'compiled-native'
        self.binary.write_bytes(header)
        self.dist = self.root / 'dist'

    def build(self):
        return release.build(self.root, self.dist, self.binary)

    def test_exact_native_bundle(self):
        (self.root / 'config.json').write_text('private', encoding='utf-8')
        (self.root / 'guest-key').write_text('private', encoding='utf-8')
        self.build()
        self.assertEqual({item.name for item in self.dist.iterdir()}, release.FILES)
        release.verify(self.root, self.dist)
        self.assertEqual((self.dist / release.ASSET).read_bytes(), self.binary.read_bytes())
        self.assertFalse(any(name.endswith('.py') or name.endswith('.tar.gz') for name in release.FILES))

    def test_reject_linux_and_wrong_architecture(self):
        header = bytearray(self.binary.read_bytes())
        for offset, invalid in ((7, 0), (7, 3), (4, 1), (5, 2), (18, 3)):
            bad = bytearray(header)
            bad[offset] = invalid
            self.binary.write_bytes(bad)
            with self.assertRaises(ValueError):
                self.build()

    def test_reject_version_and_notes_mismatch(self):
        (self.root / 'VERSION').write_text('0.2.0\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            release.check(self.root)
        (self.root / 'VERSION').write_text('0.1.0\n', encoding='utf-8')
        (self.root / 'CHANGELOG.md').write_text('## 0.1.0\n- English only\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            release.check(self.root)

    def test_reject_tampering_and_extra_files(self):
        self.build()
        (self.dist / 'web.json').write_text('private', encoding='utf-8')
        with self.assertRaises(ValueError):
            release.verify(self.root, self.dist)
        with self.assertRaises(ValueError):
            self.build()
        (self.dist / 'web.json').unlink()
        checksum = self.dist / (release.ASSET + '.sha256')
        checksum.write_bytes(checksum.read_bytes().replace(b'  helios', b' *helios'))
        with self.assertRaises(ValueError):
            release.verify(self.root, self.dist)
        self.build()
        (self.dist / 'VERSION').write_text('0.9.0\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            release.verify(self.root, self.dist)
        self.build()
        (self.dist / 'release-notes.md').write_text('Другие изменения\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            release.verify(self.root, self.dist)

    def test_reject_links(self):
        link = self.root / 'binary-link'
        try:
            link.symlink_to(self.binary)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Ссылки недоступны: ' + str(error))
        with self.assertRaises(ValueError):
            release.build(self.root, self.dist, link)
        self.build()
        checksum = self.dist / (release.ASSET + '.sha256')
        checksum.unlink()
        checksum.symlink_to(self.binary)
        with self.assertRaises(ValueError):
            release.verify(self.root, self.dist)


if __name__ == '__main__':
    unittest.main()
