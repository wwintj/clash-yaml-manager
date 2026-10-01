/* Display-only legacy messages and active anchor navigation; no business state. */
(function () {
  'use strict';
  const phrases = JSON.parse(document.getElementById('ui-display-phrases')?.textContent || '{}');
  window.displayMessage = value => {
    let text = String(value ?? '');
    for (const [original, english] of Object.entries(phrases).sort((a,b)=>b[0].length-a[0].length)) text = text.split(original).join(english);
    return text.replace(/登录尝试过多，请在 (\d+) 秒后重试。/g, 'Too many login attempts. Try again in $1 seconds.')
      .replace(/已成功删除 (\d+) 个服务器临时文件。/g, 'Deleted $1 temporary server files.')
      .replace(/第 (\d+) 行错误：/g, 'Line $1: ').replace(/第 (\d+) /g, 'Item $1 ');
  };
  const tabs = [...document.querySelectorAll('.settings-nav a')];
  function markSection() {
    const current = tabs.find(tab => tab.hash === location.hash) || tabs[0];
    tabs.forEach(tab => {
      if (tab === current) tab.setAttribute('aria-current', 'location');
      else tab.removeAttribute('aria-current');
    });
  }
  markSection();
  window.addEventListener('hashchange', markSection);
})();
