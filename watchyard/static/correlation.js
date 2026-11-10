'use strict';
(() => {
  const panel = $('correlation-preview');
  const list = $('correlation-groups');
  let pending = false;
  let signature;

  function linkedGroup() {
    return location.hash.match(/^#group=([0-9a-f]{32})$/)?.[1];
  }

  async function refreshPreview() {
    if (!signedIn || document.hidden || currentView !== 'activity' || !panel.open || pending) return;
    pending = true;
    try {
      const requested = linkedGroup();
      const path = requested ? '/api/activity/preview?group=' + requested : '/api/activity/preview';
      const groups = await api(path, undefined, {signal: AbortSignal.timeout(6000)});
      if (requested !== linkedGroup() || !signedIn) return;
      const next = JSON.stringify([requested, groups]);
      if (signature === next) return;
      signature = next;
      const missing = requested && !groups.some(group => group.id === requested);
      const markup = groups.length ? groups.map(group => {
        const cameras = new Set(group.events.map(event => event.camera_name)).size;
        const label = ({person: 'Person activity', car: 'Vehicle activity', mixed: 'People and vehicle'})[group.label];
        const views = group.events.map(event => {
          const date = new Date(event.created * 1000).toLocaleString([], {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
          });
          return `<li><button data-group-replay="${esc(event.id)}">${icon('play')} ${esc(event.camera_name)}</button>
                    <span>${esc(date)}<small>${esc(event.reason || 'First event')}</small></span></li>`;
        }).join('');
        return `<section class="${group.id === requested ? 'linked-activity-group' : ''}"><h3>${label}</h3><p>${group.events.length} events from ${cameras} ${cameras === 1 ? 'camera' : 'cameras'}</p>
                 <ul>${views}</ul></section>`;
      }).join('') : '<p>No groups suggested yet.</p>';
      list.innerHTML = (missing ? '<p>This group is no longer in recent history.</p>' : '') + markup;
    } catch {
      signature = null;
      list.textContent = 'Could not load suggestions. Try reopening this panel.';
    } finally {
      pending = false;
    }
  }

  function openLinkedGroup() {
    if (currentView === 'activity' && linkedGroup()) panel.open = true;
    refreshPreview();
  }

  panel.addEventListener('toggle', refreshPreview);
  document.addEventListener('watchyard:navigate', openLinkedGroup);
  openLinkedGroup();
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-group-replay]');
    if (button) window.WatchyardReplay.openEvent(button.dataset.groupReplay);
  });
  setInterval(refreshPreview, 12000);
})();
