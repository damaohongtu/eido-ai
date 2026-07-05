const KEY = 'eido_debug_logs';
const logsEl = document.getElementById('logs');
const metaEl = document.getElementById('meta');

function getLogs() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ [KEY]: [] }, (result) => {
      resolve(Array.isArray(result[KEY]) ? result[KEY] : []);
    });
  });
}

function setLogs(logs) {
  return chrome.storage.local.set({ [KEY]: logs });
}

function renderLog(log) {
  const item = document.createElement('section');
  item.className = `log level-${log.level || 'log'}`;

  const header = document.createElement('div');
  header.className = 'log-header';
  header.innerHTML = `<span>${log.level || 'log'} · ${log.time || ''}</span><span>${log.page || ''}</span>`;

  const pre = document.createElement('pre');
  pre.textContent = log.message || '';

  item.appendChild(header);
  item.appendChild(pre);
  return item;
}

async function render() {
  const logs = await getLogs();
  logsEl.innerHTML = '';
  metaEl.textContent = `${logs.length} 条日志 · 扩展 ID: ${chrome.runtime.id}`;

  if (!logs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '暂无插件日志。打开侧边栏并复现问题后，再回到这里刷新。';
    logsEl.appendChild(empty);
    return;
  }

  logs.slice().reverse().forEach((log) => logsEl.appendChild(renderLog(log)));
}

document.getElementById('refresh').addEventListener('click', render);

document.getElementById('clear').addEventListener('click', async () => {
  await setLogs([]);
  await render();
});

document.getElementById('copy').addEventListener('click', async () => {
  const logs = await getLogs();
  await navigator.clipboard.writeText(JSON.stringify(logs, null, 2));
});

document.getElementById('open-extensions').addEventListener('click', () => {
  chrome.tabs.create({ url: `chrome://extensions/?id=${chrome.runtime.id}` });
});

render();
