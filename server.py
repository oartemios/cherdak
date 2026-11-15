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
import threading
import sqlite3
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

ROOTS = {'books': Path(__file__).resolve().parent.parent, 'games': Path.home() / 'Development/games'}

def notes_db():
    db = sqlite3.connect(Path(__file__).resolve().parent / '.notes.sqlite3', timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL, quote TEXT NOT NULL, created TEXT NOT NULL)')
    return db

def valid_note_path(kind, path):
    root = ROOTS.get(kind)
    if root is None or not isinstance(path, str) or not path: return False
    target = (root / path).resolve()
    return target.is_relative_to(root.resolve()) and target.is_file() and target.suffix.lower() in ('.md', '.markdown')

JOBS = {}
JOBS_LOCK = threading.RLock()
GENERATION_LOCK = threading.RLock()
REPAIR_PROCESSES = {}
EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOB_STORAGE = Path(__file__).resolve().parent / '.speech-jobs'

def save_job(job_id, job):
    folder = JOB_STORAGE / job_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {key: job[key] for key in ('fingerprint', 'settings', 'chunks', 'state', 'error', 'cancelled')}
    data['files'] = [{'name': file.name, 'type': content_type} for file, content_type in job['files']]
    data['repairs'] = job.get('repairs', {})
    data['source_hash'] = job.get('source_hash')
    data['completed_at'] = job.get('completed_at')
    temp = folder / 'job.json.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, folder / 'job.json')

def restore_jobs(port):
    if not JOB_STORAGE.is_dir(): return
    for folder in sorted(JOB_STORAGE.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r'[0-9a-f]{32}', folder.name): continue
        try:
            data = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
            files = []
            for index, item in enumerate(data.pop('files')):
                if item['name'] != f'{index}.audio': raise ValueError('Invalid file')
                file = folder / item['name']
                if not file.is_file(): break
                files.append((file, item['type']))
            if data['state'] == 'complete' and len(files) != len(data['chunks']): data['state'] = 'queued'
            if data['state'] == 'pausing': data['state'] = 'paused'
            if data['state'] in ('queued', 'generating'): data['state'] = 'queued'
            data['files'] = files
            for item in data.get('repairs', {}).values():
                if item.get('state') in ('queued', 'generating', 'stopping'): item['state'] = 'error'; item['error'] = 'Сервер перезапущен; запустите перегенерацию снова.'
            with JOBS_LOCK:
                JOBS[folder.name] = data
                save_job(folder.name, data)
            if data['state'] == 'queued' and not data['cancelled']: EXECUTOR.submit(run_speech_job, folder.name, port)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue

def document_revision(settings):
    kind, path = settings.get('kind'), settings.get('path')
    if not valid_note_path(kind, path): return None
    try: return hashlib.sha256((ROOTS[kind] / path).read_bytes()).hexdigest()
    except OSError: return None

def speech_cache_key(job, text):
    settings = job['settings']; engine = settings.get('engine')
    if engine == 'local':
        return hashlib.sha256(json.dumps({'text': text, 'voice': settings.get('local_voice', 'ruslan'), 'speed': settings.get('speed', 1.0), 'version': 1}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if engine == 'clone':
        identifier = settings.get('profile'); base = Path(__file__).resolve().parent
        if identifier == 'legacy': folder = base / '.voice-sample'
        elif isinstance(identifier, str) and re.fullmatch(r'[0-9a-f]{32}', identifier): folder = base / '.voice-profiles' / identifier
        else: return None
        try: return hashlib.sha256(text.encode() + (folder / 'reference.wav').read_bytes() + (folder / 'transcript.txt').read_text(encoding='utf-8').encode() + b'qwen-v2-short-sentences').hexdigest()
        except OSError: return None
    return None

def cleanup_superseded(job_id):
    # Only promote output if its source file has not changed during generation.
    current = JOBS[job_id]; revision = current.get('source_hash')
    if not revision or document_revision(current['settings']) != revision: return
    settings = current['settings']; identity = tuple(settings.get(k) for k in ('kind', 'path', 'engine', 'profile', 'local_voice', 'speed', 'voice'))
    old_jobs = [(key, job) for key, job in JOBS.items() if key != job_id and job['state'] in ('complete', 'error', 'paused') and not job['cancelled'] and tuple(job['settings'].get(k) for k in ('kind', 'path', 'engine', 'profile', 'local_voice', 'speed', 'voice')) == identity and not any(x.get('state') in ('queued', 'generating', 'stopping') for x in job.get('repairs', {}).values())]
    if not old_jobs: return
    old_keys = {speech_cache_key(job, chunk) for _, job in old_jobs for chunk in job['chunks']}
    old_ids = {key for key, _ in old_jobs}
    keep_keys = {speech_cache_key(job, chunk) for key, job in JOBS.items() if key not in old_ids and not job['cancelled'] and job['state'] != 'superseded' and job['settings'].get('kind') == settings.get('kind') and job['settings'].get('path') == settings.get('path') for chunk in job['chunks']}
    for key, job in old_jobs:
        job['state'] = 'superseded'; files = list(job['files']); job['files'] = []; save_job(key, job)
        for file, _ in files:
            try: file.unlink(missing_ok=True)
            except OSError: pass
    cache = Path(__file__).resolve().parent / '.speech-cache' / hashlib.sha256((settings['kind'] + ':' + settings['path']).encode()).hexdigest()
    for key in old_keys - keep_keys - {None}:
        try: (cache / (key + '.wav')).unlink(missing_ok=True)
        except OSError: pass

def split_speech(text, engine, count):
    limit = min(600, 180 * count) if engine == 'clone' else 1500
    pieces = []
    for paragraph in re.split(r'\n+', text):
        paragraph = paragraph.strip()
        if not paragraph: continue
        sentences = re.split(r'(?<=[.!?…])\s+(?=[^\s])', paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            while len(sentence) > limit:
                cut = sentence.rfind(' ', 0, limit + 1)
                if cut <= 0: cut = limit
                pieces.append((sentence[:cut].strip(), True))
                sentence = sentence[cut:].strip()
            if sentence: pieces.append((sentence, False))
    chunks, current, total = [], '', 0
    for part, forced in pieces:
        if current and len(current) + len(part) + 1 > limit:
            chunks.append(current); current = ''; total = 0
        current += (' ' if current else '') + part
        total += 1
        if forced or (engine == 'clone' and total >= count):
            chunks.append(current); current = ''; total = 0
    if current: chunks.append(current)
    return chunks

def run_speech_job(job_id, port):
    with JOBS_LOCK: job = JOBS[job_id]
    retries = {}
    while len(job['files']) < len(job['chunks']):
        chunk = job['chunks'][len(job['files'])]
        with JOBS_LOCK:
            if job['cancelled']: job['state'] = 'cancelled'; return
            if job['state'] in ('paused', 'pausing'):
                job['state'] = 'paused'; save_job(job_id, job); return
            job['state'] = 'generating'; save_job(job_id, job)
        payload = dict(job['settings'], text=chunk)
        try:
            with GENERATION_LOCK:
                with JOBS_LOCK:
                    if job['cancelled']: job['state'] = 'cancelled'; return
                    if job['state'] in ('paused', 'pausing'):
                        job['state'] = 'paused'; save_job(job_id, job); return
                request = urllib.request.Request('http://127.0.0.1:%s/api/speech' % port, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=650) as response:
                    audio = response.read(); content_type = response.headers.get_content_type()
                with JOBS_LOCK:
                    if job['cancelled']: job['state'] = 'cancelled'; return
                    folder = JOB_STORAGE / job_id
                    file = folder / (str(len(job['files'])) + '.audio')
                    temporary = folder / (file.name + '.tmp')
                    temporary.write_bytes(audio); os.replace(temporary, file)
                    job['files'].append((file, content_type))
                    if job['state'] == 'pausing':
                        job['state'] = 'complete' if len(job['files']) == len(job['chunks']) else 'paused'
                        if job['state'] == 'complete': job['completed_at'] = datetime.now(timezone.utc).isoformat()
                        save_job(job_id, job)
                        if job['state'] == 'complete': cleanup_superseded(job_id)
                        return
                    save_job(job_id, job)
        except urllib.error.HTTPError as exc:
            with JOBS_LOCK:
                if job['cancelled']: job['state'] = 'cancelled'; return
                index = len(job['files']); failed = job['chunks'][index]
                attempts = retries.get(index, 0)
                if exc.code == 504 and len(failed) > 60 and attempts < 3:
                    parts = split_speech(failed, 'clone', 1)
                    if len(parts) == 1:
                        midpoint = len(failed) // 2
                        cut = failed.rfind(' ', 0, midpoint + 1)
                        if cut < 1: cut = failed.find(' ', midpoint)
                        if cut > 0: parts = [failed[:cut].strip(), failed[cut:].strip()]
                    if len(parts) > 1:
                        job['chunks'][index:index + 1] = parts
                        retries[index] = attempts + 1
                        save_job(job_id, job)
                        continue
                job['state'] = 'error'; job['error'] = 'Не удалось создать аудиофрагмент. Проверьте настройки голоса и доступность модели.'; save_job(job_id, job)
            return
        except Exception:
            with JOBS_LOCK: job['state'] = 'error'; job['error'] = 'Не удалось создать аудиофрагмент. Проверьте настройки голоса и доступность модели.'; save_job(job_id, job)
            return
    with JOBS_LOCK:
        job['state'] = 'complete'; job['completed_at'] = datetime.now(timezone.utc).isoformat(); save_job(job_id, job)
        cleanup_superseded(job_id)
def run_generation_process(command, timeout, repair_key=None, input_text=None):
    with JOBS_LOCK:
        if repair_key is not None:
            job = JOBS.get(repair_key[0]); repair = job.get('repairs', {}).get(str(repair_key[1])) if job else None
            if not repair or repair.get('state') != 'generating' or job['cancelled']: raise RuntimeError('Repair stopped')
        process = subprocess.Popen(command, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if repair_key is not None: REPAIR_PROCESSES[repair_key] = process
    try:
        try: stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate(); raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        with JOBS_LOCK:
            if repair_key is not None and REPAIR_PROCESSES.get(repair_key) is process: del REPAIR_PROCESSES[repair_key]

def regenerate_part(job_id, index, port):
    with JOBS_LOCK:
        job = JOBS[job_id]; repair = job['repairs'][str(index)]
        if job['cancelled'] or repair['state'] != 'queued': repair['state'] = 'cancelled'; save_job(job_id, job); return
        repair['state'] = 'generating'; save_job(job_id, job)
        payload = dict(job['settings'], text=job['chunks'][index], force=True, repair_job=job_id, repair_index=index)
    try:
        with GENERATION_LOCK:
            with JOBS_LOCK:
                if job['cancelled'] or repair['state'] != 'generating': repair['state'] = 'cancelled'; save_job(job_id, job); return
            def generate_piece(text, depth=0):
                request_data = dict(payload, text=text)
                request = urllib.request.Request('http://127.0.0.1:%s/api/speech' % port, data=json.dumps(request_data).encode(), headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=650) as response:
                        return response.read(), response.headers.get_content_type()
                except urllib.error.HTTPError as exc:
                    if exc.code != 504 or payload.get('engine') != 'clone' or depth >= 3 or len(text) <= 60: raise
                    parts = split_speech(text, 'clone', 1)
                    if len(parts) == 1:
                        midpoint = len(text) // 2; cut = text.rfind(' ', 0, midpoint + 1)
                        if cut < 1: cut = text.find(' ', midpoint)
                        if cut <= 0: raise
                        parts = [text[:cut].strip(), text[cut:].strip()]
                    with JOBS_LOCK:
                        if job['cancelled'] or repair['state'] != 'generating': raise RuntimeError('Cancelled')
                    pieces = [generate_piece(part, depth + 1) for part in parts]
                    output = io.BytesIO(); params = None
                    with wave.open(output, 'wb') as writer:
                        for raw, content_type in pieces:
                            if content_type != 'audio/wav': raise ValueError('Unsupported audio format')
                            with wave.open(io.BytesIO(raw), 'rb') as reader:
                                current = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
                                if params is None: params = current; writer.setparams(reader.getparams())
                                elif params != current: raise ValueError('Incompatible audio formats')
                                writer.writeframes(reader.readframes(reader.getnframes()))
                    return output.getvalue(), 'audio/wav'
            audio, content_type = generate_piece(payload['text'])
            with JOBS_LOCK:
                if job['cancelled'] or repair['state'] != 'generating': repair['state'] = 'cancelled'; save_job(job_id, job); return
                file = job['files'][index][0]; temporary = file.with_suffix('.repair-tmp')
                temporary.write_bytes(audio); os.replace(temporary, file)
                job['files'][index] = (file, content_type); repair['state'] = 'complete'; save_job(job_id, job)
    except Exception:
        with JOBS_LOCK:
            stopped = job['cancelled'] or repair['state'] in ('stopping', 'cancelled')
            repair['state'] = 'cancelled' if stopped else 'error'; repair['error'] = '' if stopped else 'Не удалось перегенерировать фрагмент. Прежнее аудио сохранено.'; save_job(job_id, job)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        if self.path == '/api/speech-regenerate-stop':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
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
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 1000: return self.send_error(400)
                data = json.loads(self.rfile.read(length)); identifier = data.get('id'); index = data.get('index')
                if not isinstance(identifier, str) or type(index) is not int: return self.send_error(400)
                with JOBS_LOCK:
                    job = JOBS.get(identifier)
                    if not job or job['cancelled']: return self.send_error(404)
                    if job['state'] in ('queued', 'generating', 'pausing'): return self.send_error(409, 'Pause generation before editing fragments')
                    if index < 0 or index >= len(job['files']): return self.send_error(400)
                    repairs = job.setdefault('repairs', {})
                    if repairs.get(str(index), {}).get('state') in ('queued', 'generating', 'stopping'): return self.send_json({'state': repairs[str(index)]['state']})
                    repairs[str(index)] = {'state': 'queued', 'error': ''}; save_job(identifier, job)
                    EXECUTOR.submit(regenerate_part, identifier, index, self.server.server_port)
                    return self.send_json({'state': 'queued'})
            except (ValueError, OSError, TypeError): return self.send_error(400)
        if self.path == '/api/notes':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); kind = data.get('kind'); path = data.get('path'); action = data.get('action')
                if not valid_note_path(kind, path): return self.send_error(400)
                with notes_db() as db:
                    if action == 'create':
                        body = data.get('body'); quote = data.get('quote', '')
                        if not isinstance(body, str) or not body.strip() or len(body) > 5000 or not isinstance(quote, str) or len(quote) > 1000: return self.send_error(400)
                        identifier = uuid.uuid4().hex; created = datetime.now(timezone.utc).isoformat()
                        db.execute('INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)', (identifier, kind, path, body.strip(), quote.strip(), created))
                        return self.send_json({'id': identifier, 'body': body.strip(), 'quote': quote.strip(), 'created': created})
                    if action in ('delete', 'update'):
                        identifier = data.get('id')
                        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier): return self.send_error(400)
                        if action == 'delete': result = db.execute('DELETE FROM notes WHERE id=? AND kind=? AND path=?', (identifier, kind, path))
                        else:
                            body = data.get('body')
                            if not isinstance(body, str) or not body.strip() or len(body) > 5000: return self.send_error(400)
                            result = db.execute('UPDATE notes SET body=? WHERE id=? AND kind=? AND path=?', (body.strip(), identifier, kind, path))
                        if result.rowcount != 1: return self.send_error(404)
                        return self.send_json({'ok': True})
                    return self.send_error(400)
            except (ValueError, OSError, TypeError, sqlite3.Error): return self.send_error(400)
        if self.path == '/api/speech-pause':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
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
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 2_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); text = data.pop('text', '')
                engine = data.get('engine'); count = data.pop('sentences', 1); existing_only = data.pop('existing_only', False); expected_revision = data.pop('source_hash', None)
                if not isinstance(existing_only, bool): return self.send_error(400)
                if not isinstance(text, str) or not text.strip() or len(text) > 300000 or engine not in ('local', 'clone', 'openai') or type(count) is not int or not 1 <= count <= 5: return self.send_error(400)
                if data.get('kind') not in ROOTS or not isinstance(data.get('path'), str) or not data['path']: return self.send_error(400)
                revision = document_revision(data)
                if revision is None: return self.send_error(400)
                if expected_revision is not None and (not isinstance(expected_revision, str) or expected_revision != revision): return self.send_error(409, 'File changed; reload before generation')
                chunks = split_speech(text, engine, count)
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
                                EXECUTOR.submit(run_speech_job, identifier, self.server.server_port)
                            return self.send_json({'id': identifier, 'total': len(existing['chunks'])})
                    if existing_only: return self.send_error(404, 'No prepared audio')
                    identifier = uuid.uuid4().hex
                    JOBS[identifier] = {'fingerprint': fingerprint, 'settings': data, 'chunks': chunks, 'files': [], 'state': 'queued', 'error': '', 'cancelled': False, 'source_hash': revision}
                    save_job(identifier, JOBS[identifier])
                EXECUTOR.submit(run_speech_job, identifier, self.server.server_port)
                return self.send_json({'id': identifier, 'total': len(chunks)})
            except (ValueError, TypeError, OSError): return self.send_error(400)
        if self.path == '/api/speech-preview':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); text = data.get('text')
                if not isinstance(text, str) or not text.strip() or len(text) > 1000 or data.get('engine') not in ('local', 'clone', 'openai') or not valid_note_path(data.get('kind'), data.get('path')): return self.send_error(400)
                data['no_cache'] = True
                request = urllib.request.Request('http://127.0.0.1:%s/api/speech' % self.server.server_port, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
                with GENERATION_LOCK:
                    with urllib.request.urlopen(request, timeout=180) as response:
                        audio = response.read(); content_type = response.headers.get_content_type()
                self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio)
            except urllib.error.HTTPError as exc: self.send_error(exc.code, 'Preview generation failed')
            except (ValueError, OSError, TypeError): self.send_error(502, 'Preview generation failed')
            return
        if self.path == '/api/transcribe-sample':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); audio = base64.b64decode(data.get('audio', ''), validate=True)
                if len(audio) > 20_000_000: return self.send_error(413)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    if not 2 <= wav.getnframes() / wav.getframerate() <= 60 or wav.getcomptype() != 'NONE': return self.send_error(400)
                base = Path(__file__).parent
                model = Path.home() / '.cache/lm-studio/models/mlx-community/Qwen3-ASR-0.6B-8bit'
                with tempfile.TemporaryDirectory() as tmp:
                    sample = Path(tmp) / 'sample.wav'; sample.write_bytes(audio)
                    output = Path(tmp) / 'transcript'
                    command = [str(base / '.clone-env/bin/python'), '-m', 'mlx_audio.stt.generate', '--model', str(model), '--audio', str(sample), '--output-path', str(output), '--format', 'txt', '--language', 'Russian']
                    result = subprocess.run(command, text=True, capture_output=True, timeout=300)
                    if result.returncode or not output.with_suffix('.txt').is_file(): return self.send_error(502, 'Transcription failed')
                    text = output.with_suffix('.txt').read_text(encoding='utf-8').strip()
                    if not text: return self.send_error(422, 'No speech detected')
                    return self.send_json({'text': text})
            except (ValueError, OSError, TypeError, wave.Error, EOFError, subprocess.TimeoutExpired): return self.send_error(502, 'Transcription failed')
        if self.path == '/api/voice-rename':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
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
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30_000_000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); transcript = data.get('transcript', '').strip()
                audio = base64.b64decode(data.get('audio', ''), validate=True)
                if not transcript or len(transcript) > 5000 or len(audio) > 20_000_000: return self.send_error(400)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    if not 2 <= duration <= 60 or wav.getcomptype() != 'NONE': return self.send_error(400)
                name = data.get('name', '').strip()
                if not name or len(name) > 80: return self.send_error(400)
                identifier = uuid.uuid4().hex
                folder = Path(__file__).parent / '.voice-profiles' / identifier; folder.mkdir(mode=0o700, parents=True)
                (folder / 'reference.wav').write_bytes(audio); (folder / 'transcript.txt').write_text(transcript, encoding='utf-8'); (folder / 'name.txt').write_text(name, encoding='utf-8')
                return self.send_json({'ok': True, 'id': identifier, 'name': name, 'duration': round(duration, 1)})
            except (ValueError, OSError, TypeError, wave.Error, EOFError): return self.send_error(400, 'Invalid WAV or transcript')
        if self.path == '/api/speech-reset':
            try:
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
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
                if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 30000: return self.send_error(413)
                data = json.loads(self.rfile.read(length)); text = data.get('text', ''); force = data.get('force', False); no_cache = data.get('no_cache', False)
                if not isinstance(no_cache, bool): return self.send_error(400)
                if not isinstance(force, bool): return self.send_error(400)
                repair_job, repair_index = data.get('repair_job'), data.get('repair_index')
                repair_key = None
                if repair_job is not None or repair_index is not None:
                    if not force or not isinstance(repair_job, str) or type(repair_index) is not int: return self.send_error(400)
                    repair_key = (repair_job, repair_index)
                if not isinstance(text, str) or not 0 < len(text) <= 2000: return self.send_error(400)
                if data.get('engine') == 'clone':
                    base = Path(__file__).parent
                    voice_id = data.get('profile', '')
                    if voice_id == 'legacy': folder = base / '.voice-sample'
                    elif isinstance(voice_id, str) and len(voice_id) == 32 and all(c in '0123456789abcdef' for c in voice_id): folder = base / '.voice-profiles' / voice_id
                    else: return self.send_error(400, 'Invalid voice')
                    sample = folder / 'reference.wav'; transcript = folder / 'transcript.txt'
                    if not sample.is_file() or not transcript.is_file(): return self.send_error(400, 'Voice sample is missing')
                    kind, path = data.get('kind'), data.get('path')
                    if kind not in ROOTS or not isinstance(path, str) or not path: return self.send_error(400)
                    cache = base / '.speech-cache' / hashlib.sha256((kind + ':' + path).encode()).hexdigest(); cache.mkdir(parents=True, exist_ok=True)
                    ref_text = transcript.read_text(encoding='utf-8')
                    key = hashlib.sha256(text.encode() + sample.read_bytes() + ref_text.encode() + b'qwen-v2-short-sentences').hexdigest()
                    cached = cache / (key + '.wav')
                    if no_cache or force or not cached.is_file():
                        with tempfile.TemporaryDirectory() as tmp:
                            command = [str(base / '.clone-env/bin/python'), '-m', 'mlx_audio.tts.generate', '--model', str(base / 'models/qwen3-tts-0.6b'), '--text', text, '--ref_audio', str(sample), '--ref_text', ref_text, '--lang_code', 'Russian', '--output_path', tmp, '--file_prefix', 'speech', '--join_audio']
                            result = run_generation_process(command, 150, repair_key)
                            outputs = list(Path(tmp).glob('speech*.wav'))
                            if result.returncode or not outputs: return self.send_error(502, 'Voice cloning failed')
                            audio = outputs[0].read_bytes()
                            if not no_cache:
                                temporary_cache = cached.with_suffix('.tmp')
                                temporary_cache.write_bytes(audio); os.replace(temporary_cache, cached)
                    else: audio = cached.read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'audio/wav'); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio); return
                if data.get('engine') == 'local':
                    base = Path(__file__).parent
                    local_voice = data.get('local_voice', 'ruslan')
                    if local_voice not in ('ruslan', 'irina', 'dmitri'): return self.send_error(400)
                    speed = data.get('speed', 1.0)
                    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.7 <= speed <= 1.3: return self.send_error(400)
                    kind, path = data.get('kind'), data.get('path')
                    if kind not in ROOTS or not isinstance(path, str) or not path: return self.send_error(400)
                    cache = base / '.speech-cache' / hashlib.sha256((kind + ':' + path).encode()).hexdigest()
                    cache.mkdir(parents=True, exist_ok=True)
                    cache_key = hashlib.sha256(json.dumps({'text': text, 'voice': local_voice, 'speed': speed, 'version': 1}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    cached = cache / (cache_key + '.wav')
                    if cached.is_file() and not force and not no_cache:
                        audio = cached.read_bytes()
                        self.send_response(200); self.send_header('Content-Type', 'audio/wav'); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio); return
                    with tempfile.TemporaryDirectory() as tmp:
                        output = Path(tmp) / 'speech.wav'
                        result = run_generation_process([str(base / '.piper-env/bin/python'), '-m', 'piper', '--model', str(base / 'voices' / ('ru_RU-' + local_voice + '-medium.onnx')), '--output_file', str(output), '--length-scale', str(round(1.2 / speed, 2)), '--sentence-silence', '0.45'], 120, repair_key, text)
                        if result.returncode: return self.send_error(502, 'Local speech generation failed')
                        audio = output.read_bytes()
                        if not no_cache:
                            temporary_cache = cached.with_suffix('.tmp')
                            temporary_cache.write_bytes(audio); os.replace(temporary_cache, cached)
                    self.send_response(200); self.send_header('Content-Type', 'audio/wav'); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio); return
                key = os.environ.get('OPENAI_API_KEY')
                if not key: return self.send_error(503, 'OPENAI_API_KEY is not configured')
                voice = data.get('voice', 'marin')
                if voice not in ('marin', 'cedar', 'coral', 'alloy', 'nova', 'shimmer'): return self.send_error(400)
                payload = json.dumps({'model': 'gpt-4o-mini-tts', 'voice': voice, 'input': text, 'instructions': 'Read naturally and expressively, preserving the language of the text.'}).encode()
                request = urllib.request.Request('https://api.openai.com/v1/audio/speech', data=payload, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=90) as response: audio = response.read()
                self.send_response(200); self.send_header('Content-Type', 'audio/mpeg'); self.send_header('Content-Length', str(len(audio))); self.end_headers(); self.wfile.write(audio)
            except subprocess.TimeoutExpired: self.send_error(504, 'Speech generation timed out')
            except (ValueError, OSError, TypeError, RuntimeError): self.send_error(502, 'Speech generation failed')
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
            target.write_text(data['content'], encoding='utf-8')
            self.send_json({'ok': True})
        except (ValueError, OSError, TypeError): self.send_error(400)
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/api/speech-latest':
            q = parse_qs(url.query); kind = q.get('kind', [''])[0]; path = q.get('path', [''])[0]
            if not valid_note_path(kind, path): return self.send_error(400)
            with JOBS_LOCK:
                candidates = [(key, job) for key, job in JOBS.items() if job['state'] == 'complete' and not job['cancelled'] and job['settings'].get('kind') == kind and job['settings'].get('path') == path]
                if not candidates: return self.send_json({'job': None})
                identifier, job = max(candidates, key=lambda item: item[1].get('completed_at') or '')
                return self.send_json({'job': {'id': identifier, 'total': len(job['chunks']), 'text': ' '.join(job['chunks']), 'settings': job['settings']}})
        if url.path == '/api/notes':
            try:
                q = parse_qs(url.query); kind = q.get('kind', [''])[0]; path = q.get('path', [''])[0]
                if not valid_note_path(kind, path): return self.send_error(400)
                with notes_db() as db:
                    rows = db.execute('SELECT id, body, quote, created FROM notes WHERE kind=? AND path=? ORDER BY created DESC', (kind, path)).fetchall()
                return self.send_json([dict(zip(('id', 'body', 'quote', 'created'), row)) for row in rows])
            except (OSError, sqlite3.Error): return self.send_error(500)
        if url.path in ('/api/speech-job', '/api/speech-part', '/api/speech-parts'):
            q = parse_qs(url.query); identifier = q.get('id', [''])[0]
            with JOBS_LOCK:
                job = JOBS.get(identifier)
                if job is None: return self.send_error(404)
                if url.path == '/api/speech-job': return self.send_json({'state': job['state'], 'ready': len(job['files']), 'total': len(job['chunks']), 'error': job['error']})
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
                        profiles.append({'id': item.name, 'name': (item / 'name.txt').read_text(encoding='utf-8')})
            return self.send_json(profiles)
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
                    if target.stat().st_size > 2_000_000: return self.send_error(413)
                    raw = target.read_bytes()
                    self.send_json({'directory': False, 'content': raw.decode('utf-8'), 'source_hash': hashlib.sha256(raw).hexdigest()})
            except (OSError, UnicodeError): self.send_error(415, 'Cannot display this file')
        elif url.path in ('/', '/project'):
            data = (Path(__file__).parent / 'index.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(data)
        else: self.send_error(404)
if __name__ == '__main__':
    print('Каталог: http://127.0.0.1:8765', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    restore_jobs(server.server_port)
    server.serve_forever()
