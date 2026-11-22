import hashlib
import base64
import io
import json
import shutil
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

import notes_store
import config_store
import server
import speech_jobs
import speech_service


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0' * 1600)
    return output.getvalue()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(server.BASE / 'web', self.root / 'web')
        (self.root / 'book').mkdir()
        (self.root / 'book/chapter.md').write_text('Тестовая глава.', encoding='utf-8')
        patches = [
            patch.object(server, 'ROOTS', {'books': self.root}),
            patch.object(server, 'BASE', self.root),
            patch.object(server, '__file__', str(self.root / 'server.py')),
            patch.object(speech_jobs, 'BASE', self.root),
            patch.object(speech_jobs, 'ROOTS', {'books': self.root}),
            patch.object(speech_jobs, 'JOB_STORAGE', self.root / 'jobs'),
            patch.object(speech_jobs, 'JOBS', {}),
            patch.object(server, 'NOTES', notes_store.NotesStore(self.root / 'notes.sqlite3')),
            patch.object(server, 'CONFIG', config_store.ConfigStore(self.root)),
            patch.object(speech_service, 'generate_piper', return_value=wav_bytes()),
        ]
        # Share one temporary job dictionary between the HTTP and job modules.
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        server_jobs = patch.object(server, 'JOBS', speech_jobs.JOBS)
        server_jobs.start()
        self.addCleanup(server_jobs.stop)
        try:
            self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        except PermissionError:
            self.skipTest('Sandbox does not allow local sockets')
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def get(self, path):
        with urlopen(self.url + path, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def post(self, path, data):
        request = Request(self.url + path, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def test_png_viewing_respects_project_roots_and_file_type(self):
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        (self.root / 'book/picture.PNG').write_bytes(image)
        code, _, body = self.get('/api/browse?kind=books&path=book%2Fpicture.PNG')
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)['image'])
        code, content_type, body = self.get('/api/image?kind=books&path=book%2Fpicture.PNG')
        self.assertEqual((code, content_type), (200, 'image/png'))
        self.assertEqual(body, image)
        (self.root / 'book/fake.png').write_text('not a PNG', encoding='utf-8')
        with self.assertRaises(HTTPError) as invalid:
            self.get('/api/image?kind=books&path=book%2Ffake.png')
        self.assertEqual(invalid.exception.code, 415)
        with self.assertRaises(HTTPError) as wrong_type:
            self.get('/api/image?kind=books&path=book%2Fchapter.md')
        self.assertEqual(wrong_type.exception.code, 404)
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / 'external.png'; external.write_bytes(image)
            (self.root / 'book/outside.png').symlink_to(external)
            with self.assertRaises(HTTPError) as escaped:
                self.get('/api/image?kind=books&path=book%2Foutside.png')
            self.assertEqual(escaped.exception.code, 404)

    def test_emotional_reference_is_separate_and_discoverable(self):
        output = io.BytesIO()
        with wave.open(output, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b'\0' * 48000)
        encoded = base64.b64encode(output.getvalue()).decode()
        common = {'audio': encoded, 'transcript': 'Тестовая запись', 'name': 'Мой голос'}
        _, _, body = self.post('/api/voice-sample', common)
        neutral = json.loads(body)
        original = self.root / '.voice-profiles' / neutral['id'] / 'reference.wav'
        before = original.read_bytes()
        _, _, body = self.post('/api/voice-sample', dict(common, name='Радостный образец', emotion='joy'))
        expressive = json.loads(body)
        self.assertNotEqual(neutral['id'], expressive['id'])
        self.assertEqual(expressive['emotion'], 'joy')
        self.assertEqual(original.read_bytes(), before)
        _, _, body = self.get('/api/voices')
        voices = {item['id']: item for item in json.loads(body)}
        self.assertEqual(voices[neutral['id']]['emotion'], 'neutral')
        self.assertEqual(voices[expressive['id']]['emotion'], 'joy')
        _, _, body = self.post('/api/voice-sample', dict(common, name='Шёпот', emotion='whisper', parent_id=neutral['id'], transcript='Тихая запись'))
        whisper = json.loads(body)
        self.assertEqual(whisper['parent_id'], neutral['id'])
        self.assertEqual((self.root / '.voice-profiles' / whisper['id'] / 'transcript.txt').read_text(encoding='utf-8'), 'Тихая запись')
        self.assertEqual(original.read_bytes(), before)
        _, _, body = self.get('/api/voices')
        self.assertEqual(next(item for item in json.loads(body) if item['id'] == whisper['id'])['parent_id'], neutral['id'])
        with self.assertRaises(HTTPError):
            self.post('/api/voice-sample', dict(common, parent_id=whisper['id'], emotion='whisper'))
        with self.assertRaises(HTTPError) as invalid:
            self.post('/api/voice-sample', dict(common, emotion='unknown'))
        self.assertEqual(invalid.exception.code, 400)

    def test_web_assets_and_document_notes_and_audio(self):
        code, content_type, html = self.get('/')
        self.assertEqual((code, content_type), (200, 'text/html'))
        self.assertIn(b'/assets/app.js', html)
        for asset in ('app.js', 'sidebar.js', 'markdown.js', 'vendor/markdown-it.mjs', 'notes.js', 'speech.js', 'settings.js', 'styles.css'):
            code, content_type, body = self.get('/assets/' + asset)
            self.assertEqual(code, 200)
            self.assertTrue(body)
        code, content_type, page = self.get('/settings')
        self.assertEqual((code, content_type), (200, 'text/html'))
        self.assertIn(b'/assets/settings.js', page)
        _, _, body = self.get('/api/settings')
        config = json.loads(body)
        changed = dict(config['values'], port=9876)
        _, _, body = self.post('/api/settings', {'values': changed, 'revision': config['revision']})
        self.assertTrue(json.loads(body)['restart_required'])
        with self.assertRaises(HTTPError) as conflict:
            self.post('/api/settings', {'values': changed, 'revision': config['revision']})
        self.assertEqual(conflict.exception.code, 409)
        code, _, body = self.get('/api/browse?kind=books&path=book%2Fchapter.md')
        document = json.loads(body)
        self.assertEqual(document['content'], 'Тестовая глава.')
        _, _, body = self.post('/api/notes', {'action': 'create', 'kind': 'books', 'path': 'book/chapter.md', 'body': 'Заметка', 'quote': ''})
        self.assertTrue(json.loads(body)['id'])
        _, _, body = self.get('/api/notes?kind=books&path=book%2Fchapter.md')
        self.assertEqual(json.loads(body)[0]['body'], 'Заметка')
        text = document['content']
        request = {'kind': 'books', 'path': 'book/chapter.md', 'text': text, 'engine': 'local', 'local_voice': 'ruslan', 'speed': 1.0, 'sentences': 1, 'source_hash': document['source_hash']}
        _, _, body = self.post('/api/speech-job', request)
        identifier = json.loads(body)['id']
        for _ in range(100):
            _, _, body = self.get('/api/speech-job?id=' + identifier)
            state = json.loads(body)
            if state['state'] in ('complete', 'error'):
                break
            time.sleep(.02)
        self.assertEqual(state['state'], 'complete', state)
        code, content_type, audio = self.get('/api/speech-part?id=' + identifier + '&index=0')
        self.assertEqual((code, content_type), (200, 'audio/wav'))
        self.assertEqual(audio, wav_bytes())
        code, content_type, timeline = self.get('/api/speech-timeline?id=' + identifier)
        self.assertEqual((code, content_type), (200, 'application/json'))
        self.assertEqual(json.loads(timeline), {'durations': [0.1]})
        file = self.root / 'book/chapter.md'
        file.write_text('Внешняя правка.', encoding='utf-8')
        with self.assertRaises(HTTPError) as error:
            self.post('/api/save', {'kind': 'books', 'path': 'book/chapter.md', 'content': 'Новая версия', 'source_hash': document['source_hash']})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(file.read_text(encoding='utf-8'), 'Внешняя правка.')


    def test_sentence_count_change_keeps_prepared_prefix_and_replans_remainder(self):
        text = 'Заголовок\nПервое. Второе. Третье. Четвёртое.\nФинал\nПоследнее.'
        request = {'kind': 'books', 'path': 'book/chapter.md', 'text': text,
                   'engine': 'synthetic', 'sentences': 2, 'headings': ['Заголовок', 'Финал']}
        with patch.object(server.EXECUTOR, 'submit') as submit:
            _, _, body = self.post('/api/speech-job', request)
            identifier = json.loads(body)['id']
            job = speech_jobs.JOBS[identifier]
            self.assertEqual(job['chunks'][:2], ['Заголовок', 'Первое. Второе.'])
            folder = speech_jobs.JOB_STORAGE / identifier
            reference = folder / 'synthetic-reference.wav'
            reference.write_bytes(wav_bytes())
            for index in range(2):
                file = folder / f'{index}.audio'
                file.write_bytes(wav_bytes())
                job['files'].append((file, 'audio/wav'))
            job['repairs'] = {'1': {'state': 'complete', 'pronunciation': 'Исправленный текст.'}}
            job['state'] = 'paused'
            speech_jobs.save_job(identifier, job)

            _, _, body = self.post('/api/speech-job', dict(request, sentences=1))
            self.assertEqual(json.loads(body), {'id': identifier, 'total': 6, 'heading_pauses': [0, 4]})
            self.assertEqual(job['chunks'], ['Заголовок', 'Первое. Второе.', 'Третье.',
                                             'Четвёртое.', 'Финал', 'Последнее.'])
            self.assertEqual(len(job['files']), 2)
            self.assertEqual(job['repairs']['1']['pronunciation'], 'Исправленный текст.')
            self.assertEqual(reference.read_bytes(), wav_bytes())
            self.assertEqual(self.get('/api/speech-part?id=' + identifier + '&index=1')[2], wav_bytes())
            persisted = json.loads((folder / 'job.json').read_text())
            self.assertEqual(persisted['chunks'], job['chunks'])
            self.assertEqual(persisted['state'], 'queued')
            self.assertEqual(submit.call_count, 2)

            # Another tab changing the split while work is queued cannot start it again.
            _, _, body = self.post('/api/speech-job', dict(request, sentences=3))
            self.assertEqual(json.loads(body)['id'], identifier)
            self.assertEqual(submit.call_count, 2)

            # A different rendered text or a different voice requires a new job.
            for params in ({'text': text.replace('Последнее.', 'Новое.')}, {'synthetic_age': 45}):
                _, _, body = self.post('/api/speech-job', request | params)
                self.assertNotEqual(json.loads(body)['id'], identifier)

            for index in range(2, len(job['chunks'])):
                file = folder / f'{index}.audio'
                file.write_bytes(wav_bytes())
                job['files'].append((file, 'audio/wav'))
            job['state'] = 'complete'
            submissions = submit.call_count
            _, _, body = self.post('/api/speech-job', dict(request, sentences=4))
            self.assertEqual(json.loads(body)['id'], identifier)
            self.assertEqual(submit.call_count, submissions)

    def test_save_synthetic_reference_and_use_on_another_page(self):
        ident = 'a' * 32
        folder = self.root / 'jobs' / ident
        folder.mkdir(parents=True)
        reference = wav_bytes()
        (folder / 'synthetic-reference.wav').write_bytes(reference)
        first = folder / '0.audio'
        first.write_bytes(b'repaired output')
        speech_jobs.JOBS[ident] = {'settings': {'engine': 'synthetic', '_synthetic_pipeline': 2, 'kind': 'books', 'path': 'book/chapter.md'}, 'chunks': ['Оригинальный текст эталона.'], 'files': [(first, 'audio/wav')], 'state': 'complete', 'cancelled': False, 'fingerprint': 'test', 'error': ''}
        _, _, body = self.post('/api/synthetic-voice-save', {'id': ident, 'name': 'Новый голос', 'kind': 'books', 'path': 'book/chapter.md'})
        profile = json.loads(body)['id']
        saved = self.root / '.voice-profiles' / profile
        self.assertEqual((saved / 'reference.wav').read_bytes(), reference)
        self.assertEqual((saved / 'transcript.txt').read_text(), 'Оригинальный текст эталона.')
        _, _, body = self.get('/api/voices')
        self.assertTrue(any(x['id'] == profile and x['origin'] == 'synthetic' for x in json.loads(body)))
        other = self.root / 'book/other.md'
        other.write_text('Другая страница.', encoding='utf-8')
        with patch.object(speech_service, 'generate_qwen', return_value=wav_bytes()) as generate:
            code, content_type, _ = self.post('/api/speech-preview', {'engine': 'clone', 'profile': profile, 'kind': 'books', 'path': 'book/other.md', 'text': 'Другая страница.'})
            self.assertEqual((code, content_type), (200, 'audio/wav'))
            self.assertEqual(generate.call_args.args[2], saved / 'reference.wav')
        self.post('/api/speech-reset', {'kind': 'books', 'path': 'book/chapter.md'})
        self.assertEqual((saved / 'reference.wav').read_bytes(), reference)



if __name__ == '__main__':
    unittest.main()
