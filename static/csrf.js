/* Refresh only on an explicit action. Never replay a rejected POST or persist tokens. */
(function (root) {
  'use strict';
  async function ensure(form) {
    const response = await fetch('/api/csrf-token', {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: {'X-CSRF-Refresh': '1'}
    });
    if (response.status === 401) {
      throw Error('Session expired; sign in again. Your form has not been submitted.');
    }
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
      throw Error('Security token could not be refreshed. Reload or sign in again; your form has not been submitted.');
    }
    let result;
    try { result = await response.json(); }
    catch (_) { throw Error('Security token could not be refreshed. Your form has not been submitted.'); }
    if (!result || typeof result.csrf_token !== 'string' || !result.csrf_token || result.csrf_token.length > 4096) {
      throw Error('Security token could not be refreshed. Your form has not been submitted.');
    }
    form.querySelectorAll('input[name="csrf_token"]').forEach(input => { input.value = result.csrf_token; });
  }
  root.CSRF = {ensure}; // Resolves without exposing a token to callers.
  const pending = new WeakSet(), ready = new WeakSet();
  document.addEventListener('submit', async event => {
    const form = event.target, submitter = event.submitter;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    if (ready.has(form)) { ready.delete(form); return; }
    // Keep native validation and the existing explicit Generate-only contract.
    if (form.id === 'process-form' && submitter?.id !== 'generate-yaml') return;
    const action = new URL(submitter?.formAction || form.action, location.href);
    const method = (submitter?.getAttribute('formmethod') || form.method).toLowerCase();
    if (method !== 'post' || action.origin !== location.origin || !form.querySelector('[name="csrf_token"]')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (pending.has(form)) return;
    pending.add(form);
    // Draft capture normally occurs later in this event; preserve it before deferral.
    if (root.saveDraft) root.saveDraft();
    let notice = form.querySelector('[data-csrf-feedback]');
    if (notice) notice.remove();
    try {
      await ensure(form);
      if (!form.isConnected || (submitter && (submitter.form !== form || submitter.disabled))) return;
      ready.add(form);
      try { form.requestSubmit(submitter || undefined); }
      finally { ready.delete(form); }
    } catch (_) {
      // Keep all inputs and files in this page. No navigation, retry or POST here.
      notice = document.createElement('p');
      notice.dataset.csrfFeedback = ''; notice.setAttribute('role', 'alert');
      notice.textContent = 'Security token could not be refreshed. Reload or sign in again; your form has not been submitted.';
      form.append(notice);
    } finally { pending.delete(form); }
  }, true);
})(window);
