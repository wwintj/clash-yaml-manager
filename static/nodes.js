(function (root) {
  'use strict';
  function matchesCountry(code, info, query) {
    const aliases = info.search_aliases || info.aliases;
    return [code, info.english, info.chinese, ...aliases].join(' ').toLowerCase().includes(query.trim().toLowerCase());
  }
  function preventImplicitGeneration(event) {
    // Delegation covers restored/cloned auxiliary rows and dynamic preview inputs.
    // Textareas keep newlines; buttons keep keyboard activation. Other forms are
    // outside this listener, so Enter still works for login/password changes.
    if (event.key === 'Enter' && event.target.tagName === 'INPUT' &&
        !['submit', 'button', 'reset'].includes(event.target.type)) {
      event.preventDefault();
    }
  }
  function isExplicitGenerate(event, button) {
    // Fail closed for missing/unknown submitters, without a persistent click flag.
    // requestSubmit(button) uses this same standard SubmitEvent identity.
    if (button && event.submitter === button) return true;
    event.preventDefault();
    return false;
  }
  if (typeof module !== 'undefined') module.exports = {matchesCountry, preventImplicitGeneration, isExplicitGenerate};
  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('process-form');
    if (!form) return;
    const generateButton = document.getElementById('generate-yaml');
    form.addEventListener('keydown', preventImplicitGeneration);
    const countries = JSON.parse(document.getElementById('country-data').textContent);
    const rows = document.getElementById('aux-node-rows');
    const template = rows.firstElementChild.cloneNode(true);
    const summary = document.getElementById('parse-summary');
    const preview = document.getElementById('parse-preview');
    const parseButton = document.getElementById('parse-nodes');
    let revision = 0;
    function dirty() { revision++; summary.textContent = 'Changes not parsed yet'; }
    function serialize() {
      document.getElementById('aux-nodes-data').value = JSON.stringify([...rows.children].map(row => ({
        country:row.querySelector('.aux-country').value, name:row.querySelector('.aux-name').value,
        link:row.querySelector('.aux-link').value})));
      document.getElementById('node-overrides-data').value = JSON.stringify(root.nodeOverrides);
    }
    function fillCountries(select, query, value) {
      select.replaceChildren(new Option('Auto detect', ''));
      for (const [code, info] of Object.entries(countries)) {
        if (!matchesCountry(code, info, query) && code !== value) continue;
        select.add(new Option(`${info.emoji} ${code} · ${info.english} / ${info.chinese}`, code));
      }
      select.value = value;
    }
    function resetRow(row) {
      row.querySelectorAll('input').forEach(input => {input.value = '';});
      fillCountries(row.querySelector('.aux-country'), '', '');
      row.querySelector('.remove-node-row').disabled = false;
    }
    // Draft-restored rows and newly cloned rows both use delegated handlers.
    rows.querySelectorAll('.remove-node-row').forEach(button => {button.disabled = false;});
    document.getElementById('add-node-row').addEventListener('click', () => {
      const row = template.cloneNode(true); resetRow(row); rows.appendChild(row); dirty();
    });
    rows.addEventListener('click', event => {
      if (!event.target.closest('.remove-node-row')) return;
      const row = event.target.closest('.node-row');
      if (rows.children.length === 1) resetRow(row); else row.remove();
      dirty();
    });
    form.addEventListener('input', event => {
      if (event.target.classList.contains('country-search')) {
        const select = event.target.parentElement.querySelector('select');
        fillCountries(select, event.target.value, select.value); return;
      }
      if (!preview.contains(event.target)) dirty();
    });
    form.addEventListener('change', event => { if (!preview.contains(event.target)) dirty(); });
    document.addEventListener('draft-cleared', () => {preview.replaceChildren(); dirty();});
    function element(tag, text, className) {
      const node = document.createElement(tag); if (text) node.textContent = text;
      if (className) node.className = className; return node;
    }
    function render(records) {
      preview.replaceChildren();
      records.forEach(record => {
        const card = element('div', '', 'preview-node');
        const nameBox = element('label', 'Name', 'preview-name');
        const name = element('input', '', 'form-control terminal-input'); name.value = record.name;
        nameBox.append(name);
        const countryBox = element('div', 'Country', 'preview-country');
        const search = element('input', '', 'country-search form-control terminal-input mb-1');
        search.type = 'search'; search.placeholder = 'Search ISO / English / 中文'; search.setAttribute('aria-label','Search preview country');
        const select = element('select', '', 'form-select terminal-select'); select.setAttribute('aria-label','Preview country');
        fillCountries(select, '', record.country); countryBox.append(search, select);
        const info = element('div', '', 'preview-info'); info.append(element('div', 'Protocol: ' + record.protocol), element('div', 'Status: ' + record.status), element('div', 'Source: ' + record.source), element('small', record.message));
        const action = element('button', 'Apply edit', 'preview-action btn btn-outline-terminal btn-terminal'); action.type = 'button';
        function edit(field, value) {
          root.nodeOverrides[record.key] = {...root.nodeOverrides[record.key], [field]:value};
          root.saveDraft(); dirty();
        }
        name.addEventListener('input', () => edit('name', name.value));
        select.addEventListener('change', () => edit('country', select.value || 'UNKNOWN'));
        action.addEventListener('click', () => parseButton.click());
        card.append(nameBox, countryBox, info, action); preview.append(card);
      });
    }
    parseButton.addEventListener('click', async () => {
      root.saveDraft(); serialize();
      const start = revision; parseButton.disabled = true; summary.textContent = 'Parsing…';
      try {
        const data = new FormData(form); data.delete('yaml_file');
        const response = await fetch('/parse-nodes', {method:'POST', body:data, credentials:'same-origin'});
        if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw Error('Session or CSRF expired. Draft saved; refresh and log in again.');
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Parse failed.');
        if (start !== revision) { summary.textContent = 'Changes not parsed yet'; return; }
        render(result.nodes);
        const count = status => result.nodes.filter(n => n.status === status).length;
        summary.textContent = `${result.nodes.length} nodes detected · ${count('Ready')} ready · ${count('Warning')} warning · ${count('Error')} errors`;
      } catch (error) {summary.textContent = error.message;}
      finally {parseButton.disabled = false;}
    });
    form.addEventListener('submit', event => {
      if (!isExplicitGenerate(event, generateButton)) return;
      if (!root.saveDraft()) { event.preventDefault(); return; }
      serialize();
      const source = document.getElementById('yaml-source');
      if (source.value === 'custom' && !form.querySelector('[name=yaml_file]').files.length &&
          form.dataset.savedCustom !== 'true') {
        event.preventDefault(); document.getElementById('source-hint').textContent = 'Custom YAML needs to be selected again.'; return;
      }
      // The server always parses the latest text and overrides, even without Parse Nodes.
      summary.textContent = 'Parsing latest input and generating YAML…';
      document.getElementById('operation-progress').classList.add('active');
      document.getElementById('operation-progress-text').textContent = 'Parsing latest input and writing YAML…';
    });
    window.addEventListener('pageshow', () => document.getElementById('operation-progress').classList.remove('active'));
    const copy = document.getElementById('copy-download-url');
    if (copy) copy.addEventListener('click', async () => {
      const input = document.getElementById('download-url');
      try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(input.value);
        else {input.select(); if (!document.execCommand('copy')) throw Error('copy');}
        copy.textContent = 'Copied';
      } catch (_) {copy.textContent = 'Select and copy the link';}
    });
    if (location.hash === '#generate-result') document.getElementById('generate-result').scrollIntoView();
  });
})(typeof window === 'undefined' ? globalThis : window);
