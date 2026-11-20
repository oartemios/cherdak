# Эксперименты с озвучкой

На Mac M1 с 16 ГБ проверены Qwen3-TTS VoiceDesign и CustomVoice 1.7B 8-bit и Base 0.6B 8-bit через mlx-audio 0.6.5 и MLX 0.32.4. В приложении VoiceDesign генерирует первый фрагмент, а Base использует его как голосовой образец для остальных. Экспериментальный сценарий отдельно сравнивает прямую генерацию VoiceDesign, голос CustomVoice и Base с синтетическим эталоном.

| Модель | Генерация шести реплик | Аудио |
|---|---:|---:|
| VoiceDesign | 27,21 с | 24,32 с |
| CustomVoice | 30,03 с | 25,04 с |
| Base | 26,20 с | 20,00 с |

VoiceDesign обработала 1000 русских слов в 20 фрагментах за 12 мин 43 с без учёта загрузки и создала 8 мин 57 с аудио. Это один запуск на повторяющемся тексте. Пиковая память и точность произношения в этом замере не оценивались. Сравнения качества с ChatGPT Voice не проводилось.

## Шёпот и стыки

Base в режиме ICL использует аудио и расшифровку эталона. Метки манеры в профиле служат для выбора образца. Текстовые инструкции об эмоциях принимает VoiceDesign и CustomVoice. Сохранение шёпота и тембра требует проверки на слух.

Установленная версия MLX Audio ограничивает эффективный штраф повторения снизу значением 1,5. Скрипт эксперимента тестирует меньшие значения прямым вызовом ICL. Один прогон при temperature 0,8 и penalty 1,05 превысил 150 с. Измерения не выявили надёжных настроек для шёпота. Расхождения локального ASR могут быть ошибками распознавания. Режим «Плавные стыки» применяет затухание до 8 мс без нормализации отдельных фрагментов.

## Как повторить

Запускайте команды из корня проекта с локальными весами и установленным окружением MLX. Сценарии и исходные тексты находятся в [experiments](../experiments/). Журналы и WAV сохраняются локально в исключённой из Git папке `artifacts/`.

```sh
.clone-env/bin/python experiments/synthetic_voice.py reference --model models/qwen3-tts-1.7b-voicedesign --output artifacts/synthetic/reference
.clone-env/bin/python experiments/synthetic_voice.py design --model models/qwen3-tts-1.7b-voicedesign --output artifacts/synthetic/design
.clone-env/bin/python experiments/synthetic_voice.py custom --model models/qwen3-tts-1.7b-customvoice --output artifacts/synthetic/custom
.clone-env/bin/python experiments/synthetic_voice.py base --model models/qwen3-tts-0.6b --reference artifacts/synthetic/reference/00-calm.wav --output artifacts/synthetic/base
```

Для замера 1000 слов:

```sh
.clone-env/bin/python experiments/synthetic_voice.py design --model models/qwen3-tts-1.7b-voicedesign --plan experiments/speed_1000_words.json --output artifacts/synthetic/speed-1000
```

Для проверки шёпота подставьте ID локального профиля с шепчущим образцом. Для сравнения стыков скрипту нужны `length-50.wav` и `length-80.wav` из этого прогона.

```sh
.clone-env/bin/python experiments/whisper_icl.py --profile PROFILE_ID --output artifacts/whisper-icl-experiment
.clone-env/bin/python experiments/join_comparison.py artifacts/whisper-icl-experiment
```
