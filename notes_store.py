"""Persistence for notes attached to project documents."""
from contextlib import closing
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


class NotesStore:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL, quote TEXT NOT NULL, created TEXT NOT NULL)')
        return db

    def list(self, kind, path):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT id, body, quote, created FROM notes WHERE kind=? AND path=? ORDER BY created DESC', (kind, path)).fetchall()
        return [dict(zip(('id', 'body', 'quote', 'created'), row)) for row in rows]

    def create(self, kind, path, body, quote):
        identifier, created = uuid4().hex, datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db, db:
            db.execute('INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)', (identifier, kind, path, body, quote, created))
        return {'id': identifier, 'body': body, 'quote': quote, 'created': created}

    def update(self, kind, path, identifier, body):
        with closing(self._connect()) as db, db:
            result = db.execute('UPDATE notes SET body=? WHERE id=? AND kind=? AND path=?', (body, identifier, kind, path))
            return result.rowcount == 1

    def delete(self, kind, path, identifier):
        with closing(self._connect()) as db, db:
            result = db.execute('DELETE FROM notes WHERE id=? AND kind=? AND path=?', (identifier, kind, path))
            return result.rowcount == 1
