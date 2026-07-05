(function () {
  const KEY = 'eido_debug_logs';
  const MAX_LOGS = 300;

  function safeStringify(value) {
    if (value instanceof Error) {
      return `${value.name}: ${value.message}\n${value.stack || ''}`;
    }
    if (typeof value === 'string') return value;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }

  function appendLog(level, args) {
    const entry = {
      level,
      page: location.href,
      message: Array.from(args).map(safeStringify).join(' '),
      time: new Date().toISOString(),
      userAgent: navigator.userAgent,
    };

    try {
      chrome.storage.local.get({ [KEY]: [] }, (result) => {
        const logs = Array.isArray(result[KEY]) ? result[KEY] : [];
        logs.push(entry);
        chrome.storage.local.set({ [KEY]: logs.slice(-MAX_LOGS) });
      });
    } catch {
      try {
        const logs = JSON.parse(localStorage.getItem(KEY) || '[]');
        logs.push(entry);
        localStorage.setItem(KEY, JSON.stringify(logs.slice(-MAX_LOGS)));
      } catch {}
    }
  }

  ['log', 'warn', 'error'].forEach((level) => {
    const original = console[level];
    console[level] = function () {
      appendLog(level, arguments);
      return original.apply(console, arguments);
    };
  });

  window.addEventListener('error', (event) => {
    appendLog('error', [event.message, event.filename, event.lineno, event.colno, event.error]);
  });

  window.addEventListener('unhandledrejection', (event) => {
    appendLog('error', ['Unhandled promise rejection', event.reason]);
  });

  window.__EIDO_APPEND_DEBUG_LOG__ = appendLog;
})();
