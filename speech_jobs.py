"""Persistent speech job state, queue and fragment regeneration."""
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import wave

from app_config import BASE, SETTINGS
from catalog_paths import valid_note_path as validate_note_path
from speech_text import prepare_speech_text, speech_resume_offset, split_speech
from speech_service import synthesize, SpeechRequestError

ROOTS = {'books': SETTINGS.books_root, 'games': SETTINGS.games_root}

def valid_note_path(kind, path):
    return validate_note_path(ROOTS, kind, path)

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
    if 'reference_text' in job:
        data['reference_text'] = job['reference_text']
    temp = folder / 'job.json.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, folder / 'job.json')

def restore_jobs():
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
            if data['state'] == 'queued' and not data['cancelled']: EXECUTOR.submit(run_speech_job, folder.name)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue

def document_revision(settings):
    kind, path = settings.get('kind'), settings.get('path')
    if not valid_note_path(kind, path): return None
    try: return hashlib.sha256((ROOTS[kind] / path).read_bytes()).hexdigest()
    except OSError: return None


def matching_speech_job(settings, text, fingerprint, revision):
    """Choose a job for the same document and voice under JOBS_LOCK."""
    voice_settings = {key: value for key, value in settings.items() if key != '_heading_pauses'}
    active_states = ('queued', 'generating', 'pausing')
    best = best_rank = None
    for identifier, job in JOBS.items():
        state = job['state']
        if job['cancelled'] or state not in (*active_states, 'complete', 'paused', 'error'):
            continue
        ready = len(job['files'])
        exact = job['fingerprint'] == fingerprint
        previous_revision = job.get('source_hash')
        if previous_revision != revision and not (exact and previous_revision is None):
            continue
        offset = None
        if not exact:
            previous_settings = {key: value for key, value in job['settings'].items() if key != '_heading_pauses'}
            if previous_settings != voice_settings:
                continue
            if ready and settings.get('_synthetic_pipeline') == 2 and not (JOB_STORAGE / identifier / 'synthetic-reference.wav').is_file():
                continue
            offset = speech_resume_offset(text, job['chunks'], ready)
            if offset is None:
                continue
        prepared_length = sum(map(len, job['chunks'][:ready]))
        rank = (state == 'complete', state in active_states, prepared_length, exact)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = identifier, job, offset
    return best

def speech_cache_key(job, text):
    settings = job['settings']; engine = settings.get('engine')
    text = prepare_speech_text(text)
    if engine == 'local':
        identity = {'text': text, 'voice': settings.get('local_voice', 'ruslan'), 'speed': settings.get('speed', 1.0), 'version': 1}
        if SETTINGS.voices_dir != (BASE / 'voices').absolute() or SETTINGS.piper_python != (BASE / '.piper-env/bin/python').absolute() or SETTINGS.piper_sentence_silence != 0.45:
            identity['voices_dir'] = str(SETTINGS.voices_dir); identity['piper_python'] = str(SETTINGS.piper_python); identity['sentence_silence'] = SETTINGS.piper_sentence_silence
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if engine == 'synthetic':
        identity = {'text': text, 'kind': settings.get('synthetic_kind', 'female'), 'age': settings.get('synthetic_age', 30), 'model': 'qwen3-tts-1.7b-voicedesign-8bit', 'version': 1}
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if engine in ('clone', 'f5'):
        identifier = settings.get('profile')
        if identifier == 'legacy': folder = BASE / '.voice-sample'
        elif isinstance(identifier, str) and re.fullmatch(r'[0-9a-f]{32}', identifier): folder = BASE / '.voice-profiles' / identifier
        else: return None
        try:
            model_identity = b'' if SETTINGS.qwen_tts_model == (BASE / 'models/qwen3-tts-0.6b').absolute() and SETTINGS.mlx_python == (BASE / '.clone-env/bin/python').absolute() else (str(SETTINGS.qwen_tts_model) + ':' + str(SETTINGS.mlx_python)).encode()
            version = b'qwen-v2-short-sentences'
            if engine == 'f5':
                version = b'f5-russian-accent-tune-ruaccent-v2'
                model_identity = str(SETTINGS.f5_python).encode()
            return hashlib.sha256(text.encode() + (folder / 'reference.wav').read_bytes() + (folder / 'transcript.txt').read_text(encoding='utf-8').encode() + version + model_identity).hexdigest()
        except OSError: return None
    return None

def cleanup_superseded(job_id):
    # Only promote output if its source file has not changed during generation.
    current = JOBS[job_id]; revision = current.get('source_hash')
    if not revision or document_revision(current['settings']) != revision: return
    settings = current['settings']; identity = tuple(settings.get(k) for k in ('kind', 'path', 'engine', 'profile', 'local_voice', 'speed', 'voice', 'synthetic_kind', 'synthetic_age'))
    old_jobs = [(key, job) for key, job in JOBS.items() if key != job_id and job['state'] in ('complete', 'error', 'paused') and not job['cancelled'] and tuple(job['settings'].get(k) for k in ('kind', 'path', 'engine', 'profile', 'local_voice', 'speed', 'voice', 'synthetic_kind', 'synthetic_age')) == identity and not any(x.get('state') in ('queued', 'generating', 'stopping') for x in job.get('repairs', {}).values())]
    if not old_jobs: return
    old_keys = {speech_cache_key(job, chunk) for _, job in old_jobs for chunk in job['chunks']}
    old_ids = {key for key, _ in old_jobs}
    keep_keys = {speech_cache_key(job, chunk) for key, job in JOBS.items() if key not in old_ids and not job['cancelled'] and job['state'] != 'superseded' and job['settings'].get('kind') == settings.get('kind') and job['settings'].get('path') == settings.get('path') for chunk in job['chunks']}
    for key, job in old_jobs:
        job['state'] = 'superseded'; files = list(job['files']); job['files'] = []; save_job(key, job)
        for file, _ in files:
            try: file.unlink(missing_ok=True)
            except OSError: pass
        try: (JOB_STORAGE / key / 'synthetic-reference.wav').unlink(missing_ok=True)
        except OSError: pass
    cache = Path(__file__).resolve().parent / '.speech-cache' / hashlib.sha256((settings['kind'] + ':' + settings['path']).encode()).hexdigest()
    for key in old_keys - keep_keys - {None}:
        try: (cache / (key + '.wav')).unlink(missing_ok=True)
        except OSError: pass

def synthetic_reference(job_id, job):
    """Return the immutable first-fragment reference for anchored jobs."""
    if (job['settings'].get('engine') != 'synthetic' or job['settings'].get('_synthetic_pipeline') != 2):
        return None
    sample = JOB_STORAGE / job_id / 'synthetic-reference.wav'
    if not sample.is_file() or not job['chunks']:
        raise RuntimeError('Synthetic voice reference is missing')
    return sample, job.get('reference_text', job['chunks'][0])


def run_speech_job(job_id):
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
        anchored = job['settings'].get('engine') == 'synthetic' and job['settings'].get('_synthetic_pipeline') == 2
        if anchored: payload['no_cache'] = True
        try:
            with GENERATION_LOCK:
                with JOBS_LOCK:
                    if job['cancelled']: job['state'] = 'cancelled'; return
                    if job['state'] in ('paused', 'pausing'):
                        job['state'] = 'paused'; save_job(job_id, job); return
                reference = synthetic_reference(job_id, job) if anchored and job['files'] else None
                audio, content_type = synthesize(payload, SETTINGS, BASE, ROOTS, speech_cache_key, run_generation_process, **({'synthetic_reference': reference} if anchored else {}))
                with JOBS_LOCK:
                    if job['cancelled']: job['state'] = 'cancelled'; return
                    folder = JOB_STORAGE / job_id
                    if anchored and not job['files']:
                        reference_file = folder / 'synthetic-reference.wav'
                        reference_temp = folder / 'synthetic-reference.tmp'
                        reference_temp.write_bytes(audio); os.replace(reference_temp, reference_file)
                        job['reference_text'] = prepare_speech_text(chunk)
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
        except SpeechRequestError as exc:
            with JOBS_LOCK:
                if job['cancelled']: job['state'] = 'cancelled'; return
                index = len(job['files']); failed = job['chunks'][index]
                attempts = retries.get(index, 0)
                if exc.status == 504 and len(failed) > 60 and attempts < 3:
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
                job['state'] = 'error'; job['error'] = str(exc) if exc.status == 422 else 'Не удалось создать аудиофрагмент. Проверьте настройки голоса и доступность модели.'; save_job(job_id, job)
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

def regenerate_part(job_id, index):
    with JOBS_LOCK:
        job = JOBS[job_id]; repair = job['repairs'][str(index)]
        if job['cancelled'] or repair['state'] != 'queued': repair['state'] = 'cancelled'; save_job(job_id, job); return
        repair['state'] = 'generating'; save_job(job_id, job)
        pronunciation = repair.get('pronunciation', job['chunks'][index])
        payload = dict(job['settings'], text=pronunciation, force=True, repair_job=job_id, repair_index=index)
        if pronunciation != job['chunks'][index]:
            payload['no_cache'] = True
        anchored = job['settings'].get('engine') == 'synthetic' and job['settings'].get('_synthetic_pipeline') == 2
        if anchored: payload['no_cache'] = True
    try:
        with GENERATION_LOCK:
            with JOBS_LOCK:
                if job['cancelled'] or repair['state'] != 'generating': repair['state'] = 'cancelled'; save_job(job_id, job); return
            def generate_piece(text, depth=0):
                request_data = dict(payload, text=text)
                try:
                    return synthesize(request_data, SETTINGS, BASE, ROOTS, speech_cache_key, run_generation_process, **({'synthetic_reference': synthetic_reference(job_id, job)} if anchored else {}))
                except SpeechRequestError as exc:
                    if exc.status != 504 or payload.get('engine') not in ('clone', 'synthetic', 'f5') or depth >= 3 or len(text) <= 60: raise
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
