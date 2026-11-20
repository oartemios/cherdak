"""Transcribe locally generated comparisons; ASR differences are not ground truth."""
import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re

from mlx_audio.stt.utils import load


def words(text):
    return re.findall(r'[^\W_]+', text.lower(), flags=re.UNICODE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    directory = Path(args.directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    model = load(args.model)
    results = []
    for case in manifest['cases']:
        result = model.generate(str(directory / (case['name'] + '.wav')), language='Russian')
        actual = result.text.strip()
        expected = words(case['text'])
        observed = words(actual)
        missing = [word for tag, i, j, _, _ in SequenceMatcher(None, expected, observed).get_opcodes()
                   if tag in ('delete', 'replace') for word in expected[i:j]]
        results.append({'name': case['name'], 'expected': case['text'], 'asr': actual,
                        'possibly_missing_or_misrecognized': missing})
        (directory / 'asr-comparison.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(case['name'], 'possible differences:', len(missing), flush=True)


if __name__ == '__main__':
    main()
