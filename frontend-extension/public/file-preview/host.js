const PREVIEW_KEY_PREFIX = 'eido_html_preview_';
const frame = document.getElementById('preview');
const status = document.getElementById('status');
const filename = document.getElementById('filename');

function showError(message) {
  status.hidden = false;
  status.textContent = message;
}

async function loadPreview() {
  const token = location.hash.slice(1);
  if (!/^[a-f0-9-]{36}$/i.test(token)) {
    showError('预览地址无效，请从 Eido 重新打开文件。');
    return;
  }

  const key = `${PREVIEW_KEY_PREFIX}${token}`;
  const stored = await chrome.storage.session.get(key);
  const payload = stored[key];
  if (typeof payload?.html !== 'string') {
    showError('预览内容已失效，请从 Eido 重新打开文件。');
    return;
  }

  filename.textContent = payload.filename || 'HTML 文件预览';
  document.title = `${filename.textContent} - Eido`;

  const onReady = async (event) => {
    if (event.source !== frame.contentWindow || event.data?.type !== 'EIDO_PREVIEW_READY') return;
    window.removeEventListener('message', onReady);
    frame.contentWindow.postMessage({ type: 'EIDO_RENDER_HTML', html: payload.html }, '*');
    status.hidden = true;
    await chrome.storage.session.remove(key);
  };

  window.addEventListener('message', onReady);
  frame.src = chrome.runtime.getURL('file-preview/sandbox.html');
}

loadPreview().catch((error) => {
  showError(error instanceof Error ? error.message : String(error));
});
