import {
  buildNativeLauncherRequest,
  NATIVE_LAUNCHER_HOST,
  nativeLauncherTimeout,
  normalizeNativeLauncherError,
} from './native-launcher-protocol.js';

const INVALID_TAB_URL = /^(chrome|edge|brave|vivaldi|about|devtools):/i;
const NATIVE_MESSAGE_TYPES = new Set([
  'EIDO_NATIVE_LAUNCHER_PING',
  'EIDO_OPENCODE_DETECT',
  'EIDO_OPENCODE_SELECT_DIRECTORY',
  'EIDO_OPENCODE_LAUNCH',
  'EIDO_OPENCODE_STATUS',
]);

chrome.runtime.onInstalled.addListener(() => {
  if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
  }

  chrome.contextMenus?.removeAll(() => {
    chrome.contextMenus.create({
      id: 'eido-open-debug-console',
      title: '打开 Eido 插件调试控制台',
      contexts: ['action'],
    });
  });
});

chrome.action.onClicked.addListener((tab) => {
  if (tab.windowId && chrome.sidePanel?.open) {
    chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => undefined);
  }
});

chrome.contextMenus?.onClicked.addListener((info) => {
  if (info.menuItemId === 'eido-open-debug-console') {
    chrome.tabs.create({ url: chrome.runtime.getURL('debug.html') });
  }
});

function isReadableTab(tab) {
  return Boolean(tab?.id && tab.url && !INVALID_TAB_URL.test(tab.url));
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: 'EIDO_PING' });
    return true;
  } catch {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content.js'],
      });
      return true;
    } catch {
      return false;
    }
  }
}

async function captureTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!isReadableTab(tab)) {
    throw new Error('该标签页不允许插件读取');
  }

  const ready = await ensureContentScript(tabId);
  if (!ready) {
    throw new Error('无法向该标签页注入读取脚本');
  }

  return chrome.tabs.sendMessage(tabId, { type: 'EIDO_EXTRACT_PAGE' });
}

function sendNativeLauncherMessage(message) {
  return new Promise((resolve) => {
    let request;
    try {
      request = buildNativeLauncherRequest(message);
    } catch (error) {
      resolve(normalizeNativeLauncherError(error));
      return;
    }

    let settled = false;
    let port;
    const finish = (response) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        port?.disconnect();
      } catch {
        // The native process may already have closed its side of the port.
      }
      resolve(response);
    };
    const timer = setTimeout(() => {
      finish({
        ok: false,
        code: 'NATIVE_REQUEST_TIMEOUT',
        message: request.command === 'select_directory'
          ? '文件夹选择器等待超时，请重试'
          : '本机启动组件响应超时，请重试',
      });
    }, nativeLauncherTimeout(request.command));

    try {
      port = chrome.runtime.connectNative(NATIVE_LAUNCHER_HOST);
      port.onMessage.addListener((response) => {
        if (!response || typeof response !== 'object') {
          finish({ ok: false, code: 'NATIVE_HOST_ERROR', message: '本机启动组件未返回有效结果' });
          return;
        }
        finish(response);
      });
      port.onDisconnect.addListener(() => {
        if (settled) return;
        const runtimeError = chrome.runtime.lastError;
        finish(normalizeNativeLauncherError(
          runtimeError || new Error('本机启动组件在返回结果前已退出')
        ));
      });
      port.postMessage(request);
    } catch (error) {
      finish(normalizeNativeLauncherError(error));
    }
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (NATIVE_MESSAGE_TYPES.has(message?.type)) {
    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, code: 'NATIVE_HOST_FORBIDDEN', message: '不允许的调用来源' });
      return false;
    }
    sendNativeLauncherMessage(message).then(sendResponse);
    return true;
  }

  if (message?.type === 'EIDO_LIST_TABS') {
    chrome.tabs.query({}).then((tabs) => {
      sendResponse({
        tabs: tabs
          .filter(isReadableTab)
          .map((tab) => ({
            id: tab.id,
            title: tab.title || tab.url || '未命名页面',
            url: tab.url || '',
            active: tab.active,
            windowId: tab.windowId,
            favIconUrl: tab.favIconUrl,
          })),
      });
    }).catch((error) => sendResponse({ error: error.message }));
    return true;
  }

  if (message?.type === 'EIDO_CAPTURE_TAB') {
    const tabId = message.tabId;
    captureTab(tabId)
      .then((page) => sendResponse({ page }))
      .catch((error) => sendResponse({ error: error.message }));
    return true;
  }

  if (message?.type === 'EIDO_CAPTURE_ACTIVE_TAB') {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => {
        if (!tab?.id) throw new Error('未找到当前活动标签页');
        return captureTab(tab.id);
      })
      .then((page) => sendResponse({ page }))
      .catch((error) => sendResponse({ error: error.message }));
    return true;
  }

  if (message?.type === 'EIDO_OPEN_DEBUG_PAGE') {
    chrome.tabs.create({ url: chrome.runtime.getURL('debug.html') })
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ error: error.message }));
    return true;
  }

  return false;
});
