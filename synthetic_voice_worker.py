"""One isolated VoiceDesign generation, invoked by the application."""
import json
import sys
from pathlib import Path

import mlx.core as mx
from mlx_audio.audio_io import write
from mlx_audio.tts.utils import load_model

request = json.load(sys.stdin)
model = load_model(request['model'])
if model.config.tts_model_type != 'voice_design':
    raise ValueError('Expected a VoiceDesign model')
mx.random.seed(42)
chunks = [result.audio for result in model.generate_voice_design(
    text=request['text'], instruct=request['description'], language='Russian')]
if not chunks:
    raise RuntimeError('VoiceDesign returned no audio')
write(Path(request['output']), mx.concatenate(chunks, axis=0), model.sample_rate, format='wav')
