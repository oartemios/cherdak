import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../web/speech.js', import.meta.url), 'utf8');
const scheduleSource = source.slice(source.indexOf('function schedule(buffer,index,at)'), source.indexOf('let first=await waitBuffer(0)'));
assert.ok(scheduleSource.startsWith('function schedule('));

function run(mode, gap) {
  const events = [], playbackSources = [], playbackSchedule = [];
  const ctx = {
    currentTime: 1, destination: {},
    createBufferSource() { return { connect() {}, start(t) { events.push(['start', t]); } }; },
    createGain() { return { connect() {}, gain: {
      setValueAtTime(v, t) { events.push(['set', v, t]); },
      linearRampToValueAtTime(v, t) { events.push(['ramp', v, t]); },
    } }; },
  };
  const schedule = new Function('ctx', 'runMode', 'runGap', 'playbackSources', 'playbackSchedule', scheduleSource + ';return schedule;')(ctx, mode, gap, playbackSources, playbackSchedule);
  const result = schedule({duration: 2}, 1, 3);
  return { result, events, playbackSchedule };
}
const improved = run('improved', .1);
assert.equal(improved.result.end, 5.1);
assert.deepEqual(improved.events.map(event => event[0]), ['set', 'ramp', 'set', 'ramp', 'start']);
assert.equal(improved.events[0][2], 3.1);
const original = run('original', 0);
assert.deepEqual(original.events, [['start', 3]]);
assert.equal(original.result.end, 5);
console.log('Speech playback scheduling checks passed');
