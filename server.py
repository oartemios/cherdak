from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import os
import urllib.request
import urllib.error
import subprocess
import tempfile
import hashlib
import base64
import io
import wave
import uuid
import re
import sqlite3
import stat
import shutil
from app_config import BASE, SETTINGS, validate_settings
from catalog_paths import valid_note_path as validate_note_path
from speech_jobs import (JOBS, JOBS_LOCK, GENERATION_LOCK, REPAIR_PROCESSES, EXECUTOR,
                         save_job, restore_jobs, document_revision,
                         speech_cache_key, run_speech_job, run_generation_process, regenerate_part)
from speech_text import split_document_speech, split_speech
from speech_service import synthesize, SpeechRequestError
from notes_store import NotesStore
from config_store import ConfigStore, ConfigurationConflict

ROOTS = {'books': SETTINGS.books_root, 'games': SETTINGS.games_root}

NOTES = NotesStore(BASE / '.notes.sqlite3')
CONFIG = ConfigStore(BASE)

def valid_note_path(kind, path):
    return validate_note_path(ROOTS, kind, path)

def heading_pause_indices(job):
    titles = set(job['settings'].get('_heading_pauses', []))
    return [index for index, chunk in enumerate(job['chunks']) if chunk in titles]


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers(); self.wfile.write(data)
    def settings_state(self):
        result = CONFIG.read(SETTINGS)
        with JOBS_LOCK:
            result['generation_active'] = any(job['state'] in ('queued', 'generating', 'pausing') or any(repair.get('state') in ('queued', 'generating', 'stopping') for repair in job.get('repairs', {}).values()) for job in JOBS.values())
        result['openai_key_configured'] = bool(os.environ.get('OPENAI_API_KEY'))
        configured = validate_settings(result['values'])
        directories = ('books_root', 'games_root', 'voices_dir', 'qwen_tts_model', 'qwen_asr_model')
        executables = ('piper_python', 'mlx_python')
        result['path_checks'] = {name: getattr(configured, name).is_dir() for name in directories}
        result['path_checks'].update({name: getattr(configured, name).is_file() and os.access(getattr(configured, name), os.X_OK) for name in executables})
        return result
    def do_POST(self):
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            return self.send_error(403)
        if self.path == '/api/settings':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 50000: return self.send_json({'error': 'Некорректный размер запроса.'}, 400)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict): return self.send_json({'error': 'Некорректные настройки.'}, 400)
                CONFIG.save(data.get('values'), data.get('revision'))
                return self.send_json(self.settings_state())
            except ConfigurationConflict as exc: return self.send_json({'error': str(exc)}, 409)
            except (ValueError, TypeError, OSError) as exc: return self.send_json({'error': str(exc)}, 400)
        if self.path == '/api/speech-regenerate-stop':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 1000: return self.send_error(400)
                data = json.loads(self.rfile.read(length)); identifier, index = data.get('id'), data.get('index')
                if not isinstance(identifier, str) or type(index) is not int: return self.send_error(400)
                with JOBS_LOCK:
                    job = JOBS.get(identifier); repair = job.get('repairs', {}).get(str(index)) if job else None
                    if not repair: return self.send_error(404)
                    if repair['state'] == 'queued': repair['state'] = 'cancelled'
                    elif repair['state'] == 'generating':
                        repair['state'] = 'stopping'
                        process = REPAIR_PROCESSES.get((identifier, index))
                        if process and process.poll() is None:
                            try: process.terminate()
                            except ProcessLookupError: pass
                    save_job(identifier, job)
                    return self.send_json({'state': repair['state']})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/speech-regenerate':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(400)
                data = json.loads(self.rfile.read(length)); identifier = data.get('id'); index = data.get('index')
                if not isinstance(identifier, str) or type(index) is not int: return self.send_error(400)
                pronunciation = data.get('pronunciation')
                if pronunciation is not None and (not isinstance(pronunciation, str) or not pronunciation.strip() or len(pronunciation) > 2000):
                    return self.send_error(400, 'Invalid pronunciation text')
                with JOBS_LOCK:
                    job = JOBS.get(identifier)
                    if not job or job['cancelled']: return self.send_error(404)
                    if job['state'] in ('queued', 'generating', 'pausing'): return self.send_error(409, 'Pause generation before editing fragments')
                    if index < 0 or index >= len(job['files']): return self.send_error(400)
                    repairs = job.setdefault('repairs', {})
                    if repairs.get(str(index), {}).get('state') in ('queued', 'generating', 'stopping'): return self.send_json({'state': repairs[str(index)]['state']})
                    previous = repairs.get(str(index), {})
                    repairs[str(index)] = {'state': 'queued', 'error': ''}
                    if pronunciation is not None:
                        repairs[str(index)]['pronunciation'] = pronunciation.strip()
                    elif 'pronunciation' in previous:
                        repairs[str(index)]['pronunciation'] = previous['pronunciation']
                    save_job(identifier, job)
                    EXECUTOR.submit(regenerate_part, identifier, index)
                    return self.send_json({'state': 'queued'})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/notes':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); kind = data.get('kind'); path = data.get('path'); action = data.get('action')
                if not valid_note_path(kind, path): return self.send_error(400)
                if action == 'create':
                    body = data.get('body'); quote = data.get('quote', '')
                    if not isinstance(body, str) or not body.strip() or len(body) > 5000 or not isinstance(quote, str) or len(quote) > 1000: return self.send_error(400)
                    return self.send_json(NOTES.create(kind, path, body.strip(), quote.strip()))
                if action in ('delete', 'update'):
                    identifier = data.get('id')
                    if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier): return self.send_error(400)
                    if action == 'delete': changed = NOTES.delete(kind, path, identifier)
                    else:
                        body = data.get('body')
                        if not isinstance(body, str) or not body.strip() or len(body) > 5000: return self.send_error(400)
                        changed = NOTES.update(kind, path, identifier, body.strip())
                    if not changed: return self.send_error(404)
                    return self.send_json({'ok': True})
                return self.send_error(400)
            except (ValueError, OSError, TypeError, sqlite3.Error): return self.send_error(400)
        if self.path == '/api/speech-pause':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 1000: return self.send_error(400)
                identifier = json.loads(self.rfile.read(length)).get('id')
                with JOBS_LOCK:
                    job = JOBS.get(identifier)
                    if job is None: return self.send_error(404)
                    if job['state'] == 'queued': job['state'] = 'pausing'
                    elif job['state'] == 'generating': job['state'] = 'pausing'
                    save_job(identifier, job)
                    return self.send_json({'state': job['state']})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/speech-job':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 2_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); text = data.pop('text', '')
                data.pop('_synthetic_pipeline', None)
                engine = data.get('engine'); count = data.pop('sentences', 1); existing_only = data.pop('existing_only', False); expected_revision = data.pop('source_hash', None)
                if not isinstance(existing_only, bool): return self.send_error(400)
                if not isinstance(text, str) or not text.strip() or len(text) > 300000 or engine not in ('local', 'clone', 'openai', 'synthetic') or type(count) is not int or not 1 <= count <= 5: return self.send_error(400)
                if data.get('kind') not in ROOTS or not isinstance(data.get('path'), str) or not data['path']: return self.send_error(400)
                if engine == 'synthetic':
                    from synthetic_voice import voice_description
                    voice_description(data.get('synthetic_kind', 'female'), data.get('synthetic_age', 30))
                    data['_synthetic_pipeline'] = 2
                revision = document_revision(data)
                if revision is None: return self.send_error(400)
                if expected_revision is not None and (not isinstance(expected_revision, str) or expected_revision != revision): return self.send_error(409, 'File changed; reload before generation')
                headings = data.pop('headings', [])
                if not isinstance(headings, list) or any(not isinstance(title, str) for title in headings):
                    return self.send_error(400)
                chunks, pause_after = split_document_speech(text, engine, count, set(headings))
                data.pop('_heading_pauses', None)
                if pause_after: data['_heading_pauses'] = pause_after
                if not chunks: return self.send_error(400)
                fingerprint = hashlib.sha256(json.dumps({'text': text, 'settings': data, 'sentences': count}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                with JOBS_LOCK:
                    for identifier, existing in JOBS.items():
                        if existing['fingerprint'] == fingerprint and existing['state'] in ('queued', 'generating', 'complete', 'paused', 'pausing', 'error') and not existing['cancelled']:
                            if existing['state'] in ('paused', 'error') and not existing_only:
                                if existing['state'] == 'error' and len(existing['files']) < len(existing['chunks']):
                                    index = len(existing['files']); failed = existing['chunks'][index]
                                    parts = split_speech(failed, 'clone', 1)
                                    if len(parts) == 1 and len(failed) > 80:
                                        midpoint = len(failed) // 2
                                        cut = failed.rfind(' ', 0, midpoint + 1)
                                        if cut < 1: cut = failed.find(' ', midpoint)
                                        if cut > 0: parts = [failed[:cut].strip(), failed[cut:].strip()]
                                    existing['chunks'][index:index + 1] = parts
                                existing['state'] = 'queued'; existing['error'] = ''; save_job(identifier, existing)
                                EXECUTOR.submit(run_speech_job, identifier)
                            return self.send_json({'id': identifier, 'total': len(existing['chunks']), 'heading_pauses': heading_pause_indices(existing)})
                    if existing_only: return self.send_error(404, 'No prepared audio')
                    identifier = uuid.uuid4().hex
                    JOBS[identifier] = {'fingerprint': fingerprint, 'settings': data, 'chunks': chunks, 'files': [], 'state': 'queued', 'error': '', 'cancelled': False, 'source_hash': revision}
                    save_job(identifier, JOBS[identifier])
                EXECUTOR.submit(run_speech_job, identifier)
                return self.send_json({'id': identifier, 'total': len(chunks), 'heading_pauses': heading_pause_indices(JOBS[identifier])})
            except (ValueError, TypeError, OSError): return self.send_error(400)
        if self.path == '/api/speech-preview':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); text = data.get('text')
                if not isinstance(text, str) or not text.strip() or len(text) > 1000 or not valid_note_path(data.get('kind'), data.get('path')): return self.send_error(400)
                data['no_cache'] = True
                with GENERATION_LOCK:
                    audio, content_type = synthesize(data, SETTINGS, BASE, ROOTS, speech_cache_key, run_generation_process)
                self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio)
            except SpeechRequestError as exc: self.send_error(exc.status, str(exc))
            except (ValueError, OSError, TypeError): self.send_error(400)
            return
        if self.path == '/api/transcribe-sample':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); audio = base64.b64decode(data.get('audio', ''), validate=True)
                if len(audio) > 20_000_000: return self.send_error(413)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    if not 2 <= wav.getnframes() / wav.getframerate() <= 60 or wav.getcomptype() != 'NONE': return self.send_error(400)
                base = Path(__file__).parent
                model = SETTINGS.qwen_asr_model
                with tempfile.TemporaryDirectory() as tmp:
                    sample = Path(tmp) / 'sample.wav'; sample.write_bytes(audio)
                    output = Path(tmp) / 'transcript'
                    command = [str(SETTINGS.mlx_python), '-m', 'mlx_audio.stt.generate', '--model', str(model), '--audio', str(sample), '--output-path', str(output), '--format', 'txt', '--language', 'Russian']
                    result = subprocess.run(command, text=True, capture_output=True, timeout=SETTINGS.asr_timeout)
                    if result.returncode or not output.with_suffix('.txt').is_file(): return self.send_error(502, 'Transcription failed')
                    text = output.with_suffix('.txt').read_text(encoding='utf-8').strip()
                    if not text: return self.send_error(422, 'No speech detected')
                    return self.send_json({'text': text})
            except (ValueError, OSError, TypeError, wave.Error, EOFError, subprocess.TimeoutExpired): return self.send_error(502, 'Transcription failed')
        if self.path == '/api/synthetic-voice-save':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 10000: return self.send_error(400)
                data = json.loads(self.rfile.read(length))
                identifier, name, kind, path = data.get('id'), data.get('name'), data.get('kind'), data.get('path')
                if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier) or not isinstance(name, str): return self.send_error(400)
                name = name.strip()
                if not name or len(name) > 80 or not valid_note_path(kind, path): return self.send_error(400)
                with JOBS_LOCK:
                    job = JOBS.get(identifier)
                    if not job or job['cancelled'] or job['state'] == 'superseded' or job['settings'].get('kind') != kind or job['settings'].get('path') != path: return self.send_error(404)
                    if job['settings'].get('engine') != 'synthetic' or job['settings'].get('_synthetic_pipeline') != 2 or not job['files'] or not job['chunks']: return self.send_error(409, 'Synthetic reference is not ready')
                    # The immutable reference belongs to this job, not the possibly repaired first output.
                    reference = job['files'][0][0].parent / 'synthetic-reference.wav'
                    audio = reference.read_bytes()
                    transcript = job['chunks'][0]
                    with wave.open(io.BytesIO(audio), 'rb') as wav:
                        if wav.getnframes() <= 0 or wav.getframerate() <= 0 or wav.getcomptype() != 'NONE': return self.send_error(400, 'Invalid reference audio')
                    voice_id = uuid.uuid4().hex
                    folder = Path(__file__).parent / '.voice-profiles' / voice_id
                    folder.mkdir(mode=0o700, parents=True)
                    try:
                        (folder / 'reference.wav').write_bytes(audio)
                        (folder / 'transcript.txt').write_text(transcript, encoding='utf-8')
                        (folder / 'name.txt').write_text(name, encoding='utf-8')
                        (folder / 'origin.txt').write_text('synthetic', encoding='utf-8')
                    except OSError:
                        shutil.rmtree(folder, ignore_errors=True)
                        raise
                return self.send_json({'ok': True, 'id': voice_id, 'name': name})
            except (ValueError, OSError, TypeError, wave.Error, EOFError): return self.send_error(400, 'Cannot save synthetic reference')
        if self.path == '/api/voice-rename':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 10000: return self.send_error(400)
                data = json.loads(self.rfile.read(length)); identifier = data.get('id'); name = data.get('name')
                if not isinstance(identifier, str) or not isinstance(name, str): return self.send_error(400)
                name = name.strip()
                if not name or len(name) > 80: return self.send_error(400)
                base = Path(__file__).parent
                if identifier == 'legacy': folder = base / '.voice-sample'
                elif len(identifier) == 32 and all(c in '0123456789abcdef' for c in identifier): folder = base / '.voice-profiles' / identifier
                else: return self.send_error(400)
                if not (folder / 'reference.wav').is_file() or not (folder / 'transcript.txt').is_file(): return self.send_error(404)
                (folder / 'name.txt').write_text(name, encoding='utf-8')
                return self.send_json({'ok': True, 'name': name})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/voice-sample':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); transcript = data.get('transcript', '').strip()
                audio = base64.b64decode(data.get('audio', ''), validate=True)
                if not transcript or len(transcript) > 5000 or len(audio) > 20_000_000: return self.send_error(400)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    if not 2 <= duration <= 60 or wav.getcomptype() != 'NONE': return self.send_error(400)
                name = data.get('name', '').strip()
                emotion = data.get('emotion', 'neutral')
                if not name or len(name) > 80 or emotion not in ('neutral', 'joy', 'anxiety', 'anger', 'whisper'): return self.send_error(400)
                parent = data.get('parent_id') or None
                if parent is not None:
                    if not isinstance(parent, str) or (parent != 'legacy' and (len(parent) != 32 or any(c not in '0123456789abcdef' for c in parent))): return self.send_error(400)
                    parent_folder = Path(__file__).parent / ('.voice-sample' if parent == 'legacy' else '.voice-profiles/' + parent)
                    if not (parent_folder / 'reference.wav').is_file() or not (parent_folder / 'transcript.txt').is_file(): return self.send_error(404)
                    if (parent_folder / 'parent.txt').exists() or emotion not in ('neutral', 'whisper'): return self.send_error(400)
                identifier = uuid.uuid4().hex
                folder = Path(__file__).parent / '.voice-profiles' / identifier; folder.mkdir(mode=0o700, parents=True)
                (folder / 'reference.wav').write_bytes(audio); (folder / 'transcript.txt').write_text(transcript, encoding='utf-8'); (folder / 'name.txt').write_text(name, encoding='utf-8')
                (folder / 'emotion.txt').write_text(emotion, encoding='utf-8')
                if parent: (folder / 'parent.txt').write_text(parent, encoding='utf-8')
                return self.send_json({'ok': True, 'id': identifier, 'name': name, 'emotion': emotion, 'parent_id': parent, 'duration': round(duration, 1)})
            except (ValueError, OSError, TypeError, wave.Error, EOFError): return self.send_error(400, 'Invalid WAV or transcript')
        if self.path == '/api/speech-reset':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 10000: return self.send_error(400)
                data = json.loads(self.rfile.read(length))
                kind, path = data.get('kind'), data.get('path')
                if kind not in ROOTS or not isinstance(path, str) or not path: return self.send_error(400)
                with JOBS_LOCK:
                    for job_id, job in JOBS.items():
                        if job['settings'].get('kind') == kind and job['settings'].get('path') == path:
                            job['cancelled'] = True; job['state'] = 'cancelled'
                            for file, _ in job['files']: file.unlink(missing_ok=True)
                            job['files'].clear(); save_job(job_id, job)
                cache = Path(__file__).parent / '.speech-cache' / hashlib.sha256((kind + ':' + path).encode()).hexdigest()
                with GENERATION_LOCK:
                    if cache.is_dir():
                        for item in cache.glob('*.wav'):
                            if item.is_file(): item.unlink()
                return self.send_json({'ok': True})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/speech':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length))
                with GENERATION_LOCK:
                    audio, content_type = synthesize(data, SETTINGS, BASE, ROOTS, speech_cache_key, run_generation_process)
                self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio)
            except SpeechRequestError as exc: self.send_error(exc.status, str(exc))
            except (ValueError, OSError, TypeError): self.send_error(400)
            return
        if self.path == '/api/tags':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 100000: return self.send_error(413)
                data = json.loads(self.rfile.read(length))
                if data.get('kind') not in ROOTS or not isinstance(data.get('name'), str) or not isinstance(data.get('tags'), list) or not all(isinstance(t, str) and len(t) <= 60 for t in data['tags']): return self.send_error(400)
                file = Path(__file__).parent / 'tags.json'
                tags = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
                tags[data['kind'] + ':' + data['name']] = data['tags']
                file.write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding='utf-8')
                return self.send_json({'ok': True})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path != '/api/save': return self.send_error(404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 2_000_000: return self.send_error(413)
            data = json.loads(self.rfile.read(length))
            root = ROOTS.get(data.get('kind'))
            if not root: return self.send_error(400)
            root = root.resolve()
            target = (root / data.get('path', '')).resolve()
            if not target.is_relative_to(root) or not target.is_file() or target.suffix.lower() not in ('.md', '.markdown') or not isinstance(data.get('content'), str): return self.send_error(400)
            expected = data.get('source_hash')
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected): return self.send_error(400, 'File revision is required')
            current = target.read_bytes()
            if hashlib.sha256(current).hexdigest() != expected: return self.send_error(409, 'File changed since it was opened')
            encoded = data['content'].encode('utf-8')
            mode = stat.S_IMODE(target.stat().st_mode)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.catalog-save-', delete=False) as handle:
                    temporary = Path(handle.name); handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
                os.chmod(temporary, mode)
                # Recheck immediately before replacing to avoid overwriting a newer edit.
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected: return self.send_error(409, 'File changed since it was opened')
                os.replace(temporary, target); temporary = None
            finally:
                if temporary is not None: temporary.unlink(missing_ok=True)
            self.send_json({'ok': True, 'source_hash': hashlib.sha256(encoded).hexdigest()})
        except (ValueError, OSError, TypeError): self.send_error(400)
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/api/settings':
            try:
                return self.send_json(self.settings_state())
            except (ValueError, OSError) as exc: return self.send_json({'error': str(exc)}, 500)
        if url.path == '/api/speech-latest':
            q = parse_qs(url.query); kind = q.get('kind', [''])[0]; path = q.get('path', [''])[0]
            if not valid_note_path(kind, path): return self.send_error(400)
            with JOBS_LOCK:
                candidates = [(key, job) for key, job in JOBS.items() if job['state'] == 'complete' and not job['cancelled'] and job['settings'].get('kind') == kind and job['settings'].get('path') == path]
                voice_fields = ('engine', 'profile', 'local_voice', 'speed', 'voice', 'synthetic_kind', 'synthetic_age')
                filters = {field: q[field][0] for field in voice_fields if field in q}
                defaults = {'speed': 1.0, 'local_voice': 'ruslan', 'voice': 'marin', 'synthetic_kind': 'female', 'synthetic_age': 30}
                if 'speed' in filters:
                    try: filters['speed'] = float(filters['speed'])
                    except ValueError: return self.send_error(400)
                candidates = [
                    (key, job) for key, job in candidates
                    if all((job['settings'].get(field, defaults.get(field)) if field == 'speed'
                            else str(job['settings'].get(field, defaults.get(field)))) == value
                           for field, value in filters.items())
                ]
                if not candidates: return self.send_json({'job': None})
                identifier, job = max(candidates, key=lambda item: item[1].get('completed_at') or '')
                return self.send_json({'job': {'id': identifier, 'total': len(job['chunks']), 'text': ' '.join(job['chunks']), 'settings': job['settings'], 'heading_pauses': heading_pause_indices(job)}})
        if url.path == '/api/notes':
            try:
                q = parse_qs(url.query); kind = q.get('kind', [''])[0]; path = q.get('path', [''])[0]
                if not valid_note_path(kind, path): return self.send_error(400)
                return self.send_json(NOTES.list(kind, path))
            except (OSError, sqlite3.Error): return self.send_error(500)
        if url.path in ('/api/speech-job', '/api/speech-part', '/api/speech-parts'):
            q = parse_qs(url.query); identifier = q.get('id', [''])[0]
            with JOBS_LOCK:
                job = JOBS.get(identifier)
                if job is None: return self.send_error(404)
                if url.path == '/api/speech-job':
                    reference_ready = (
                        job['settings'].get('engine') == 'synthetic'
                        and job['settings'].get('_synthetic_pipeline') == 2
                        and not job['cancelled'] and job['state'] != 'superseded'
                        and bool(job['files'])
                        and (job['files'][0][0].parent / 'synthetic-reference.wav').is_file()
                    )
                    return self.send_json({'state': job['state'], 'ready': len(job['files']), 'total': len(job['chunks']), 'error': job['error'], 'synthetic_reference_ready': reference_ready})
                if url.path == '/api/speech-parts': return self.send_json([{'index': index, 'text': text, 'ready': index < len(job['files']), 'repair': job.get('repairs', {}).get(str(index))} for index, text in enumerate(job['chunks'])])
                try: index = int(q.get('index', ['-1'])[0])
                except ValueError: return self.send_error(400)
                if index < 0 or index >= len(job['files']): return self.send_error(404)
                file, content_type = job['files'][index]
                try: audio = file.read_bytes()
                except OSError: return self.send_error(404)
            self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio); return
        if url.path == '/api/voices':
            base = Path(__file__).parent; profiles = []
            legacy = base / '.voice-sample'
            if (legacy / 'reference.wav').is_file() and (legacy / 'transcript.txt').is_file(): profiles.append({'id': 'legacy', 'name': (legacy / 'name.txt').read_text(encoding='utf-8') if (legacy / 'name.txt').is_file() else 'Мой голос'})
            folder = base / '.voice-profiles'
            if folder.is_dir():
                for item in folder.iterdir():
                    if item.is_dir() and len(item.name) == 32 and all(c in '0123456789abcdef' for c in item.name) and (item / 'reference.wav').is_file() and (item / 'transcript.txt').is_file() and (item / 'name.txt').is_file():
                        profiles.append({'id': item.name, 'name': (item / 'name.txt').read_text(encoding='utf-8'), 'emotion': (item / 'emotion.txt').read_text(encoding='utf-8').strip() if (item / 'emotion.txt').is_file() else 'neutral', 'parent_id': (item / 'parent.txt').read_text(encoding='utf-8').strip() if (item / 'parent.txt').is_file() else None, 'origin': (item / 'origin.txt').read_text(encoding='utf-8').strip() if (item / 'origin.txt').is_file() else None})
            return self.send_json(profiles)
        if url.path == '/api/search':
            q = parse_qs(url.query); term = q.get('q', [''])[0].strip().casefold(); kind_filter = q.get('kind', ['all'])[0]
            if not term or len(term) > 200 or kind_filter not in ('all', 'books', 'games'): return self.send_error(400)
            results = []
            for kind, root in ROOTS.items():
                if kind_filter != 'all' and kind != kind_filter: continue
                root = root.resolve()
                if not root.is_dir(): continue
                for directory, dirs, files in os.walk(root, followlinks=False):
                    dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
                    for name in sorted(files):
                        file = Path(directory) / name
                        if name.startswith('.') or file.is_symlink() or file.suffix.lower() not in ('.md', '.markdown') or len(file.relative_to(root).parts) < 2: continue
                        try:
                            if file.stat().st_size > 2_000_000: continue
                            lines = file.read_text(encoding='utf-8').splitlines()
                        except (OSError, UnicodeError): continue
                        for number, line in enumerate(lines, 1):
                            if term in line.casefold():
                                results.append({'kind': kind, 'path': str(file.relative_to(root)), 'line': number, 'snippet': line.strip()[:300]})
                                if len(results) >= 200: return self.send_json({'results': results, 'truncated': True})
            return self.send_json({'results': results, 'truncated': False})
        if url.path == '/api/projects':
            projects = []
            for kind, root in ROOTS.items():
                for p in root.iterdir():
                    if not p.is_dir() or p.name.startswith('.') or p == Path(__file__).resolve().parent: continue
                    projects.append({'name': p.name, 'kind': kind, 'modified': p.stat().st_mtime})
            tagfile = Path(__file__).parent / 'tags.json'
            tags = json.loads(tagfile.read_text(encoding='utf-8')) if tagfile.exists() else {}
            for project in projects: project['tags'] = tags.get(project['kind'] + ':' + project['name'], [])
            self.send_json(projects)
        elif url.path == '/api/resolve':
            q = parse_qs(url.query); root = ROOTS.get(q.get('kind', [''])[0]); current = q.get('path', [''])[0]; link = q.get('link', [''])[0].split('#', 1)[0].strip()
            if not root or not current or not link: return self.send_error(400)
            root = root.resolve(); project_name = current.split('/')[0]; project = (root / project_name).resolve()
            if not project.is_relative_to(root) or not project.is_dir(): return self.send_error(404)
            candidates = []
            for base in ((root / current).parent, project):
                for suffix in ('', '.md', '.markdown'):
                    candidate = (base / (link + suffix)).resolve()
                    if candidate.is_relative_to(project) and candidate.is_file(): candidates.append(candidate)
            if not candidates and '/' not in link and '\\' not in link:
                for candidate in project.rglob('*'):
                    if candidate.is_file() and candidate.resolve().is_relative_to(project) and (candidate.name.casefold() == link.casefold() or candidate.stem.casefold() == link.casefold() and candidate.suffix.lower() in ('.md', '.markdown')): candidates.append(candidate.resolve())
            if not candidates: return self.send_error(404)
            self.send_json({'path': str(candidates[0].relative_to(root))})
        elif url.path == '/api/image':
            q = parse_qs(url.query); root = ROOTS.get(q.get('kind', [''])[0]); relative = q.get('path', [''])[0]
            if not root or not relative: return self.send_error(400)
            root = root.resolve(); target = (root / relative).resolve()
            if not target.is_relative_to(root) or target == root or target.suffix.lower() != '.png' or not target.is_file(): return self.send_error(404)
            try:
                with target.open('rb') as image:
                    if image.read(8) != b'\x89PNG\r\n\x1a\n': return self.send_error(415, 'Invalid PNG file')
                    image.seek(0); size = os.fstat(image.fileno()).st_size
                    self.send_response(200); self.send_header('Content-Type', 'image/png'); self.send_header('Content-Length', str(size)); self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Cache-Control', 'no-store'); self.end_headers()
                    shutil.copyfileobj(image, self.wfile)
            except OSError: return self.send_error(404)
        elif url.path == '/api/browse':
            q = parse_qs(url.query); root = ROOTS.get(q.get('kind', [''])[0]); relative = q.get('path', [''])[0]
            if not root: return self.send_error(400)
            root = root.resolve(); target = (root / relative).resolve()
            if not target.is_relative_to(root) or target == root or not target.exists(): return self.send_error(404)
            try:
                if target.is_dir():
                    entries = [{'name': p.name, 'directory': p.is_dir()} for p in target.iterdir() if not p.name.startswith('.') and p.resolve().is_relative_to(root)]
                    self.send_json({'directory': True, 'entries': sorted(entries, key=lambda x: (not x['directory'], x['name'].casefold()))})
                else:
                    if target.suffix.lower() == '.png': return self.send_json({'directory': False, 'image': True})
                    if target.stat().st_size > 2_000_000: return self.send_error(413)
                    raw = target.read_bytes()
                    self.send_json({'directory': False, 'content': raw.decode('utf-8'), 'source_hash': hashlib.sha256(raw).hexdigest()})
            except (OSError, UnicodeError): self.send_error(415, 'Cannot display this file')
        elif url.path in ('/assets/app.js', '/assets/styles.css', '/assets/sidebar.js', '/assets/markdown.js', '/assets/canvas.js', '/assets/notes.js', '/assets/speech.js', '/assets/settings.js'):
            asset = {'/assets/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/assets/styles.css': ('styles.css', 'text/css; charset=utf-8'), '/assets/sidebar.js': ('sidebar.js', 'text/javascript; charset=utf-8'), '/assets/markdown.js': ('markdown.js', 'text/javascript; charset=utf-8'), '/assets/canvas.js': ('canvas.js', 'text/javascript; charset=utf-8'), '/assets/notes.js': ('notes.js', 'text/javascript; charset=utf-8'), '/assets/speech.js': ('speech.js', 'text/javascript; charset=utf-8'), '/assets/settings.js': ('settings.js', 'text/javascript; charset=utf-8')}[url.path]
            data = (BASE / 'web' / asset[0]).read_bytes()
            self.send_response(200); self.send_header('Content-Type', asset[1]); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        elif url.path == '/settings':
            data = (BASE / 'web' / 'settings.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        elif url.path in ('/', '/project'):
            data = (BASE / 'web' / 'index.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(data)
        else: self.send_error(404)
if __name__ == '__main__':
    print(f'Каталог: http://127.0.0.1:{SETTINGS.port}', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', SETTINGS.port), Handler)
    restore_jobs()
    server.serve_forever()
