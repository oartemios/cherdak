const form = document.querySelector('#settings-form');
const save = document.querySelector('#save-settings');
const message = document.querySelector('#server-message');
const browserStatus = document.querySelector('#ui-status');
const keyStatus = document.querySelector('#openai-key-status');
const voice = document.querySelector('#ui-voice');
const fields = [
  'books_root', 'games_root', 'voices_dir', 'qwen_tts_model', 'qwen_asr_model',
  'piper_python', 'mlx_python', 'port', 'qwen_timeout', 'piper_timeout',
  'asr_timeout', 'piper_sentence_silence', 'openai_model',
];
const numericFields = new Set(['port', 'qwen_timeout', 'piper_timeout', 'asr_timeout', 'piper_sentence_silence']);
let revision = null;
let generationActive = false;

function showMessage(text, error = false) {
  message.textContent = text;
  message.classList.toggle('error', error);
  message.hidden = !text;
}

function applyTheme() {
  document.body.classList.toggle('light', localStorage.getItem('projectTheme') === 'light');
}

const browserSettings = [
  ['ui-theme', 'projectTheme', 'dark'],
  ['ui-view', 'projectView', 'cards'],
  ['ui-group', 'projectGrouping', 'none'],
  ['ui-sidebar', 'sidebarTool', 'outline'],
  ['ui-sentences', 'speechSentences', '1'],
  ['ui-speed', 'speechSpeed', '1'],
];
for (const [id, key, fallback] of browserSettings) {
  const control = document.getElementById(id);
  let value = localStorage.getItem(key) || fallback;
  if (id === 'ui-speed') value = String(Number(value));
  if (id === 'ui-view' && value === 'groups') value = 'cards';
  control.value = [...control.options].some(option => option.value === value) ? value : fallback;
  control.addEventListener('change', () => {
    localStorage.setItem(key, control.value);
    if (id === 'ui-theme') applyTheme();
    browserStatus.textContent = 'Настройка сохранена в этом браузере.';
  });
}
applyTheme();

function setVoiceChoice() {
  const selected = localStorage.getItem('selectedVoice') || 'local:ruslan';
  if (![...voice.options].some(option => option.value === selected)) {
    const missing = document.createElement('option');
    missing.value = selected;
    missing.textContent = 'Сохранённый голос недоступен';
    document.querySelector('#ui-custom-voices').append(missing);
  }
  voice.value = selected;
}
voice.addEventListener('change', () => {
  localStorage.setItem('selectedVoice', voice.value);
  browserStatus.textContent = 'Настройка сохранена в этом браузере.';
});
async function loadVoices() {
  try {
    const response = await fetch('/api/voices');
    if (!response.ok) throw new Error();
    const voices = await response.json();
    const group = document.querySelector('#ui-custom-voices');
    group.replaceChildren();
    for (const item of voices) {
      const option = document.createElement('option');
      option.value = 'clone:' + item.id;
      const labels = {joy:'радость', anxiety:'тревога', anger:'раздражение', whisper:'шёпот'};
      option.textContent = item.name + (labels[item.emotion] ? ' · ' + labels[item.emotion] : '');
      group.append(option);
    }
  } catch {
    browserStatus.textContent = 'Не удалось загрузить собственные голоса.';
  }
  setVoiceChoice();
}
loadVoices();

function renderPathChecks(data) {
  if (!data.path_checks) return;
  const labels = {books_root:'книги', games_root:'игры', voices_dir:'голоса Piper', qwen_tts_model:'Qwen TTS', qwen_asr_model:'Qwen ASR', piper_python:'Python Piper', mlx_python:'Python MLX'};
  const missing = Object.entries(data.path_checks).filter(([, found]) => !found).map(([key]) => labels[key] || key);
  const target = document.querySelector('#path-status');
  target.hidden = missing.length === 0;
  target.textContent = missing.length ? 'Не найдены сохранённые пути: ' + missing.join(', ') + '. Проверьте их перед перезапуском.' : '';
}

function renderPending(data, saved = false) {
  renderPathChecks(data);
  if (typeof data.generation_active === 'boolean') generationActive = data.generation_active;
  if (data.restart_required) {
    const busy = generationActive ? ' Сейчас есть активная генерация — дождитесь её завершения перед перезапуском.' : '';
    const configuredPort = String(data.values.port);
    const currentPort = location.port || (location.protocol === 'https:' ? '443' : '80');
    const nextUrl = configuredPort !== currentPort ? ' После перезапуска откройте http://127.0.0.1:' + configuredPort + '.' : '';
    showMessage('Настройки сохранены и вступят в силу после перезапуска сервера.' + busy + nextUrl);
  } else if (saved) {
    showMessage('Настройки сохранены. Они совпадают с текущими настройками сервера.');
  } else {
    showMessage('');
  }
}

async function loadSettings() {
  try {
    const response = await fetch('/api/settings');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось загрузить настройки.');
    revision = data.revision;
    generationActive = Boolean(data.generation_active);
    for (const name of fields) document.getElementById(name).value = String(data.values[name]);
    keyStatus.textContent = data.openai_key_configured
      ? 'Ключ API обнаружен в окружении сервера; его значение здесь не отображается.'
      : 'Ключ API не обнаружен. Для OpenAI задайте OPENAI_API_KEY перед запуском.';
    save.disabled = false;
    renderPending(data);
  } catch (error) {
    showMessage(error.message || 'Не удалось загрузить настройки.', true);
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!form.reportValidity() || revision === null) return;
  const values = {};
  for (const name of fields) {
    const raw = document.getElementById(name).value.trim();
    values[name] = numericFields.has(name) ? Number(raw) : raw;
  }
  save.disabled = true;
  showMessage('Сохранение…');
  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({values, revision}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Не удалось сохранить настройки.');
    revision = result.revision;
    renderPending(result, true);
  } catch (error) {
    showMessage(error.message || 'Не удалось сохранить настройки.', true);
  } finally {
    save.disabled = false;
  }
});
loadSettings();
