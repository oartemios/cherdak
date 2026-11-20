# Эксперимент с синтетическим голосом

Статус: прототип командной строки, не интегрирован в приложение; качество и производительность не оценены. Данные сцены — `experiments/synthetic_scene.json`, сценарий — `experiments/synthetic_voice.py`. Рабочее окружение и клонирование не изменены.

Установлены mlx-audio 0.6.5 и mlx 0.32.4. В установленной реализации есть `generate_voice_design(text, instruct, language, ...)` и `generate_custom_voice(text, speaker, language, instruct, ...)`. Ветка Base ICL использует аудио и текст образца, но не инструкцию об эмоции. `speed` не используется. Наличие методов не доказывает успешной загрузки конкретных весов или качества генерации. В репозитории не найден компонент Speech Plan; JSON сцены — самостоятельная экспериментальная структура, не интеграция с ним.

Пример после полной загрузки моделей, из корня проекта (запуск последовательно):

```sh
.clone-env/bin/python experiments/synthetic_voice.py reference --model models/qwen3-tts-1.7b-voicedesign --output artifacts/synthetic/reference
.clone-env/bin/python experiments/synthetic_voice.py design --model models/qwen3-tts-1.7b-voicedesign --output artifacts/synthetic/design
.clone-env/bin/python experiments/synthetic_voice.py custom --model models/qwen3-tts-1.7b-customvoice --output artifacts/synthetic/custom
.clone-env/bin/python experiments/synthetic_voice.py base --model models/qwen3-tts-0.6b --reference artifacts/synthetic/reference/00-calm.wav --output artifacts/synthetic/base
```

Каждый запуск сохраняет фрагменты и manifest со временем загрузки и генерации, длительностью и текстом. Файлы эталона и `reference_text` в JSON должны оставаться парой. Base использует этот синтетический эталон, а не запись человека. VoiceDesign повторно получает описание на каждом фрагменте; устойчивость тембра требует проверки на слух. CustomVoice использует встроенного говорящего. Одинаковый seed не гарантирует совпадение между моделями или версиями. Инструкции об эмоциях — запросы модели, а не гарантия выражения. Для Base инструкции не передаются.

Оценивать на слух вслепую естественность, тембр, эмоции, точность русского текста и переходы; отдельно замерить время, память и повторяемость на нескольких запусках. Скрипт пока не объединяет фрагменты и не измеряет качество стыков. Результатов сравнения с ChatGPT Voice нет.

## Первый запуск на машине

Все три модели загрузились и сгенерировали шесть фрагментов в `artifacts/synthetic/{design,custom,base}`; синтетический эталон — в `artifacts/synthetic/reference`. Один запуск, без субъективной оценки: суммарное время генерации шести фрагментов — VoiceDesign 27,21 с на 24,32 с аудио, CustomVoice 30,03 с на 25,04 с аудио, Base 26,20 с на 20,00 с аудио. Время загрузки соответственно 2,81, 2,77 и 2,45 с. Это не тест пиковой памяти и не оценка качества. Вначале документа статус отсутствия генерации относится к моменту подготовки прототипа.
