import MarkdownIt from './vendor/markdown-it.mjs';

const parser = new MarkdownIt({ html: false, linkify: true });
const escape = parser.utils.escapeHtml;
const calloutTitles = new Map([
  ['note', 'Заметка'],
  ['tip', 'Совет'],
  ['important', 'Важно'],
  ['warning', 'Внимание'],
  ['caution', 'Осторожно'],
]);

const wikiPattern = /\[\[([^\]\n]+)\]\]/y;
parser.inline.ruler.before('link', 'wiki_link', (state, silent) => {
  if (state.linkLevel || !state.src.startsWith('[[', state.pos)) return false;
  wikiPattern.lastIndex = state.pos;
  const match = wikiPattern.exec(state.src);
  if (!match || wikiPattern.lastIndex > state.posMax) return false;

  if (!silent) {
    const [target, label] = match[1].split('|');
    const token = state.push('wiki_link', 'a', 0);
    token.meta = { target };
    token.content = label || target;
  }
  state.pos += match[0].length;
  return true;
});

parser.renderer.rules.wiki_link = (tokens, index) => {
  const { meta: { target }, content } = tokens[index];
  return `<a href="#" class="wiki-link" data-wiki="${escape(target)}">${escape(content)}</a>`;
};

parser.core.ruler.before('inline', 'catalog_blocks', state => {
  const { tokens } = state;
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (tokens[index + 1]?.type !== 'paragraph_open' || tokens[index + 2]?.type !== 'inline') continue;
    const inline = tokens[index + 2];

    if (token.type === 'list_item_open') {
      const task = /^\[([ xX])\][ \t]+/.exec(inline.content);
      if (!task) continue;
      token.attrJoin('class', 'markdown-task');
      token.meta = { checked: task[1] !== ' ' };
      inline.content = inline.content.slice(task[0].length);
    }

    if (token.type === 'blockquote_open') {
      const callout = /^\[!(note|tip|important|warning|caution)\](?:[ \t]+([^\n]*))?(?:\n|$)/i.exec(inline.content);
      if (!callout) continue;
      const kind = callout[1].toLowerCase();
      token.meta = { title: callout[2]?.trim() || calloutTitles.get(kind) };
      token.attrJoin('class', `markdown-callout markdown-callout-${kind}`);
      inline.content = inline.content.slice(callout[0].length);
      if (!inline.content) tokens.splice(index + 1, 3);
    }
  }
});

parser.renderer.rules.blockquote_open = (tokens, index, options, env, renderer) => {
  const { meta } = tokens[index];
  const open = renderer.renderToken(tokens, index, options);
  return meta ? open + `<div class="markdown-callout-title">${escape(meta.title)}</div>\n` : open;
};

parser.renderer.rules.list_item_open = (tokens, index, options, env, renderer) => {
  const { meta } = tokens[index];
  const open = renderer.renderToken(tokens, index, options);
  if (!meta) return open;
  const checked = meta.checked ? ' checked' : '';
  return open + `<input type="checkbox" disabled${checked} aria-label="${meta.checked ? 'Выполнено' : 'Не выполнено'}"> `;
};

const renderFence = parser.renderer.rules.fence;
parser.renderer.rules.fence = (tokens, index, options, env, renderer) => {
  const code = renderFence(tokens, index, options, env, renderer);
  if (!/^dataview(?:js)?$/i.test(tokens[index].info.trim())) return code;
  return '<p class="markdown-notice">Запрос Obsidian Dataview показан как код: этот каталог его не выполняет.</p>\n' + code;
};

function relativeProjectPath(href, path) {
  if (!path || /^(?:[a-z][a-z\d+.-]*:|[/#?])/i.test(href)) return '';
  try {
    const url = new URL(href, 'https://catalog.invalid/' + path.split('/').map(encodeURIComponent).join('/'));
    const segments = url.pathname.slice(1).split('/').map(decodeURIComponent);
    if (segments[0] !== path.split('/')[0] || segments.some(segment => /[/\\\0]/.test(segment))) return '';
    return segments.join('/');
  } catch {
    return '';
  }
}

parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  const token = tokens[index];
  const href = token.attrGet('href');
  if (/^https?:\/\//i.test(href)) {
    token.attrSet('target', '_blank');
    token.attrSet('rel', 'noopener noreferrer');
  } else {
    const path = relativeProjectPath(href, env.path);
    if (/\.(?:md|markdown|canvas|png)$/i.test(path)) {
      const fragment = href.includes('#') ? href.slice(href.indexOf('#')) : '';
      token.attrSet('href', '/project?' + new URLSearchParams({ kind: env.kind, path }) + fragment);
    }
  }
  return renderer.renderToken(tokens, index, options);
};

const renderImage = parser.renderer.rules.image;
parser.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const token = tokens[index];
  const path = relativeProjectPath(token.attrGet('src'), env.path);
  if (/\.png$/i.test(path)) {
    token.attrSet('src', '/api/image?' + new URLSearchParams({ kind: env.kind, path }));
  }
  return renderImage(tokens, index, options, env, renderer);
};

export function markdown(text, context = {}) {
  const source = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const content = source.replace(/^---\n([\s\S]*?)\n---[ \t]*(?:\n|$)/, (whole, body) =>
    /^(?:[\w.-]+):/m.test(body) ? '' : whole);
  return parser.render(content, { ...context }).trimEnd();
}
