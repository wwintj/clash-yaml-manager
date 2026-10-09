/* Local-only drafts: never store files, passwords, CSRF tokens or session cookies. */
(function (root) {
  'use strict';
  const KEY = 'clash-yaml-manager.draft.v1';
  const POLICY_KEY = 'clash-yaml-manager.draft.policy.v1';
  const TTL = 30 * 24 * 60 * 60 * 1000;
  function policy(storage) { return storage.getItem(POLICY_KEY) === 'keep' ? 'keep' : 'timed'; }
  function setPolicy(storage, value) {
    if (!['timed', 'keep'].includes(value)) throw Error('invalid policy');
    storage.setItem(POLICY_KEY, value);
  }
  function fields(value) {
    const overrides = {};
    if (value.overrides && typeof value.overrides === 'object' && !Array.isArray(value.overrides)) {
      for (const [id, row] of Object.entries(value.overrides)) {
        if (row && typeof row === 'object' && !Array.isArray(row)) {
          const safe = {};
          for (const key of ['country', 'name']) if (typeof row[key] === 'string') safe[key] = row[key];
          Object.defineProperty(overrides, id, {value:safe, enumerable:true});
        }
      }
    }
    return {batch:value.batch, rows:value.rows.map(row => ({country:row.country, name:row.name, link:row.link})),
      policies:value.policies.filter(p => typeof p === 'string'), source:value.source,
      ...(value.node_update_mode === undefined ? {} : {node_update_mode:value.node_update_mode}), overrides};
  }
  function store(storage, value, now = Date.now(), retention = 'timed') {
    if (!['timed', 'keep'].includes(retention)) throw Error('invalid policy');
    storage.setItem(KEY, JSON.stringify({version: 1, saved_at: now, ...fields(value),
      ...(retention === 'keep' ? {retention_policy:'keep'} : {})}));
  }
  function restore(storage, now = Date.now()) {
    const raw = storage.getItem(KEY);
    if (!raw) return null;
    try {
      const draft = JSON.parse(raw);
      if (draft.version !== 1 || !Number.isFinite(draft.saved_at) ||
          ![undefined, 'timed', 'keep'].includes(draft.retention_policy) ||
          (draft.retention_policy !== 'keep' && now - draft.saved_at >= TTL) || draft.saved_at > now ||
          typeof draft.batch !== 'string' || !Array.isArray(draft.rows) ||
          !draft.rows.every(r => r && ['country', 'name', 'link'].every(k => typeof r[k] === 'string')) ||
          !Array.isArray(draft.policies)) throw Error('invalid');
      return {version:1, saved_at:draft.saved_at, ...fields(draft),
        node_update_mode:draft.node_update_mode === 'merge' ? 'merge' : 'replace',
        ...(draft.retention_policy === 'keep' ? {retention_policy:'keep'} : {})};
    } catch (_) { storage.removeItem(KEY); return null; }
  }
  function clear(storage) { storage.removeItem(KEY); }
  const api = {KEY, POLICY_KEY, TTL, store, restore, clear, policy, setPolicy};
  if (typeof module !== 'undefined') module.exports = api;
  root.Drafts = api;
  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('process-form');
    if (!form) return; // Login/CSRF pages must never replace the saved draft with an empty one.
    const rows = document.getElementById('aux-node-rows');
    const template = rows.firstElementChild.cloneNode(true);
    const batch = document.getElementById('batch_nodes');
    const source = document.getElementById('yaml-source');
    const updateMode = document.getElementById('node-update-mode');
    const file = form.querySelector('[name=yaml_file]');
    const status = document.getElementById('draft-status');
    const keep = document.getElementById('keep-draft');
    const hint = document.getElementById('source-hint');
    const policies = [...document.querySelectorAll('[name=special_groups]')];
    let timer, cleared = false, retention = 'timed';
    root.nodeOverrides = {};
    function syncSource() {
      file.disabled = source.value !== 'custom';
      hint.textContent = source.value === 'custom' && !file.files.length ? 'Custom YAML needs to be selected again.' : '';
    }
    function snapshot() {
      return {batch: batch.value, source: source.value, node_update_mode: updateMode.value,
        rows: [...rows.children].map(row => ({country: row.querySelector('.aux-country').value,
          name: row.querySelector('.aux-name').value, link: row.querySelector('.aux-link').value})),
        policies: policies.filter(p => p.checked).map(p => p.value), overrides: root.nodeOverrides};
    }
    function save() {
      clearTimeout(timer); timer = null;
      if (cleared) return false;
      try {
        store(localStorage, snapshot(), Date.now(), retention);
        status.textContent = 'Draft saved';
        return true;
      }
      catch (_) { status.textContent = 'Draft could not be saved — browser storage unavailable or full.'; return false; }
    }
    root.saveDraft = save;
    try {
      const draft = restore(localStorage);
      retention = policy(localStorage); keep.checked = retention === 'keep';
      if (draft) {
        batch.value = draft.batch;
        source.value = draft.source === 'custom' ? 'custom' : 'default';
        updateMode.value = draft.node_update_mode;
        rows.replaceChildren();
        (draft.rows.length ? draft.rows : [{country:'', name:'', link:''}]).forEach(value => {
          const row = template.cloneNode(true);
          ['country', 'name', 'link'].forEach(k => { row.querySelector('.aux-' + k).value = value[k]; });
          rows.appendChild(row);
        });
        policies.forEach(p => { p.checked = draft.policies.includes(p.value); });
        root.nodeOverrides = draft.overrides && typeof draft.overrides === 'object' && !Array.isArray(draft.overrides) ? draft.overrides : {};
        status.textContent = 'Draft restored';
      }
    } catch (_) { status.textContent = 'Draft storage unavailable.'; }
    syncSource();
    window.addEventListener('storage', event => {
      if (event.key === null || event.key === KEY && event.newValue === null) {
        cleared = true; clearTimeout(timer); timer = null;
        status.textContent = 'Draft cleared in another tab';
      }
      if (event.key === null || event.key === POLICY_KEY) {
        retention = event.newValue === 'keep' ? 'keep' : 'timed';
        keep.checked = retention === 'keep';
      }
    });
    keep.addEventListener('change', () => {
      try {
        // Validate the stored record under its OLD policy before applying opt-in.
        // A preference alone never revives an expired/deleted/corrupt draft.
        const existing = restore(localStorage);
        const next = keep.checked ? 'keep' : 'timed'; setPolicy(localStorage, next); retention = next;
        if (!cleared && (existing || timer)) save();
        else status.textContent = retention === 'keep' ? 'Future drafts kept until cleared / this browser' : 'Draft autosave / 30 days / this browser';
      } catch (_) {
        keep.checked = retention === 'keep';
        status.textContent = 'Draft policy could not be saved — browser storage unavailable or full.';
      }
    });
    document.addEventListener('input', event => {
      if (!form.contains(event.target) && !policies.includes(event.target)) return;
      cleared = false;
      status.textContent = 'Saving…'; clearTimeout(timer); timer = setTimeout(save, 250);
    });
    document.addEventListener('change', event => {
      if (!form.contains(event.target) && !policies.includes(event.target)) return;
      cleared = false;
      syncSource(); save();
    });
    document.addEventListener('click', event => {
      if (event.target.closest('#add-node-row, .remove-node-row')) { cleared = false; setTimeout(save, 0); }
      if (!event.target.closest('.clear-draft')) return;
      if (!confirm('Clear the saved draft and all node inputs?')) return;
      clearTimeout(timer); timer = null;
      cleared = true;
      let removed = true;
      try { clear(localStorage); } catch (_) { removed = false; }
      form.reset(); policies.forEach(p => { p.checked = false; });
      updateMode.value = 'replace';
      rows.replaceChildren(template.cloneNode(true)); root.nodeOverrides = {};
      syncSource(); document.dispatchEvent(new Event('draft-cleared'));
      status.textContent = removed ? 'Draft cleared' : 'Draft could not be removed — browser storage unavailable. Clear site data in your browser.';
    });
    // Capture before other submit handlers; also covers logout and password changes.
    document.addEventListener('submit', save, true);
    window.addEventListener('pagehide', () => { if (timer) save(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden && timer) save(); });
  });
})(typeof window === 'undefined' ? globalThis : window);
