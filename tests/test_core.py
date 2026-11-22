import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app_config
import server
from speech_text import prepare_speech_text, split_document_speech, split_speech


class ConfigTests(unittest.TestCase):
    def test_defaults_preserve_current_locations(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = app_config.load_settings(Path(folder) / 'absent.json')
        self.assertEqual(settings.books_root, Path.home() / 'Documents/stories/books')
        self.assertEqual(settings.games_root, (Path.home() / 'Development/games').resolve())
        self.assertEqual(settings.qwen_tts_model, app_config.BASE / 'models/qwen3-tts-0.6b')
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.piper_python, app_config.BASE / '.piper-env/bin/python')
        self.assertEqual(settings.mlx_python, app_config.BASE / '.clone-env/bin/python')

    def test_overrides_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text(json.dumps({'games_root': '/tmp/example-games', 'port': 9000}))
            settings = app_config.load_settings(config)
            self.assertEqual(settings.games_root, Path('/tmp/example-games'))
            self.assertEqual(settings.port, 9000)
            for value in ({'port': 0}, {'port': True}, {'unexpected': 1}, {'qwen_timeout': -1}):
                config.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    app_config.load_settings(config)

    def test_existing_default_cache_keys_are_preserved(self):
        text = 'Первое предложение.'
        data = {'text': text, 'voice': 'ruslan', 'speed': 1.0, 'version': 1}
        expected = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        actual = server.speech_cache_key({'settings': {'engine': 'local', 'local_voice': 'ruslan', 'speed': 1.0}}, text)
        self.assertEqual(actual, expected)


class SplitTests(unittest.TestCase):
    def test_headings_quotes_and_dotted_numbers(self):
        heading = 'Глава 1.2. Начало'
        text = heading + '\n«Не спеши»\n«Я вернусь!» Кто-то ответил: 3.14 и 1.2.3.'
        chunks, pauses = split_document_speech(text, 'synthetic', 3, {heading})
        self.assertEqual(chunks, [heading, '«Не спеши»\n«Я вернусь!» Кто-то ответил: 3.14 и 1.2.3.'])
        self.assertEqual(pauses, [heading])
        self.assertEqual(prepare_speech_text(chunks[0]), 'Глава 1 точка 2, Начало.')
        self.assertEqual(prepare_speech_text(chunks[1]),
                         '«Не спеши». «Я вернусь!» Кто-то ответил: 3 точка 14 и 1 точка 2 точка 3.')
        self.assertEqual(split_speech('«Я вернусь!» Кто-то ответил.', 'clone', 1),
                         ['«Я вернусь!»', 'Кто-то ответил.'])

    def test_sentence_counts_and_text_preserved(self):
        text = 'Первое предложение. Второе предложение! Третье предложение?'
        self.assertEqual(split_speech(text, 'clone', 1), ['Первое предложение.', 'Второе предложение!', 'Третье предложение?'])
        self.assertEqual(split_speech(text, 'clone', 2), ['Первое предложение. Второе предложение!', 'Третье предложение?'])

    def test_long_sentence_splits_without_losing_words(self):
        text = ' '.join(['слово'] * 100) + '.'
        chunks = split_speech(text, 'clone', 1)
        self.assertTrue(all(len(chunk) <= 180 for chunk in chunks))
        self.assertEqual(' '.join(chunks), text)


class HandlerHarness(server.Handler):
    def __init__(self, body, origin=None):
        self.headers = {'Content-Length': str(len(body))}
        if origin is not None:
            self.headers['Origin'] = origin
        self.path = '/api/save'
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.server = type('Server', (), {'server_port': 8765})()
        self.status = None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self.status = code


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'project').mkdir()
        self.file = self.root / 'project/chapter.md'
        self.file.write_text('Оригинал', encoding='utf-8')
        os.chmod(self.file, 0o640)
        self.roots = patch.object(server, 'ROOTS', {'books': self.root})
        self.roots.start()
        self.addCleanup(self.roots.stop)
        self.addCleanup(self.temp.cleanup)

    def request(self, content, digest, origin=None):
        body = json.dumps({'kind': 'books', 'path': 'project/chapter.md', 'content': content, 'source_hash': digest}).encode()
        handler = HandlerHarness(body, origin)
        handler.do_POST()
        return handler.status

    def test_save_rejects_conflict_and_keeps_original(self):
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.file.write_text('Новое извне', encoding='utf-8')
        self.assertEqual(self.request('Редактор', digest), 409)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'Новое извне')

    def test_save_is_atomic_and_keeps_mode(self):
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.assertEqual(self.request('Изменено', digest), 200)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'Изменено')
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(self.file.parent.glob('.catalog-save-*')), [])

    def test_cross_origin_post_is_rejected(self):
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.assertEqual(self.request('Злоумышленник', digest, 'https://example.com'), 403)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'Оригинал')

class NotesTests(unittest.TestCase):
    def test_notes_are_scoped_and_survive_reopening(self):
        from notes_store import NotesStore
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'notes.sqlite3'
            notes = NotesStore(path)
            item = notes.create('books', 'one.md', 'Заметка', 'Цитата')
            self.assertEqual(NotesStore(path).list('books', 'one.md')[0]['quote'], 'Цитата')
            self.assertFalse(notes.update('books', 'other.md', item['id'], 'Чужое'))
            self.assertTrue(notes.update('books', 'one.md', item['id'], 'Новая'))
            self.assertEqual(notes.list('books', 'one.md')[0]['body'], 'Новая')
            self.assertTrue(notes.delete('books', 'one.md', item['id']))
            self.assertEqual(notes.list('books', 'one.md'), [])


class JobPersistenceTests(unittest.TestCase):
    def test_interrupted_job_restores_and_resumes_from_saved_part(self):
        import speech_jobs as jobs
        with tempfile.TemporaryDirectory() as folder:
            storage = Path(folder)
            ident = 'a' * 32
            job_dir = storage / ident
            job_dir.mkdir()
            audio = job_dir / '0.audio'
            audio.write_bytes(b'first')
            job = {'fingerprint': 'hash', 'settings': {}, 'chunks': ['first', 'second'], 'files': [(audio, 'audio/wav')], 'state': 'generating', 'error': '', 'cancelled': False}
            with patch.object(jobs, 'JOB_STORAGE', storage), patch.object(jobs, 'JOBS', {}), patch.object(jobs.EXECUTOR, 'submit') as submit:
                jobs.save_job(ident, job)
                jobs.restore_jobs()
                restored = jobs.JOBS[ident]
                self.assertEqual(restored['state'], 'queued')
                self.assertEqual(len(restored['files']), 1)
                submit.assert_called_once()
                with patch.object(jobs, 'synthesize', return_value=(b'second', 'audio/wav')):
                    jobs.run_speech_job(ident)
                self.assertEqual(restored['state'], 'complete')
                self.assertEqual((job_dir / '1.audio').read_bytes(), b'second')
                self.assertEqual(audio.read_bytes(), b'first')


class EngineTests(unittest.TestCase):
    def test_piper_adapter_passes_settings_and_text(self):
        from speech_engines import generate_piper
        settings = app_config.load_settings(Path('/nonexistent/catalog-test-config.json'))
        def runner(command, timeout, repair_key, text):
            self.assertEqual(command[0], str(settings.piper_python))
            self.assertEqual(timeout, settings.piper_timeout)
            self.assertEqual(text, 'Привет')
            Path(command[command.index('--output_file') + 1]).write_bytes(b'audio')
            return type('Result', (), {'returncode': 0})()
        self.assertEqual(generate_piper(settings, 'Привет', 'ruslan', 1.0, runner), b'audio')


class SpeechServiceTests(unittest.TestCase):
    def test_preview_does_not_create_cache_and_final_reuses_cache(self):
        import speech_service
        settings = app_config.load_settings(Path('/nonexistent/catalog-test-config.json'))
        data = {'engine': 'local', 'kind': 'books', 'path': 'book.md', 'text': 'Привет', 'local_voice': 'ruslan', 'speed': 1.0}
        key = lambda job, text: 'a' * 64
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with patch.object(speech_service, 'generate_piper', return_value=b'audio') as generate:
                preview = speech_service.synthesize(dict(data, no_cache=True), settings, base, {'books': base}, key, None)
                self.assertEqual(preview, (b'audio', 'audio/wav'))
                self.assertEqual(generate.call_args.args[1], 'Привет.')
                self.assertFalse((base / '.speech-cache').exists())
                speech_service.synthesize(data, settings, base, {'books': base}, key, None)
                speech_service.synthesize(data, settings, base, {'books': base}, key, None)
                self.assertEqual(generate.call_count, 2)  # preview plus the first final

    def test_failed_new_version_does_not_remove_old_audio(self):
        import speech_jobs as jobs
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'book').mkdir()
            document = root / 'book/chapter.md'
            document.write_text('Оригинал', encoding='utf-8')
            ident_old, ident_new = 'a' * 32, 'b' * 32
            storage = root / 'jobs'
            (storage / ident_old).mkdir(parents=True)
            audio = storage / ident_old / '0.audio'
            audio.write_bytes(b'old')
            settings = {'kind': 'books', 'path': 'book/chapter.md', 'engine': 'local', 'local_voice': 'ruslan', 'speed': 1.0}
            old = {'fingerprint': 'old', 'settings': settings, 'chunks': ['Оригинал'], 'files': [(audio, 'audio/wav')], 'state': 'complete', 'error': '', 'cancelled': False}
            new = {'fingerprint': 'new', 'settings': settings, 'chunks': ['Новая'], 'files': [], 'state': 'queued', 'error': '', 'cancelled': False, 'source_hash': hashlib.sha256(document.read_bytes()).hexdigest()}
            with patch.object(jobs, 'JOB_STORAGE', storage), patch.object(jobs, 'ROOTS', {'books': root}), patch.object(jobs, 'JOBS', {ident_old: old, ident_new: new}), patch.object(jobs, 'synthesize', side_effect=RuntimeError('failed')):
                jobs.run_speech_job(ident_new)
                self.assertEqual(new['state'], 'error')
                self.assertEqual(old['state'], 'complete')
                self.assertEqual(audio.read_bytes(), b'old')


class FragmentRepairTests(unittest.TestCase):
    def test_timeout_splits_and_replaces_only_after_all_parts_succeed(self):
        import wave
        import speech_jobs as jobs
        from speech_service import SpeechRequestError
        def sound():
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\0' * 1600)
            return output.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            storage = Path(folder); identifier = 'c' * 32; directory = storage / identifier; directory.mkdir()
            file = directory / '0.audio'; file.write_bytes(b'original')
            text = 'Длинное предложение содержит достаточно слов для деления и последующего восстановления без пропусков.'
            repair = {'state': 'queued', 'error': ''}
            job = {'fingerprint': 'x', 'settings': {'engine': 'clone'}, 'chunks': [text], 'files': [(file, 'audio/wav')], 'state': 'complete', 'error': '', 'cancelled': False, 'repairs': {'0': repair}}
            calls = []
            def fake(data, *args):
                calls.append(data['text'])
                if len(calls) == 1: raise SpeechRequestError(504, 'timeout')
                self.assertEqual(file.read_bytes(), b'original')
                return sound(), 'audio/wav'
            with patch.object(jobs, 'JOB_STORAGE', storage), patch.object(jobs, 'JOBS', {identifier: job}), patch.object(jobs, 'synthesize', side_effect=fake):
                jobs.regenerate_part(identifier, 0)
            self.assertEqual(repair['state'], 'complete')
            self.assertEqual(' '.join(calls[1:]), text)
            with wave.open(str(file), 'rb') as wav:
                self.assertEqual(wav.getnframes(), 1600)


class FinalAudioLifecycleTests(unittest.TestCase):
    def test_previous_audio_replaced_only_after_matching_source_completes(self):
        import speech_jobs as jobs
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'book').mkdir()
            document = root / 'book/chapter.md'; document.write_text('Текущая версия', encoding='utf-8')
            storage = root / 'jobs'; old_id, new_id = 'a' * 32, 'b' * 32
            settings = {'kind': 'books', 'path': 'book/chapter.md', 'engine': 'local', 'local_voice': 'ruslan', 'speed': 1.0}
            items = {}
            for identifier, text in ((old_id, 'Старый текст'), (new_id, 'Текущая версия')):
                directory = storage / identifier; directory.mkdir(parents=True)
                file = directory / '0.audio'; file.write_bytes(identifier.encode())
                items[identifier] = {'fingerprint': identifier, 'settings': settings, 'chunks': [text], 'files': [(file, 'audio/wav')], 'state': 'complete', 'error': '', 'cancelled': False, 'source_hash': hashlib.sha256(document.read_bytes()).hexdigest()}
            with patch.object(jobs, 'JOB_STORAGE', storage), patch.object(jobs, 'ROOTS', {'books': root}), patch.object(jobs, 'JOBS', items), patch.object(jobs, '__file__', str(root / 'speech_jobs.py')):
                document.write_text('Изменено во время генерации', encoding='utf-8')
                jobs.cleanup_superseded(new_id)
                self.assertEqual(items[old_id]['state'], 'complete')
                self.assertTrue(items[old_id]['files'][0][0].exists())
                document.write_text('Текущая версия', encoding='utf-8')
                new_file = items[new_id]['files'][0][0]
                jobs.cleanup_superseded(new_id)
                self.assertEqual(items[old_id]['state'], 'superseded')
                self.assertEqual(items[old_id]['files'], [])
                self.assertEqual(new_file.read_bytes(), new_id.encode())


if __name__ == '__main__':
    unittest.main()
