(function (root) {
  'use strict';
  function matchesCountry(code, info, query) {
    const aliases = info.search_aliases || info.aliases;
    return [code, info.english, info.chinese, info.traditional, ...aliases].join(' ').toLowerCase().includes(query.trim().toLowerCase());
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
    const diffButton = document.getElementById('preview-yaml-diff');
    const diffPanel = document.getElementById('yaml-diff-panel');
    const diffStatus = document.getElementById('yaml-diff-status');
    const diffSummary = document.getElementById('yaml-diff-summary');
    const diffCode = document.getElementById('yaml-diff-code');
    const diffText = document.getElementById('yaml-diff-text');
    let revision = 0;
    function dirty() {
      revision++; summary.textContent = '變更尚未解析';
      if (diffPanel && !diffPanel.hidden) {
        diffCode.textContent = ''; diffText.hidden = true; diffSummary.textContent = '';
        diffStatus.textContent = '輸入已變更，請重新預覽。';
      }
    }
    function serialize() {
      document.getElementById('aux-nodes-data').value = JSON.stringify([...rows.children].map(row => ({
        country:row.querySelector('.aux-country').value, name:row.querySelector('.aux-name').value,
        link:row.querySelector('.aux-link').value})));
      document.getElementById('node-overrides-data').value = JSON.stringify(root.nodeOverrides);
    }
    function fillCountries(select, query, value) {
      select.replaceChildren(new Option('自動偵測', ''));
      for (const [code, info] of Object.entries(countries)) {
        if (!matchesCountry(code, info, query) && code !== value) continue;
        select.add(new Option(`${info.emoji} ${code} · ${info.traditional}`, code));
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
        const nameBox = element('label', '名稱', 'preview-name');
        const name = element('input', '', 'form-control terminal-input'); name.value = record.name;
        nameBox.append(name);
        const countryBox = element('div', '國家', 'preview-country');
        const search = element('input', '', 'country-search form-control terminal-input mb-1');
        search.type = 'search'; search.placeholder = '搜尋國家／ISO 代碼'; search.setAttribute('aria-label','搜尋預覽國家');
        const select = element('select', '', 'form-select terminal-select'); select.setAttribute('aria-label','預覽國家');
        fillCountries(select, '', record.country); countryBox.append(search, select);
        const info = element('div', '', 'preview-info'); info.append(element('div', '協定：' + record.protocol), element('div', '狀態：' + root.displayLabel(record.status)), element('div', '來源：' + root.displayLabel(record.source)), element('small', root.displayMessage(record.message)));
        const action = element('button', '套用修改', 'preview-action btn btn-outline-terminal btn-terminal btn-sm'); action.type = 'button';
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
      const start = revision; parseButton.disabled = true; summary.textContent = '解析中…';
      try {
        await root.CSRF.ensure(form);
        const data = new FormData(form); data.delete('yaml_file');
        data.delete('sources');
        for (const key of [...data.keys()]) if (key.startsWith('source_file_')) data.delete(key);
        const response = await fetch('/parse-nodes', {method:'POST', body:data, credentials:'same-origin'});
        if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw Error('登入狀態或安全權杖已失效。草稿已儲存，請重新整理並重新登入。');
        const result = await response.json();
        if (!response.ok) throw Error(root.displayMessage(result.error) || '解析失敗。');
        if (start !== revision) { summary.textContent = '變更尚未解析'; return; }
        render(result.nodes);
        const count = status => result.nodes.filter(n => n.status === status).length;
        summary.textContent = `偵測到 ${result.nodes.length} 個節點 · 就緒 ${count('Ready')} · 警告 ${count('Warning')} · 錯誤 ${count('Error')}`;
      } catch (error) {summary.textContent = root.displayMessage(error.message);}
      finally {parseButton.disabled = false;}
    });
    if (diffButton) diffButton.addEventListener('click', async () => {
      // Read current controls/edits; never send cached parse records or save diff.
      serialize();
      const start = revision;
      diffPanel.hidden = false; diffText.hidden = true; diffCode.textContent = '';
      diffSummary.textContent = ''; diffStatus.textContent = '預覽中…';
      const file = form.querySelector('[name=yaml_file]');
      if (document.getElementById('yaml-source').value === 'custom' && !file.files.length) {
        diffStatus.textContent = '無法預覽：需要重新選擇自訂 YAML 檔案。';
        return;
      }
      diffButton.disabled = true;
      try {
        await root.CSRF.ensure(form);
        const response = await fetch('/api/preview-yaml-diff', {method:'POST', body:new FormData(form), credentials:'same-origin', cache:'no-store'});
        if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
          throw Error('登入狀態或安全權杖已失效，請重新整理或重新登入。');
        }
        const result = await response.json();
        if (start !== revision) return;
        if (!response.ok || !result.ok) throw Error(root.displayMessage(result.error) || 'YAML 預覽失敗。');
        diffStatus.textContent = result.changed ? '有變更' : 'YAML 沒有變更。';
        const counts = result.summary;
        diffSummary.textContent = `舊節點：${counts.old_node_count} · 新節點：${counts.new_node_count} · 策略組：${counts.group_count} · 規則：${counts.rule_count}`;
        diffCode.textContent = result.diff; diffText.hidden = !result.changed;
      } catch (error) {
        if (start === revision) diffStatus.textContent = '無法預覽：' + error.message;
      } finally { diffButton.disabled = false; }
    });
    form.addEventListener('submit', event => {
      if (!isExplicitGenerate(event, generateButton)) return;
      if (!root.saveDraft()) { event.preventDefault(); return; }
      serialize();
      const source = document.getElementById('yaml-source');
      if (source.value === 'custom' && !form.querySelector('[name=yaml_file]').files.length &&
          form.dataset.savedCustom !== 'true') {
        event.preventDefault(); document.getElementById('source-hint').textContent = '需要重新選擇自訂 YAML 檔案。'; return;
      }
      // The server always parses the latest text and overrides, even without Parse Nodes.
      summary.textContent = '正在解析最新輸入並產生 YAML…';
      document.getElementById('operation-progress').classList.add('active');
      document.getElementById('operation-progress-text').textContent = '正在解析最新輸入並寫入 YAML…';
    });
    window.addEventListener('pageshow', () => document.getElementById('operation-progress').classList.remove('active'));
    const copy = document.getElementById('copy-download-url');
    if (copy) copy.addEventListener('click', async () => {
      const input = document.getElementById('download-url');
      try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(input.value);
        else {input.select(); if (!document.execCommand('copy')) throw Error('copy');}
        copy.textContent = '已複製';
      } catch (_) {copy.textContent = '請手動選取並複製連結';}
    });
    if (location.hash === '#generate-result') document.getElementById('generate-result').scrollIntoView();
  });
})(typeof window === 'undefined' ? globalThis : window);
