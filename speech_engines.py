"""Adapters for speech engines. Storage and queueing live elsewhere."""
from pathlib import Path
import json
import tempfile
import urllib.request


class SpeechEngineError(RuntimeError):
    pass


def generate_qwen(settings, text, sample, transcript, runner, repair_key=None):
    with tempfile.TemporaryDirectory() as folder:
        command = [str(settings.mlx_python), '-m', 'mlx_audio.tts.generate', '--model', str(settings.qwen_tts_model), '--text', text, '--ref_audio', str(sample), '--ref_text', transcript, '--lang_code', 'Russian', '--output_path', folder, '--file_prefix', 'speech', '--join_audio']
        result = runner(command, settings.qwen_timeout, repair_key)
        outputs = list(Path(folder).glob('speech*.wav'))
        if result.returncode or len(outputs) != 1:
            raise SpeechEngineError('Qwen did not produce audio')
        return outputs[0].read_bytes()


def generate_voice_design(settings, text, description, runner, repair_key=None):
    from synthetic_voice import VOICE_MODEL
    model = Path(__file__).resolve().parent / VOICE_MODEL
    if not (model / 'model.safetensors').is_file():
        raise SpeechEngineError('VoiceDesign model is missing')
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / 'speech.wav'
        request = json.dumps({'model': str(model), 'text': text, 'description': description, 'output': str(output)}, ensure_ascii=False)
        command = [str(settings.mlx_python), str(Path(__file__).with_name('synthetic_voice_worker.py'))]
        result = runner(command, settings.qwen_timeout, repair_key, request)
        if result.returncode or not output.is_file():
            raise SpeechEngineError('VoiceDesign did not produce audio')
        return output.read_bytes()


def generate_piper(settings, text, voice, speed, runner, repair_key=None):
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / 'speech.wav'
        command = [str(settings.piper_python), '-m', 'piper', '--model', str(settings.voices_dir / ('ru_RU-' + voice + '-medium.onnx')), '--output_file', str(output), '--length-scale', str(round(1.2 / speed, 2)), '--sentence-silence', str(settings.piper_sentence_silence)]
        result = runner(command, settings.piper_timeout, repair_key, text)
        if result.returncode or not output.is_file():
            raise SpeechEngineError('Piper did not produce audio')
        return output.read_bytes()


def generate_openai(settings, text, voice, key):
    payload = json.dumps({'model': settings.openai_model, 'voice': voice, 'input': text, 'instructions': 'Read naturally and expressively, preserving the language of the text.'}).encode()
    request = urllib.request.Request('https://api.openai.com/v1/audio/speech', data=payload, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()
