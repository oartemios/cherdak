"""Safe persistence for optional local settings; it never stores API keys."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from app_config import default_values, validate_settings


class ConfigurationConflict(Exception):
    pass


class ConfigStore:
    def __init__(self, base):
        self.path = Path(base) / 'config.local.json'
        self.lock = threading.Lock()

    def _read(self):
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}, 'missing'
        try:
            values = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Не удалось прочитать локальный файл настроек.') from exc
        validate_settings(values)
        return values, hashlib.sha256(raw).hexdigest()

    def read(self, active_settings):
        with self.lock:
            values, revision = self._read()
            effective = default_values() | values
            return {'values': effective, 'revision': revision,
                    'restart_required': validate_settings(effective) != active_settings}

    def save(self, values, expected_revision):
        if not isinstance(values, dict) or not isinstance(expected_revision, str):
            raise ValueError('Некорректные настройки.')
        validate_settings(values)
        payload = (json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        with self.lock:
            _, revision = self._read()
            if revision != expected_revision:
                raise ConfigurationConflict('Настройки изменились в другом окне. Обновите страницу.')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.settings-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                # Detect external changes before replacing the existing configuration.
                _, current_revision = self._read()
                if current_revision != expected_revision:
                    raise ConfigurationConflict('Настройки изменились в другом окне. Обновите страницу.')
                os.replace(temporary, self.path); temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return hashlib.sha256(payload).hexdigest()
