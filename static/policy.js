/* Presentation only. Server policy_engine validates and generates both outputs. */
document.addEventListener('DOMContentLoaded', () => {
  const sync = () => document.querySelectorAll('[data-policy-scope]').forEach(scope => {
    const kind = scope.querySelector('[data-policy-type]').value;
    const automatic = ['url-test', 'fallback', 'load-balance'].includes(kind);
    scope.querySelector('[data-policy-options]').hidden = !automatic;
    scope.querySelectorAll('[data-policy-only]').forEach(field => { field.hidden = field.dataset.policyOnly !== kind; });
    scope.querySelectorAll('[data-policy-option]').forEach(input => {
      input.disabled = !automatic || (input.dataset.policyOption !== 'common' && input.dataset.policyOption !== kind);
      input.required = !input.disabled;
    });
  });
  document.querySelectorAll('[data-policy-type]').forEach(type => type.addEventListener('change', sync));
  document.addEventListener('draft-cleared', sync);
  sync();
});
