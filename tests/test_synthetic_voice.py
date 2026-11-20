import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_config import SETTINGS
from speech_jobs import speech_cache_key
from speech_service import SpeechRequestError, synthesize
from speech_text import split_speech
from synthetic_voice import voice_description


class SyntheticVoiceTests(unittest.TestCase):
    def test_validation_and_description(self):
        self.assertIn('woman', voice_description('female', 30))
        self.assertIn('man', voice_description('male', 70))
        self.assertIn('child', voice_description('child', 10))
        for kind, age in [('child', 18), ('male', 10), ('female', True), ('other', 30)]:
            with self.assertRaises(ValueError):
                voice_description(kind, age)

    def test_cache_separates_voice_choices(self):
        def key(kind, age):
            return speech_cache_key({'settings': {'engine': 'synthetic', 'synthetic_kind': kind, 'synthetic_age': age}}, 'Привет')
        self.assertEqual(len({key('female', 30), key('male', 30), key('female', 40), key('child', 10)}), 4)

    def test_synthesis_dispatch_and_validation(self):
        data = {'engine': 'synthetic', 'kind': 'books', 'path': 'chapter.md', 'text': 'Привет', 'synthetic_kind': 'child', 'synthetic_age': 10, 'no_cache': True}
        with tempfile.TemporaryDirectory() as root, patch('speech_service.generate_voice_design', return_value=b'wave') as generate:
            audio, content_type = synthesize(data, SETTINGS, Path(root), {'books': Path(root)}, speech_cache_key, None)
            self.assertEqual((audio, content_type), (b'wave', 'audio/wav'))
            self.assertIn('child', generate.call_args.args[2])
            with self.assertRaises(SpeechRequestError):
                synthesize(dict(data, synthetic_age=30), SETTINGS, Path(root), {'books': Path(root)}, speech_cache_key, None)
        self.assertEqual(split_speech('Первое предложение. Второе предложение.', 'synthetic', 1), ['Первое предложение.', 'Второе предложение.'])

if __name__ == '__main__':
    unittest.main()

class AnchoredJobTests(unittest.TestCase):
    def test_first_fragment_is_immutable_reference_for_following_and_repair(self):
        import speech_jobs as jobs
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ident = 'a' * 32
            job = {'fingerprint': 'test', 'settings': {'engine': 'synthetic', '_synthetic_pipeline': 2},
                   'chunks': ['Первый фрагмент.', 'Второй фрагмент.'], 'files': [], 'state': 'queued',
                   'error': '', 'cancelled': False, 'repairs': {}}
            calls = []
            def generate(payload, *args, **kwargs):
                reference = kwargs.get('synthetic_reference')
                calls.append((payload['text'], reference, payload.get('no_cache')))
                if reference:
                    self.assertEqual(reference[0].read_bytes(), b'first audio')
                    self.assertEqual(reference[1], 'Первый фрагмент.')
                return (b'first audio' if reference is None else b'following audio'), 'audio/wav'
            with patch.object(jobs, 'JOB_STORAGE', root), patch.object(jobs, 'JOBS', {ident: job}), patch.object(jobs, 'synthesize', side_effect=generate):
                jobs.run_speech_job(ident)
                self.assertEqual(job['state'], 'complete')
                self.assertIsNone(calls[0][1])
                self.assertIsNotNone(calls[1][1])
                self.assertTrue(all(x[2] for x in calls))
                job['repairs']['0'] = {'state': 'queued'}
                jobs.regenerate_part(ident, 0)
                self.assertEqual(job['repairs']['0']['state'], 'complete')
                self.assertIsNotNone(calls[2][1])
                self.assertEqual((root / ident / 'synthetic-reference.wav').read_bytes(), b'first audio')
                self.assertEqual(job['files'][0][0].read_bytes(), b'following audio')

    def test_missing_reference_fails_closed(self):
        import speech_jobs as jobs
        with tempfile.TemporaryDirectory() as tmp, patch.object(jobs, 'JOB_STORAGE', Path(tmp)):
            with self.assertRaises(RuntimeError):
                jobs.synthetic_reference('a' * 32, {'settings': {'engine': 'synthetic', '_synthetic_pipeline': 2}, 'chunks': ['текст']})
