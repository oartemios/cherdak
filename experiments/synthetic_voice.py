"""Isolated CLI experiment: run one model per process to limit peak memory."""
import argparse
import json
import time
from pathlib import Path

EMOTIONS = {
    'calm': 'Speak calmly and naturally.',
    'joy': 'Speak with genuine joy and excitement.',
    'fear': 'Speak with fear and apprehension.',
    'anger': 'Speak angrily, with restrained intensity.',
    'sarcasm': 'Speak with dry, unmistakable sarcasm.',
    'whisper': 'Whisper softly.',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['reference', 'design', 'custom', 'base'])
    p.add_argument('--model', required=True)
    p.add_argument('--plan', default='experiments/synthetic_scene.json')
    p.add_argument('--output', required=True)
    p.add_argument('--reference', help='Synthetic reference WAV, required for base')
    p.add_argument('--speaker', default='Ryan')
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    if any(s['emotion'] not in EMOTIONS or not s['text'].strip() for s in plan['segments']):
        p.error('Invalid scene segment')
    if args.mode == 'base' and not args.reference:
        p.error('base requires --reference')
    import mlx.core as mx
    from mlx_audio.audio_io import write
    from mlx_audio.tts.utils import load_model
    from mlx_audio.utils import load_audio
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    model = load_model(args.model)
    load_seconds = time.monotonic() - started
    expected = {'reference': 'voice_design', 'design': 'voice_design', 'custom': 'custom_voice', 'base': 'base'}[args.mode]
    if model.config.tts_model_type != expected:
        raise ValueError(f'Expected {expected} model')
    reference = load_audio(args.reference, sample_rate=model.sample_rate, volume_normalize=False) if args.reference else None
    segments = [{'text': plan['reference_text'], 'emotion': 'calm'}] if args.mode == 'reference' else plan['segments']
    manifest = {'mode': args.mode, 'model': args.model, 'seed': args.seed, 'load_seconds': load_seconds, 'segments': []}
    for i, segment in enumerate(segments):
        mx.random.seed(args.seed + i)
        start = time.monotonic()
        common = dict(text=segment['text'], language='Russian')
        instruction = EMOTIONS[segment['emotion']]
        if args.mode in ('reference', 'design'):
            result = model.generate_voice_design(**common, instruct=plan['voice_description'] + ' ' + instruction)
        elif args.mode == 'custom':
            result = model.generate_custom_voice(**common, speaker=args.speaker, instruct=instruction)
        else:
            result = model.generate(text=segment['text'], lang_code='Russian', ref_audio=reference, ref_text=plan['reference_text'])
        chunks = [x.audio for x in result]
        if not chunks:
            raise RuntimeError('Model returned no audio')
        audio = mx.concatenate(chunks, axis=0)
        filename = f'{i:02d}-{segment["emotion"]}.wav'
        write(out / filename, audio, model.sample_rate, format='wav')
        manifest['segments'].append({**segment, 'file': filename, 'seconds': time.monotonic() - start, 'audio_seconds': len(audio) / model.sample_rate})
        (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(filename, flush=True)

if __name__ == '__main__':
    main()
