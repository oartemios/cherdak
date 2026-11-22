import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

async function loadModule(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  return import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
}

const { markdown } = await import('../web/markdown.js');
assert.equal(markdown('---\ntitle: Тайна\n---\n# Глава'), '<h1>Глава</h1>');
assert.match(markdown('---\nобычный текст'), /обычный текст/);
assert.match(markdown('# Глава\n**Важное**'), /<h1>Глава<\/h1>/);
assert.match(markdown('[[Место|Название]]'), /data-wiki="Место">Название<\/a>/);
assert.match(markdown('---\nобычный текст\n---\n# Глава'), /обычный текст/);
assert.match(markdown('```dataview\nLIST\n```'), /каталог его не выполняет/);
assert.ok(!markdown('<script>alert(1)</script>').includes('<script>'));

assert.match(markdown('Глава\n=====\n\nСтрока  \nперенос\n\n---'),
  /<h1>Глава<\/h1>[\s\S]*Строка<br>\nперенос[\s\S]*<hr>/);
assert.match(markdown('3. Первый\n   - Вложенный\n\n> > Цитата'),
  /<ol start="3">[\s\S]*<ul>[\s\S]*<blockquote>\n<blockquote>/);
assert.match(markdown('Колонка | Значение\n--- | ---:\n**Текст** | ~~старое~~'),
  /<table>[\s\S]*<strong>Текст<\/strong>[\s\S]*<s>старое<\/s>/);
assert.match(markdown('- [x] **Готово**\n- [ ] В работе'),
  /<input type="checkbox" disabled checked[^>]*> <strong>Готово<\/strong>[\s\S]*<input type="checkbox" disabled aria-label=/);
assert.match(markdown('> [!TIP] План\n> **Сохраните** черновик.'),
  /markdown-callout-tip">\n<div class="markdown-callout-title">План<\/div>\n<p><strong>Сохраните<\/strong>/);
assert.match(markdown('> [!NOTE]\n>\n> - Пункт'), /Заметка<\/div>\n<ul>/);
assert.match(markdown('~~~js\n[[Место]] <tag>\n~~~'),
  /<code class="language-js">\[\[Место\]\] &lt;tag&gt;/);
assert.match(markdown('`[[Место]]` и \\*текст*'), /<code>\[\[Место\]\]<\/code> и \*текст\*/);
assert.match(markdown('https://example.com'), /href="https:\/\/example.com" target="_blank" rel="noopener noreferrer"/);
assert.doesNotMatch(markdown('[X](javascript:alert%281%29) ![X](data:text/html,test)'), /(?:href|src)=/);

const context = { kind: 'books', path: 'Книга/главы/глава.md' };
assert.match(markdown('![Схема](../img/map.png)\n\n[Связь][next]\n\n[next]: next.md', context),
  /src="\/api\/image\?kind=books&amp;path=[^"]+%2Fimg%2Fmap.png"[\s\S]*href="\/project\?kind=books&amp;path=[^"]+%2Fnext.md"/);
assert.doesNotMatch(markdown('![Схема](../../other/map.png)', context), /\/api\/image/);

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
