(() => {
  const modeNames = {paused: 'Paused', home: 'At home', away: 'Away', unknown: 'Presence unknown'};
  const outcomes = {ordinary: 'Routine activity', observe: 'More evidence needed', held: 'Held by alert settings', urgent: 'Urgent review'};
  const form = $('presence-form');
  const mode = $('presence-mode');
  const duration = $('presence-duration');
  const save = $('presence-save');
  const error = $('presence-error');
  const results = $('simulation-results');
  let dirty = false;
  let loading = false;
  let saving = false;
  let signature = '';

  function renderForm() {
    $('presence-period').classList.toggle('hidden', mode.value !== 'away');
    mode.disabled = duration.disabled = saving;
    save.disabled = !mode.value || !dirty || saving;
  }

  function renderHistory(assessments) {
    const next = JSON.stringify(assessments);
    if (next === signature) return;
    signature = next;
    results.replaceChildren();
    if (!assessments.length) {
      const empty = document.createElement('p');
      empty.className = 'settings-note';
      empty.textContent = 'Set presence to At home or Away to start reviewing new person events.';
      results.append(empty);
      return;
    }
    for (const item of assessments) {
      const row = document.createElement('article');
      row.className = 'simulation-result';
      row.dataset.outcome = item.outcome;
      const heading = document.createElement('strong');
      heading.textContent = outcomes[item.outcome];
      const meta = document.createElement('p');
      meta.textContent = `${item.camera_name} · ${new Date(item.assessed_at * 1000).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'})} · ${modeNames[item.presence]}`;
      const reason = document.createElement('p');
      reason.textContent = item.reason;
      const replay = document.createElement('button');
      replay.type = 'button';
      replay.className = 'text-button';
      replay.textContent = 'Open replay';
      replay.addEventListener('click', () => window.WatchyardReplay?.openEvent(item.event_id));
      row.append(heading, meta, reason);
      if (item.outcome === 'urgent' || item.feedback === 'false_alarm') {
        const evidence = document.createElement('p');
        evidence.textContent = item.feedback === 'false_alarm' ? 'Reviewed as a false alarm' :
          `${item.observations} observations over ${item.dwell_seconds} seconds`;
        row.append(evidence);
      }
      row.append(replay);
      results.append(row);
    }
  }

  async function refreshSimulation() {
    if (!signedIn || !admin || currentView !== 'settings' || loading || saving) return;
    loading = true;
    try {
      const {presence, assessments} = await api('/api/incidents/simulation');
      if (!signedIn || !admin) return;
      let description = modeNames[presence.mode];
      if (presence.mode === 'away') {
        description += ' until ' + new Date(presence.until * 1000).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'});
      }
      if (presence.mode === 'unknown') description += ' · Away period ended';
      if ($('presence-state').textContent !== description) $('presence-state').textContent = description;
      if (!dirty) {
        mode.value = presence.mode === 'unknown' ? '' : presence.mode;
        if (presence.mode === 'away') duration.value = String(Math.round((presence.until - presence.changed_at) / 60));
      }
      renderForm();
      renderHistory(assessments);
    } catch (failure) {
      if (signedIn && admin) $('presence-state').textContent = 'Could not load simulation status.';
    } finally {
      loading = false;
    }
  }

  document.addEventListener('watchyard:navigate', refreshSimulation);
  form.addEventListener('change', () => {
    dirty = true;
    error.textContent = '';
    renderForm();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    saving = true;
    error.textContent = '';
    renderForm();
    try {
      const data = {mode: mode.value};
      if (data.mode === 'away') data.minutes = Number(duration.value);
      await api('/api/incidents/presence', data);
      dirty = false;
      notice('Simulation presence saved');
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      saving = false;
      renderForm();
      await refreshSimulation();
    }
  });
  window.WatchyardIncidents = {refresh: refreshSimulation};
})();
