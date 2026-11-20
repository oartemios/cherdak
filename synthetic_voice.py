"""VoiceDesign request validation and instruction construction."""
VOICE_MODEL = 'models/qwen3-tts-1.7b-voicedesign'


def voice_description(kind, age):
    if kind not in ('female', 'male', 'child') or type(age) is not int or not 5 <= age <= 100:
        raise ValueError('Invalid synthetic voice settings')
    if kind == 'child' and age > 17:
        raise ValueError('Child voice age must be between 5 and 17')
    if kind != 'child' and age < 18:
        raise ValueError('Adult voice age must be between 18 and 100')
    person = {'female': 'woman', 'male': 'man', 'child': 'child'}[kind]
    return (f'A Russian speaking {person}, approximately {age} years old, warm mid-range voice, '
            'clear diction and natural conversational delivery. Speak calmly and naturally.')
