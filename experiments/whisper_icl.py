"""Reproducible, local-only Qwen ICL parameter experiment; does not alter app settings."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import mlx.core as mx
from mlx_audio.audio_io import write
from mlx_audio.tts.utils import load_model
from mlx_audio.utils import load_audio

ROOT = Path(__file__).resolve().parents[1]
TEXT = ('В здании встречаются головоломки и связанные с ними задания. '
        'Тихий голос рассказывает историю, пока за окном медленно темнеет. '
        'В конце коридора открывается дверь, и слышатся осторожные шаги.')


def prefix(limit):
    if len(TEXT) <= limit:
        return TEXT
    return TEXT[:limit + 1].rsplit(' ', 1)[0].rstrip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True, help='Existing profile ID')
    parser.add_argument('--output', required=True)
    parser.add_argument('--skip', action='append', default=[], help='Case to skip, e.g. after a timeout')
    args = parser.parse_args()
    if len(args.profile) != 32 or any(c not in '0123456789abcdef' for c in args.profile):
        parser.error('Invalid profile ID')
    sample = ROOT / '.voice-profiles' / args.profile / 'reference.wav'
    transcript = sample.with_name('transcript.txt').read_text(encoding='utf-8')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    model_path = ROOT / 'models/qwen3-tts-0.6b'
    model = load_model(str(model_path))
    if not model.speech_tokenizer.has_encoder:
        raise RuntimeError('ICL speech encoder is unavailable')
    reference = load_audio(str(sample), sample_rate=model.sample_rate, volume_normalize=False)
    cases = [(f'length-{n}', prefix(n), 0.9, 1.5) for n in (50, 80, 120, 180)]
    cases += [(f'temp-{t:.1f}-rep-{r:.2f}', prefix(120), t, r)
              for t in (0.7, 0.8, 0.9) for r in (1.05, 1.2, 1.5)]
    manifest = {'model': str(model_path), 'reference_id': args.profile,
                'reference_sha256': hashlib.sha256(sample.read_bytes()).hexdigest(),
                'transcript_sha256': hashlib.sha256(transcript.encode()).hexdigest(),
                'reference_transcription': 'user-confirmed', 'sample_rate': model.sample_rate,
                'seed': 42, 'top_k': 50, 'top_p': 1.0, 'max_tokens': 8192,
                'mode': 'ICL; direct _generate_icl: bypasses app/library 1.5 minimum', 'cases': []}
    manifest_file = out / 'manifest.json'
    if manifest_file.exists():
        previous = json.loads(manifest_file.read_text(encoding='utf-8'))
        if previous['reference_sha256'] != manifest['reference_sha256'] or previous['transcript_sha256'] != manifest['transcript_sha256']:
            raise RuntimeError('Reference changed; use a new output directory')
        manifest['cases'] = previous['cases']
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, text, temperature, repetition in cases:
        if name in args.skip or any(case['name'] == name for case in manifest['cases']):
            continue
        print(f'START {name}', flush=True)
        started = time.monotonic()
        mx.random.seed(42)
        results = list(model._generate_icl(text=text, ref_audio=reference, ref_text=transcript,
                       language='Russian', temperature=temperature, top_k=50, top_p=1.0,
                       repetition_penalty=repetition, max_tokens=8192, stream=False))
        if not results:
            raise RuntimeError(f'No audio: {name}')
        audio = mx.concatenate([result.audio for result in results], axis=0)
        write(out / (name + '.wav'), audio, model.sample_rate, format='wav')
        manifest['cases'].append({'name': name, 'text': text, 'length': len(text),
                                  'temperature': temperature, 'repetition_penalty': repetition,
                                  'seconds': round(time.monotonic() - started, 2),
                                  'audio_seconds': round(audio.shape[0] / model.sample_rate, 3)})
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'DONE {name}', flush=True)


if __name__ == '__main__':
    main()
