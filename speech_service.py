"""Audio generation and cache policy shared by HTTP and background jobs."""
import os
from pathlib import Path
import re
import subprocess

from speech_engines import generate_f5, generate_openai, generate_piper, generate_qwen, generate_voice_design


class SpeechRequestError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def synthesize(data, settings, base, roots, cache_key, runner, synthetic_reference=None):
    text = data.get('text', '')
    force, no_cache = data.get('force', False), data.get('no_cache', False)
    if not isinstance(force, bool) or not isinstance(no_cache, bool):
        raise SpeechRequestError(400, 'Invalid cache options')
    if not isinstance(text, str) or not 0 < len(text) <= 2000:
        raise SpeechRequestError(400, 'Invalid text')
    repair_job, repair_index = data.get('repair_job'), data.get('repair_index')
    repair_key = None
    if repair_job is not None or repair_index is not None:
        if not force or not isinstance(repair_job, str) or type(repair_index) is not int:
            raise SpeechRequestError(400, 'Invalid repair')
        repair_key = (repair_job, repair_index)
    engine = data.get('engine')
    if engine not in ('clone', 'local', 'openai', 'synthetic', 'f5'):
        raise SpeechRequestError(400, 'Invalid engine')
    if engine == 'openai':
        key = os.environ.get('OPENAI_API_KEY')
        if not key:
            raise SpeechRequestError(503, 'OPENAI_API_KEY is not configured')
        voice = data.get('voice', 'marin')
        if voice not in ('marin', 'cedar', 'coral', 'alloy', 'nova', 'shimmer'):
            raise SpeechRequestError(400, 'Invalid voice')
        try:
            return generate_openai(settings, text, voice, key), 'audio/mpeg'
        except (OSError, ValueError, RuntimeError) as exc:
            raise SpeechRequestError(502, 'Speech generation failed') from exc

    kind, path = data.get('kind'), data.get('path')
    if kind not in roots or not isinstance(path, str) or not path:
        raise SpeechRequestError(400, 'Invalid project')
    if engine in ('clone', 'f5'):
        voice_id = data.get('profile', '')
        if voice_id == 'legacy':
            folder = base / '.voice-sample'
        elif isinstance(voice_id, str) and re.fullmatch(r'[0-9a-f]{32}', voice_id):
            folder = base / '.voice-profiles' / voice_id
        else:
            raise SpeechRequestError(400, 'Invalid voice')
        sample, transcript = folder / 'reference.wav', folder / 'transcript.txt'
        if not sample.is_file() or not transcript.is_file():
            raise SpeechRequestError(400, 'Voice sample is missing')
    elif engine == 'synthetic':
        from synthetic_voice import voice_description
        try:
            description = voice_description(data.get('synthetic_kind', 'female'), data.get('synthetic_age', 30))
        except ValueError as exc:
            raise SpeechRequestError(400, str(exc)) from exc
    else:
        voice = data.get('local_voice', 'ruslan')
        speed = data.get('speed', 1.0)
        if voice not in ('ruslan', 'irina', 'dmitri'):
            raise SpeechRequestError(400, 'Invalid voice')
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.7 <= speed <= 1.3:
            raise SpeechRequestError(400, 'Invalid speed')
    try:
        # Preview audio is kept in memory and does not create cache directories.
        cached = None
        if not no_cache:
            import hashlib
            cache = base / '.speech-cache' / hashlib.sha256((kind + ':' + path).encode()).hexdigest()
            cache.mkdir(parents=True, exist_ok=True)
            key = cache_key({'settings': data}, text)
            if key is None:
                raise SpeechRequestError(400, 'Cannot construct cache key')
            cached = cache / (key + '.wav')
            if cached.is_file() and not force:
                return cached.read_bytes(), 'audio/wav'
        if engine in ('clone', 'f5'):
            generate = generate_f5 if engine == 'f5' else generate_qwen
            audio = generate(settings, text, sample, transcript.read_text(encoding='utf-8'), runner, repair_key)
        elif engine == 'synthetic':
            if synthetic_reference is None:
                audio = generate_voice_design(settings, text, description, runner, repair_key)
            else:
                sample, transcript_text = synthetic_reference
                audio = generate_qwen(settings, text, sample, transcript_text, runner, repair_key)
        else:
            audio = generate_piper(settings, text, voice, speed, runner, repair_key)
        if cached is not None:
            temporary = cached.with_suffix('.tmp')
            temporary.write_bytes(audio)
            os.replace(temporary, cached)
        return audio, 'audio/wav'
    except SpeechRequestError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise SpeechRequestError(504, 'Speech generation timed out') from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise SpeechRequestError(502, 'Speech generation failed') from exc
