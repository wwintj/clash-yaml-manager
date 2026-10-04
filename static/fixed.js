/* Fixed forms restore server state, never read/write the temporary browser draft. */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => { if (!confirm(form.dataset.confirm)) event.preventDefault(); });
  });
  document.querySelectorAll('.copy-fixed-url').forEach(button => {
    const input = button.parentElement.querySelector('.fixed-url');
    const status = button.parentElement.querySelector('.copy-status');
    const idleText = button.textContent;
    let resetTimer;
    let copying = false;
    button.addEventListener('click', async () => {
      if (copying) return;
      copying = true;
      clearTimeout(resetTimer);
      try {
        await navigator.clipboard.writeText(input.value);
        button.textContent = 'Copied';
        status.textContent = 'URL copied.';
        resetTimer = setTimeout(() => {
          button.textContent = idleText;
          status.textContent = '';
        }, 2000);
      } catch (_) {
        button.textContent = idleText;
        input.focus(); input.select();
        status.textContent = 'Copy failed — select the URL and copy manually.';
      } finally {
        copying = false;
      }
    });
  });
  const toolbar = document.getElementById('fixed-toolbar');
  if (toolbar) {
    const search = document.getElementById('fixed-search');
    const status = document.getElementById('fixed-status');
    const sort = document.getElementById('fixed-sort');
    const clear = document.getElementById('fixed-clear');
    const result = document.getElementById('fixed-result-count');
    const empty = document.getElementById('fixed-no-results');
    const region = document.querySelector('.fixed-list-region');
    const body = region.querySelector('tbody');
    // Keep the management index deliberately separate from bearer URL inputs.
    const rows = [...body.rows].map((row, index) => ({
      row, index, name: row.dataset.name.toLowerCase(), prefix: row.dataset.prefix.toLowerCase(),
      status: row.dataset.status, nodes: Number(row.dataset.nodeCount), updated: Number(row.dataset.updated)
    }));
    function apply() {
      const query = search.value.trim().toLowerCase();
      const [field, direction] = sort.value.split('-');
      const ordered = [...rows].sort((a, b) => {
        const compared = field === 'name' ? (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) : a[field] - b[field];
        return (direction === 'desc' ? -compared : compared) || a.index - b.index;
      });
      const fragment = document.createDocumentFragment();
      let visible = 0;
      for (const item of ordered) {
        item.row.hidden = !(status.value === 'all' || item.status === status.value) ||
          !(item.name.includes(query) || item.prefix.includes(query));
        if (!item.row.hidden) visible++;
        fragment.append(item.row);
      }
      body.append(fragment);
      result.textContent = `${visible === rows.length ? visible : `${visible} of ${rows.length}`} ${rows.length === 1 ? 'subscription' : 'subscriptions'}`;
      empty.hidden = visible !== 0;
      region.hidden = visible === 0;
      clear.disabled = !search.value && status.value === 'all' && sort.value === 'updated-desc';
    }
    search.addEventListener('input', apply);
    status.addEventListener('change', apply);
    sort.addEventListener('change', apply);
    clear.addEventListener('click', () => {
      search.value = ''; status.value = 'all'; sort.value = 'updated-desc'; apply(); search.focus();
    });
    apply();
    toolbar.hidden = false;
  }
  document.querySelectorAll('form[data-source-action]').forEach(action => {
    action.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (action.dataset.busy) { event.preventDefault(); return; }
      action.dataset.busy = 'true';
      document.querySelectorAll('button[form="' + action.id + '"]').forEach(button => {
        button.dataset.idleText = button.textContent;
        button.disabled = true; button.textContent = 'Refreshing...';
      });
    });
  });
  document.querySelectorAll('form[data-health-check], form[data-proxy-check]').forEach(action => {
    action.addEventListener('submit', event => {
      if (action.dataset.busy) { event.preventDefault(); return; }
      action.dataset.busy = 'true';
      const button = action.querySelector('button');
      button.dataset.idleText = button.textContent;
      button.disabled = true; button.textContent = 'Checking...';
    });
  });
  document.querySelectorAll('[data-health-mode]').forEach(mode => {
    const field = mode.form.querySelector('[data-health-interval]');
    const select = field.querySelector('select');
    const show = () => {
      field.hidden = mode.value !== 'automatic';
      select.disabled = field.hidden; select.required = !field.hidden;
    };
    mode.addEventListener('change', show); show();
  });
  const proxyScope = document.querySelector('[data-proxy-scope]');
  if (proxyScope) {
    const custom = document.getElementById('proxy-custom-fields');
    const show = () => { custom.hidden = proxyScope.value !== 'custom'; };
    proxyScope.addEventListener('change', show);
    show();
  }
  const healthPolicyMode = document.querySelector('[name=health_policy_mode]');
  if (healthPolicyMode) {
    const sync = () => document.querySelectorAll('[data-health-policy-warning]').forEach(warning => {
      warning.hidden = healthPolicyMode.value !== 'exclude-unhealthy';
    });
    healthPolicyMode.addEventListener('change', sync); sync();
  }
  const form = document.querySelector('form[data-fixed]');
  if (!form) return;
  const external = document.getElementById('external-sources');
  function serializeSources() {
    const sources = [...external.children].map((card, index) => {
      const file = card.querySelector('.source-file');
      if (file) file.name = 'source_file_' + index;
      return {id:card.dataset.sourceId, type:card.dataset.sourceType,
        name:card.querySelector('.source-name').value,
        enabled:card.querySelector('.source-enabled').checked,
        format:card.querySelector('.source-format').value,
        ...(card.dataset.sourceType === 'remote_url' ? {url:card.querySelector('.source-url').value,
          refresh_interval_seconds:card.querySelector('.source-refresh-interval').value === '' ? null :
            Number(card.querySelector('.source-refresh-interval').value)} : {})};
    });
    document.getElementById('external-sources-data').value = JSON.stringify(sources);
  }
  for (const kind of ['remote', 'uploaded']) {
    document.getElementById('add-' + kind + '-source').addEventListener('click', () => {
      external.append(document.getElementById(kind + '-source-template').content.cloneNode(true));
      serializeSources();
    });
  }
  external.addEventListener('click', event => {
    if (event.target.closest('.remove-source')) { event.target.closest('.external-source').remove(); serializeSources(); }
  });
  form.addEventListener('submit', event => {
    if (event.submitter?.id !== 'generate-yaml') return;
    serializeSources();
    // Let the shared form validation run before preventing duplicate submissions.
    queueMicrotask(() => {
      if (!event.defaultPrevented) {
        document.getElementById('generate-yaml').dataset.idleText = document.getElementById('generate-yaml').textContent;
        document.getElementById('generate-yaml').disabled = true;
        document.getElementById('generate-yaml').textContent = 'Saving and refreshing...';
      }
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('button[data-idle-text]').forEach(button => {
      button.disabled = false; button.textContent = button.dataset.idleText; delete button.dataset.idleText;
    });
    document.querySelectorAll('form[data-busy]').forEach(action => { delete action.dataset.busy; });
  });
  serializeSources();
  const fields = JSON.parse(document.getElementById('fixed-fields').textContent);
  window.nodeOverrides = fields.node_overrides;
  window.saveDraft = () => true;
  form.querySelector('#batch_nodes').value = fields.batch_nodes;
  const source = form.querySelector('#yaml-source'); source.value = fields.yaml_source;
  const file = form.querySelector('[name=yaml_file]');
  function syncSource() {
    file.disabled = source.value !== 'custom';
    document.getElementById('source-hint').textContent = source.value !== 'custom' ? '' :
      (form.dataset.savedCustom === 'true' ? 'Current custom YAML: saved' : 'Select a Custom YAML file.');
  }
  source.addEventListener('change', syncSource); syncSource();
  const rows = document.getElementById('aux-node-rows');
  const template = rows.firstElementChild.cloneNode(true); rows.replaceChildren();
  (fields.aux_nodes.length ? fields.aux_nodes : [{country:'',name:'',link:''}]).forEach(values => {
    const row = template.cloneNode(true);
    for (const key of ['country','name','link']) row.querySelector('.aux-' + key).value = values[key];
    rows.append(row);
  });
  form.querySelectorAll('[name=special_groups]').forEach(input => { input.checked = fields.special_groups.includes(input.value); });
  const prefix = document.getElementById('url-prefix');
  let edited = Boolean(prefix.value);
  prefix.addEventListener('input', () => { edited = true; });
  document.getElementById('subscription-name').addEventListener('input', event => {
    if (!edited) prefix.value = event.target.value.toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/-+/g,'-').replace(/^-|-$/g,'').slice(0,64).replace(/-$/,'') || 'subscription';
  });
});
