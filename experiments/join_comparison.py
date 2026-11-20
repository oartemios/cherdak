"""Create comparable PCM WAV examples from the same generated fragments."""
import argparse
from pathlib import Path
import wave
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('directory')
    args = p.parse_args()
    folder = Path(args.directory)
    fragments = []
    for name in ('length-50.wav', 'length-80.wav'):
        with wave.open(str(folder / name), 'rb') as f:
            if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, 24000):
                raise ValueError('Unexpected audio format')
            fragments.append(np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(np.float64) / 32768)
    def write(name, data):
        with wave.open(str(folder / name), 'wb') as f:
            f.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            f.writeframes(np.clip(data * 32768, -32768, 32767).astype('<i2').tobytes())
    write('join-original.wav', np.concatenate(fragments))
    normalized = []
    for fragment in fragments:
        peak = np.max(np.abs(fragment)); active = fragment[np.abs(fragment) >= .012]
        gain = min(2, .14 / np.sqrt(np.mean(active ** 2)), .95 / peak) if len(active) and peak else 1
        normalized.append(fragment * gain)
    write('join-legacy-normalized.wav', np.concatenate(normalized))
    faded = []
    for fragment in fragments:
        fragment = fragment.copy(); n = min(round(.008 * 24000), len(fragment) // 2)
        fragment[:n] *= np.linspace(0, 1, n); fragment[-n:] *= np.linspace(1, 0, n)
        faded.append(fragment)
    write('join-improved-100ms.wav', np.concatenate([faded[0], np.zeros(2400), faded[1]]))


if __name__ == '__main__':
    main()
