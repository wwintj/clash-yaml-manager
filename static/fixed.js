/* Fixed forms restore server state, never read/write the temporary browser draft. */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => { if (!confirm(form.dataset.confirm)) event.preventDefault(); });
  });
  document.querySelectorAll('.copy-fixed-url').forEach(button => {
    button.addEventListener('click', async () => {
      const input = button.parentElement.querySelector('.fixed-url');
      const status = button.parentElement.querySelector('.copy-status');
      try {
        await navigator.clipboard.writeText(input.value);
        status.textContent = 'Copied';
      } catch (_) {
        input.focus(); input.select(); status.textContent = 'Copy unavailable. Select and copy this URL manually.';
      }
    });
  });
  const form = document.querySelector('form[data-fixed]');
  if (!form) return;
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
