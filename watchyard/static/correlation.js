'use strict';
(() => {
  const panel = $('correlation-preview');
  const list = $('correlation-groups');
  let pending = false;
  let signature;

  async function refreshPreview() {
    if (!signedIn || document.hidden || currentView !== 'activity' || !panel.open || pending) return;
    pending = true;
    try {
      const groups = await api('/api/activity/preview', undefined, {signal: AbortSignal.timeout(6000)});
      const next = JSON.stringify(groups);
      if (signature === next) return;
      signature = next;
      list.innerHTML = groups.length ? groups.map(group => {
        const cameras = new Set(group.events.map(event => event.camera_name)).size;
        const label = group.label === 'person' ? 'Person activity' : 'Vehicle activity';
        const views = group.events.map(event => {
          const date = new Date(event.created * 1000).toLocaleString([], {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
          });
          return `<li><button data-group-replay="${esc(event.id)}">${icon('play')} ${esc(event.camera_name)}</button>
                    <span>${esc(date)}<small>${esc(event.reason || 'First event')}</small></span></li>`;
        }).join('');
        return `<section><h3>${label}</h3><p>${group.events.length} events from ${cameras} ${cameras === 1 ? 'camera' : 'cameras'}</p>
                 <ul>${views}</ul></section>`;
      }).join('') : '<p>No groups suggested yet.</p>';
    } catch {
      signature = null;
      list.textContent = 'Could not load suggestions. Try reopening this panel.';
    } finally {
      pending = false;
    }
  }

  panel.addEventListener('toggle', refreshPreview);
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-group-replay]');
    if (button) window.WatchyardReplay.openEvent(button.dataset.groupReplay);
  });
  setInterval(refreshPreview, 12000);
})();
