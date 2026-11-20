"""Run Russian F5-TTS and RUAccent in the optional F5 environment."""
import json
import re
import secrets
import sys

MODEL_REPO = 'Misha24-10/F5-TTS_RUSSIAN'
CHECKPOINT = 'F5TTS_v1_Base_accent_tune/model_last_inference.safetensors'
VOCABULARY = 'F5TTS_v1_Base/vocab.txt'
MARKED_WORD = r'[А-Яа-яЁё]*(?:\+[аеёиоуыэюяАЕЁИОУЫЭЮЯ][А-Яа-яЁё]*)+'


def accent_text(accentizer, text):
    text = re.sub(r'([аеёиоуыэюяАЕЁИОУЫЭЮЯ])\u0301', r'+\1', text)
    return accentizer.process_all(text, skip_regex=MARKED_WORD)


def main():
    from f5_tts.api import F5TTS
    from huggingface_hub import hf_hub_download
    import numpy as np
    from ruaccent import RUAccent

    request = json.load(sys.stdin)
    accentizer = RUAccent()
    accentizer.load(omograph_model_size='turbo3.1', use_dictionary=True, tiny_mode=False)
    # The character tokenizer may omit the segment IDs required by RUAccent's ONNX model.
    accent_model = accentizer.accent_model
    inputs = accent_model.tokenizer.model_input_names
    if 'token_type_ids' not in inputs and any(item.name == 'token_type_ids' for item in accent_model.session.get_inputs()):
        accent_model.tokenizer.model_input_names = [*inputs, 'token_type_ids']
    model = F5TTS(
        model='F5TTS_v1_Base',
        ckpt_file=hf_hub_download(MODEL_REPO, CHECKPOINT),
        vocab_file=hf_hub_download(MODEL_REPO, VOCABULARY),
    )
    text = accent_text(accentizer, request['text']).strip()
    if text and text[-1].isalnum():
        text += '.'
    audio, _, _ = model.infer(
        ref_file=request['sample'],
        ref_text=accent_text(accentizer, request['transcript']),
        gen_text=text,
        file_wave=request['output'],
        # F5-TTS also uses this seed as PYTHONHASHSEED for child processes.
        seed=secrets.randbits(32),
    )
    if audio is None or not audio.size or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.001:
        raise RuntimeError('F5-TTS produced silent or invalid audio')


if __name__ == '__main__':
    main()
