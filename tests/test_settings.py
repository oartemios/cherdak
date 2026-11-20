import json
from pathlib import Path
import tempfile
import unittest

from app_config import load_settings
from config_store import ConfigStore, ConfigurationConflict


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ConfigStore(self.root)
        self.active = load_settings(self.root / 'config.local.json')

    def test_defaults_and_pending_changes(self):
        before = self.store.read(self.active)
        self.assertFalse(before['restart_required'])
        values = dict(before['values'], port=9876, qwen_timeout=200)
        revision = self.store.save(values, before['revision'])
        after = self.store.read(self.active)
        self.assertEqual(after['revision'], revision)
        self.assertEqual(after['values']['port'], 9876)
        self.assertTrue(after['restart_required'])
        self.assertEqual(load_settings(self.root / 'config.local.json').qwen_timeout, 200)

    def test_stale_editor_cannot_overwrite_newer_settings(self):
        first = self.store.read(self.active)
        self.store.save(dict(first['values'], port=9876), first['revision'])
        file = self.root / 'config.local.json'
        saved = file.read_bytes()
        with self.assertRaises(ConfigurationConflict):
            self.store.save(dict(first['values'], port=9999), first['revision'])
        self.assertEqual(file.read_bytes(), saved)

    def test_invalid_settings_and_secrets_are_not_written(self):
        first = self.store.read(self.active)
        for patch in ({'port': 70000}, {'qwen_timeout': 0}, {'OPENAI_API_KEY': 'not-a-real-key'}, {'books_root': ''}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.store.save(dict(first['values'], **patch), first['revision'])
        self.assertFalse((self.root / 'config.local.json').exists())

    def test_relative_paths_remain_relative_on_disk(self):
        first = self.store.read(self.active)
        self.store.save(dict(first['values'], voices_dir='voices'), first['revision'])
        saved = json.loads((self.root / 'config.local.json').read_text())
        self.assertEqual(saved['voices_dir'], 'voices')
        self.assertEqual(saved['books_root'], '~/Documents/stories/books')


if __name__ == '__main__':
    unittest.main()
