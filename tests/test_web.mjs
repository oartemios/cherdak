import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

async function loadModule(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  return import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
}

const { markdown } = await loadModule('../web/markdown.js');
assert.equal(markdown('---\ntitle: Тайна\n---\n# Глава'), '<h1>Глава</h1>');
assert.match(markdown('---\nобычный текст'), /обычный текст/);
assert.match(markdown('# Глава\n**Важное**'), /<h1>Глава<\/h1>/);
assert.match(markdown('[[Место|Название]]'), /data-wiki="Место">Название<\/a>/);
assert.match(markdown('---\nобычный текст\n---\n# Глава'), /обычный текст/);
assert.match(markdown('```dataview\nLIST\n```'), /каталог его не выполняет/);
assert.ok(!markdown('<script>alert(1)</script>').includes('<script>'));

const elements = new Map();
for (const id of ['outline', 'notes', 'speech']) {
  const classes = new Set();
  elements.set('#tab-' + id, {
    classList: { toggle(name, active) { if (active) classes.add(name); else classes.delete(name); } },
    setAttribute(name, value) { this[name] = value; }, classes,
  });
  elements.set('#' + id + '-panel', { hidden: false });
}
globalThis.document = { querySelector(selector) { return elements.get(selector); } };
const saved = new Map();
globalThis.localStorage = { getItem(key) { return saved.get(key) ?? null; }, setItem(key, value) { saved.set(key, value); } };
const { initSidebar } = await loadModule('../web/sidebar.js');
initSidebar();
assert.equal(elements.get('#outline-panel').hidden, false);
assert.equal(elements.get('#notes-panel').hidden, true);
elements.get('#tab-notes').onclick();
assert.equal(saved.get('sidebarTool'), 'notes');
assert.equal(elements.get('#notes-panel').hidden, false);
assert.equal(elements.get('#tab-notes')['aria-pressed'], 'true');
initSidebar();
assert.equal(elements.get('#notes-panel').hidden, false);
console.log('Markdown and sidebar checks passed');
