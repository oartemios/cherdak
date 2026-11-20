"""Run Russian F5-TTS and RUAccent in the optional F5 environment."""
import json
import re
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
    from ruaccent import RUAccent

    request = json.load(sys.stdin)
    accentizer = RUAccent()
    accentizer.load(omograph_model_size='turbo3.1', use_dictionary=True, tiny_mode=False)
    model = F5TTS(
        model='F5TTS_v1_Base',
        ckpt_file=hf_hub_download(MODEL_REPO, CHECKPOINT),
        vocab_file=hf_hub_download(MODEL_REPO, VOCABULARY),
    )
    model.infer(
        ref_file=request['sample'],
        ref_text=accent_text(accentizer, request['transcript']),
        gen_text=accent_text(accentizer, request['text']),
        file_wave=request['output'],
    )


if __name__ == '__main__':
    main()
