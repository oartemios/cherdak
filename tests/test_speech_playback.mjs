import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const source = await readFile(new URL('../web/speech.js', import.meta.url), 'utf8');
const {speechTimeline, findSpeechPosition, scheduleSpeechBuffer} =
  await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

const timeline = speechTimeline([2, 3, null, 4], 0.25, [0]);
assert.deepEqual(timeline, [{start: 0, end: 2}, {start: 2.8, end: 5.8}]);
assert.deepEqual(findSpeechPosition(timeline, 0), {index: 0, offset: 0});
assert.deepEqual(findSpeechPosition(timeline, 2.5), {index: 1, offset: 0});
assert.deepEqual(findSpeechPosition(timeline, 3.8), {index: 1, offset: 1});
const end = findSpeechPosition(timeline, 5.8);
assert.equal(end.index, 1);
assert.ok(end.offset < 3 && end.offset > 2.99);

function run(mode, offset) {
  const events = [];
  const ctx = {
    destination: {},
    createBufferSource() { return {connect() {}, start(t, from) { events.push(['start', t, from]); }}; },
    createGain() { return {connect() {}, gain: {
      setValueAtTime(v, t) { events.push(['set', v, t]); },
      linearRampToValueAtTime(v, t) { events.push(['ramp', v, t]); },
    }}; },
  };
  const result = scheduleSpeechBuffer(ctx, {duration: 2}, 3, offset, mode);
  return {result, events};
}

const improved = run('improved', 1.25);
assert.equal(improved.result.end, 3.75);
assert.deepEqual(improved.events.map(event => event[0]), ['set', 'ramp', 'set', 'ramp', 'start']);
assert.deepEqual(improved.events.at(-1), ['start', 3, 1.25]);
assert.equal(improved.events.at(-2)[2], 3.75);
const original = run('original', 0);
assert.deepEqual(original.events, [['start', 3, 0]]);
assert.equal(original.result.end, 5);

// Exercise the handlers in the order a native range input fires them.
const slider = {value: 0, setAttribute() {}};
const seeks = [], pointerEvents = {};
const controls = runInNewContext(
  source.slice(source.indexOf('let seekSession ='), source.indexOf('function updatePlaybackProgress')) +
  `\nseekSession = session;
    updatePlaybackClock(false);
    ({refresh: () => updatePlaybackClock(false)});`,
  {
    session: {paused: true, position: 1, timeline},
    playbackBar: slider,
    playbackSchedule: [],
    playbackTotal: timeline.length,
    playbackContext: null,
    lifecycle: new AbortController(),
    document: {
      querySelector: () => ({}),
      addEventListener: (event, handler) => { pointerEvents[event] = handler; },
    },
    playFinal: (previous, seek) => seeks.push({time: seek.time, paused: seek.paused}),
  },
);
assert.equal(slider.disabled, false);
slider.onpointerdown();
slider.value = 1.5;
controls.refresh();
assert.equal(slider.value, 1.5, 'a playback tick must not overwrite the drag');
slider.oninput();
slider.value = 3.8;
slider.oninput();
slider.onchange();
assert.equal(seeks.length, 0);
pointerEvents.pointerup();
slider.onchange();
assert.deepEqual(seeks, [{time: 3.8, paused: true}], 'one seek per drag, preserving pause');
slider.value = 4.5;
slider.oninput(); // Keyboard and assistive technology trigger input without pointerdown.
slider.onchange();
assert.deepEqual(seeks.at(-1), {time: 4.5, paused: true});
assert.equal(seeks.length, 2);
slider.onpointerdown();
slider.value = 5;
slider.oninput();
slider.onpointercancel();
assert.equal(slider.value, 1);
assert.equal(seeks.length, 2);

// Start a prepared recording at an offset inside the second chunk and continue into the third.
const starts = [], requested = [];
const job = {id: 'prepared', total: 3, heading_pauses: [0]};
const durations = [2, 3, 4];
const session = {job, durations: [...durations], timeline: speechTimeline(durations, 0.25, [0]),
                 gap: 0.25, mode: 'original'};
const scope = {
  seek: {session, time: 3.8, paused: false},
  generation: 0, playbackSources: [], playbackSchedule: [],
  stopAudio(retainedSession) {
    assert.equal(retainedSession, session, 'seeking must keep the slider timeline active');
    scope.generation++;
  },
  updatePlaybackClock() {}, updatePlaybackProgress() {}, updateSpeechButtons() {},
  speechStatus: {}, AbortController, URLSearchParams,
  setInterval() {}, clearInterval() {},
  speechTimeline, findSpeechPosition, scheduleSpeechBuffer,
  speechGapBefore: (index, gap, headings) => index ? gap + (headings.includes(index - 1) ? 0.55 : 0) : 0,
  async speechJobStatus() { return {state: 'complete', ready: 3, total: 3}; },
  async fetch(url) {
    if (url.startsWith('/api/speech-timeline?')) return {ok: true, json: async () => ({durations})};
    const index = Number(new URLSearchParams(url.split('?')[1]).get('index'));
    requested.push(index);
    return {ok: true, arrayBuffer: async () => index};
  },
  window: {AudioContext: class {
    currentTime = 1;
    destination = {};
    async resume() {}
    async close() {}
    async decodeAudioData(index) { return {duration: durations[index]}; }
    createBufferSource() {
      return {
        connect() {},
        start(time, offset) {
          starts.push({time, offset});
          queueMicrotask(() => this.onended());
        },
      };
    }
  }},
};
const player = source.slice(source.indexOf('async function playFinal('), source.indexOf('async function setPlaybackPaused('));
await runInNewContext(player + '\nplayFinal(false, seek);', scope);
assert.deepEqual(requested, [1, 2]);
assert.deepEqual(starts.map(item => item.offset), [1, 0]);
assert.equal(starts[1].time, starts[0].time + 2.25);
assert.equal(scope.speechStatus.textContent, 'Чтение завершено');

console.log('Speech playback scheduling and seek checks passed');
