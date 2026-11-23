// Each sidebar tool supplies a matching #tab-{id} and #{id}-panel element.
const tools = ['outline', 'notes', 'speech'];

export function initSidebar() {
  function select(tool) {
    if (!tools.includes(tool)) tool = 'outline';
    for (const id of tools) {
      const active = id === tool;
      document.querySelector('#' + id + '-panel').hidden = !active;
      const button = document.querySelector('#tab-' + id);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    }
  }
  for (const id of tools) {
    document.querySelector('#tab-' + id).onclick = () => {
      localStorage.setItem('sidebarTool', id);
      select(id);
    };
  }
  select(localStorage.getItem('sidebarTool') || 'outline');
}

export function renderOutline(article, outline) {
  outline.replaceChildren();
  const headings = [...article.querySelectorAll('h1,h2,h3,h4,h5,h6')];
  if (!headings.length) {
    outline.textContent = 'Заголовков нет';
    return;
  }

  function jumpTo(heading) {
    heading.focus({preventScroll: true});
    heading.scrollIntoView({block: 'start', inline: 'nearest'});
  }

  headings.forEach((heading, index) => {
    heading.id = 'heading-' + index;
    heading.tabIndex = -1;
    const link = document.createElement('a');
    link.className = 'outline-link';
    link.href = '#' + heading.id;
    link.textContent = heading.textContent;
    link.style.paddingLeft = (Number(heading.tagName[1]) - 1) * 10 + 'px';
    link.onclick = event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      if (!heading.isConnected) return;
      // Fragment navigation would trigger the file browser's popstate handler.
      history.replaceState(history.state, '', link.hash);
      jumpTo(heading);
    };
    outline.append(link);
  });

  const target = headings.find(heading => '#' + heading.id === location.hash);
  if (target) jumpTo(target);
}
