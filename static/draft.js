/* Local-only drafts: never store files, passwords, CSRF tokens or session cookies. */
(function (root) {
  'use strict';
  const KEY = 'clash-yaml-manager.draft.v1';
  const TTL = 30 * 24 * 60 * 60 * 1000;
  function store(storage, value, now = Date.now()) {
    storage.setItem(KEY, JSON.stringify({version: 1, saved_at: now, ...value}));
  }
  function restore(storage, now = Date.now()) {
    const raw = storage.getItem(KEY);
    if (!raw) return null;
    try {
      const draft = JSON.parse(raw);
      if (draft.version !== 1 || !Number.isFinite(draft.saved_at) ||
          now - draft.saved_at >= TTL || draft.saved_at > now ||
          typeof draft.batch !== 'string' || !Array.isArray(draft.rows) ||
          !draft.rows.every(r => r && ['country', 'name', 'link'].every(k => typeof r[k] === 'string')) ||
          !Array.isArray(draft.policies)) throw Error('invalid');
      return draft;
    } catch (_) { storage.removeItem(KEY); return null; }
  }
  function clear(storage) { storage.removeItem(KEY); }
  const api = {KEY, TTL, store, restore, clear};
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
    const file = form.querySelector('[name=yaml_file]');
    const status = document.getElementById('draft-status');
    const hint = document.getElementById('source-hint');
    const policies = [...document.querySelectorAll('[name=special_groups]')];
    let timer;
    root.nodeOverrides = {};
    function syncSource() {
      file.disabled = source.value !== 'custom';
      hint.textContent = source.value === 'custom' && !file.files.length ? 'Custom YAML needs to be selected again.' : '';
    }
    function snapshot() {
      return {batch: batch.value, source: source.value,
        rows: [...rows.children].map(row => ({country: row.querySelector('.aux-country').value,
          name: row.querySelector('.aux-name').value, link: row.querySelector('.aux-link').value})),
        policies: policies.filter(p => p.checked).map(p => p.value), overrides: root.nodeOverrides};
    }
    function save() {
      clearTimeout(timer); timer = null;
      try { store(localStorage, snapshot()); status.textContent = 'Draft saved'; return true; }
      catch (_) { status.textContent = 'Draft could not be saved — browser storage unavailable or full.'; return false; }
    }
    root.saveDraft = save;
    try {
      const draft = restore(localStorage);
      if (draft) {
        batch.value = draft.batch;
        source.value = draft.source === 'custom' ? 'custom' : 'default';
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
    document.addEventListener('input', event => {
      if (!form.contains(event.target) && !policies.includes(event.target)) return;
      status.textContent = 'Saving…'; clearTimeout(timer); timer = setTimeout(save, 250);
    });
    document.addEventListener('change', event => {
      if (!form.contains(event.target) && !policies.includes(event.target)) return;
      syncSource(); save();
    });
    document.addEventListener('click', event => {
      if (event.target.closest('#add-node-row, .remove-node-row')) setTimeout(save, 0);
      if (!event.target.closest('.clear-draft')) return;
      if (!confirm('Clear the saved draft and all node inputs?')) return;
      clearTimeout(timer); timer = null;
      try { clear(localStorage); } catch (_) { /* Form reset still works. */ }
      form.reset(); policies.forEach(p => { p.checked = false; });
      rows.replaceChildren(template.cloneNode(true)); root.nodeOverrides = {};
      syncSource(); document.dispatchEvent(new Event('draft-cleared'));
      status.textContent = 'Draft cleared';
    });
    // Capture before other submit handlers; also covers logout and password changes.
    document.addEventListener('submit', save, true);
    window.addEventListener('pagehide', () => { if (timer) save(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden && timer) save(); });
  });
})(typeof window === 'undefined' ? globalThis : window);
