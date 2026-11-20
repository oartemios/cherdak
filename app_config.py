"""Local configuration for the project catalogue (no third-party dependencies)."""
from dataclasses import dataclass
from pathlib import Path
import json
import os

BASE = Path(__file__).resolve().parent

@dataclass(frozen=True)
class Settings:
    books_root: Path
    games_root: Path
    voices_dir: Path
    qwen_tts_model: Path
    qwen_asr_model: Path
    piper_python: Path
    mlx_python: Path
    port: int
    qwen_timeout: int
    piper_timeout: int
    asr_timeout: int
    piper_sentence_silence: float
    openai_model: str


def default_values():
    return {
        'books_root': '~/Documents/stories/books',
        'games_root': '~/Development/games',
        'voices_dir': 'voices',
        'qwen_tts_model': 'models/qwen3-tts-0.6b',
        'qwen_asr_model': '~/.cache/lm-studio/models/mlx-community/Qwen3-ASR-0.6B-8bit',
        'piper_python': '.piper-env/bin/python',
        'mlx_python': '.clone-env/bin/python',
        'port': 8765,
        'qwen_timeout': 150,
        'piper_timeout': 120,
        'asr_timeout': 300,
        'piper_sentence_silence': 0.45,
        'openai_model': 'gpt-4o-mini-tts',
    }


def load_settings(path=None):
    file = Path(path) if path is not None else BASE / 'config.local.json'
    try:
        values = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Cannot read configuration {file}: {exc}') from exc
    return validate_settings(values)


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError('Configuration must be a JSON object')
    defaults = default_values()
    unknown = set(values) - set(defaults)
    if unknown:
        raise ValueError('Unknown configuration keys: ' + ', '.join(sorted(unknown)))
    data = defaults | values
    for key in ('books_root', 'games_root', 'voices_dir', 'qwen_tts_model', 'qwen_asr_model', 'piper_python', 'mlx_python'):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f'{key} must be a non-empty path')
        candidate = Path(os.path.expanduser(data[key]))
        data[key] = Path(os.path.abspath(candidate if candidate.is_absolute() else BASE / candidate))
    for key in ('port', 'qwen_timeout', 'piper_timeout', 'asr_timeout'):
        if type(data[key]) is not int or data[key] <= 0 or (key == 'port' and data[key] > 65535):
            raise ValueError(f'{key} must be a positive integer' + (' up to 65535' if key == 'port' else ''))
    if isinstance(data['piper_sentence_silence'], bool) or not isinstance(data['piper_sentence_silence'], (float, int)) or not 0 <= data['piper_sentence_silence'] <= 10:
        raise ValueError('piper_sentence_silence must be between 0 and 10 seconds')
    if not isinstance(data['openai_model'], str) or not data['openai_model'].strip():
        raise ValueError('openai_model must be a non-empty string')
    return Settings(**data)


# A single immutable configuration shared by the HTTP server and job service.
SETTINGS = load_settings()
