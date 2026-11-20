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
