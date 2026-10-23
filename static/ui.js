/* Display-only legacy messages and active anchor navigation; no business state. */
(function () {
  'use strict';
  const phrases = JSON.parse(document.getElementById('ui-display-phrases')?.textContent || '{}');
  const labels = JSON.parse(document.getElementById('ui-display-labels')?.textContent || '{}');
  window.displayMessage = value => {
    let text = String(value ?? '');
    for (const [original, translated] of Object.entries(phrases).sort((a,b)=>b[0].length-a[0].length)) text = text.split(original).join(translated);
    return text.replace(/登录尝试过多，请在 (\d+) 秒后重试。/g, '登入嘗試次數過多，請在 $1 秒後重試。')
      .replace(/已成功删除 (\d+) 个服务器临时文件。/g, '已刪除 $1 個伺服器暫存檔案。')
      .replace(/第 (\d+) 行错误：/g, '第 $1 行錯誤：');
  };
  window.displayLabel = value => Object.hasOwn(labels, value) ? labels[value] : String(value ?? '');
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
