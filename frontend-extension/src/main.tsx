import React, { useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import App from '../../frontend/App';
import '../../frontend/index.css';
import './extension.css';

interface BrowserTab {
  id: number;
  title: string;
  url: string;
  active?: boolean;
  windowId?: number;
  favIconUrl?: string;
}

interface BrowserPage {
  title: string;
  url: string;
  canonicalUrl?: string;
  description?: string;
  siteName?: string;
  selection?: string;
  headings?: string[];
  links?: string[];
  text: string;
  truncated?: boolean;
  capturedAt: string;
}

type CapturedPage = BrowserPage & {
  tabId?: number;
};

function sendRuntimeMessage<T>(message: Record<string, unknown>): Promise<T> {
  if (!globalThis.chrome?.runtime?.sendMessage) {
    return Promise.reject(new Error('当前环境不是 Chrome 插件运行时'));
  }

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(err.message));
        return;
      }
      if (response?.error) {
        reject(new Error(response.error));
        return;
      }
      resolve(response as T);
    });
  });
}

function trimForContext(text: string, maxLength: number): string {
  return text.length > maxLength ? `${text.slice(0, maxLength)}\n[内容过长，已截断]` : text;
}

function formatPageForContext(page: CapturedPage, index: number): string {
  const parts = [
    `### 页面 ${index + 1}: ${page.title}`,
    `URL: ${page.url}`,
  ];

  if (page.description) parts.push(`摘要: ${page.description}`);
  if (page.selection) parts.push(`用户选中文本:\n${trimForContext(page.selection, 8000)}`);
  if (page.headings?.length) parts.push(`页面标题结构:\n${page.headings.slice(0, 40).join('\n')}`);
  parts.push(`正文:\n${trimForContext(page.text, 24000)}`);
  if (page.truncated) parts.push('注: 页面正文在浏览器采集阶段已截断。');

  return parts.join('\n\n');
}

function buildBrowserContext(pages: CapturedPage[]): string {
  if (!pages.length) return '';
  return [
    '## 浏览器网页上下文',
    '以下内容来自用户通过 Chrome 插件显式选择的网页。回答时请优先引用这些页面内容；如果信息不足，请说明缺口。',
    ...pages.map(formatPageForContext),
  ].join('\n\n---\n\n');
}

const BrowserContextPanel: React.FC<{
  pages: CapturedPage[];
  tabs: BrowserTab[];
  loading: boolean;
  error: string | null;
  onCaptureActive: () => void;
  onCaptureTab: (tabId: number) => void;
  onRemovePage: (url: string) => void;
  onClearPages: () => void;
  onRefreshTabs: () => void;
  onOpenDebug: () => void;
}> = ({
  pages,
  tabs,
  loading,
  error,
  onCaptureActive,
  onCaptureTab,
  onRemovePage,
  onClearPages,
  onRefreshTabs,
  onOpenDebug,
}) => {
  const [open, setOpen] = useState(false);

  return (
    <div className="eido-extension-context">
      <button
        type="button"
        className="eido-extension-context__toggle"
        onClick={() => setOpen((value) => !value)}
        title="网页上下文"
      >
        网页上下文 {pages.length ? `(${pages.length})` : ''}
      </button>

      {open ? (
        <section className="eido-extension-context__panel">
          <header className="eido-extension-context__header">
            <div>
              <h2>网页上下文</h2>
              <p>选择当前页或其他标签页，发送消息时会自动附加给 Eido。</p>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="关闭">×</button>
          </header>

          <div className="eido-extension-context__actions">
            <button type="button" onClick={onCaptureActive} disabled={loading}>读取当前页</button>
            <button type="button" onClick={onRefreshTabs} disabled={loading}>刷新标签</button>
            <button type="button" onClick={onClearPages} disabled={!pages.length}>清空</button>
            <button type="button" onClick={onOpenDebug}>调试控制台</button>
          </div>

          {error ? <div className="eido-extension-context__error">{error}</div> : null}

          <div className="eido-extension-context__section">
            <div className="eido-extension-context__label">已加入分析</div>
            {pages.length ? (
              <div className="eido-extension-context__list">
                {pages.map((page) => (
                  <div className="eido-extension-context__item" key={`${page.url}-${page.capturedAt}`}>
                    <div className="eido-extension-context__item-main">
                      <strong title={page.title}>{page.title}</strong>
                      <span title={page.url}>{page.url}</span>
                    </div>
                    <button type="button" onClick={() => onRemovePage(page.url)} aria-label="移除">×</button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="eido-extension-context__empty">尚未加入网页</div>
            )}
          </div>

          <div className="eido-extension-context__section">
            <div className="eido-extension-context__label">打开的标签页</div>
            <div className="eido-extension-context__tab-list">
              {tabs.map((tab) => (
                <button
                  type="button"
                  className="eido-extension-context__tab"
                  key={tab.id}
                  onClick={() => onCaptureTab(tab.id)}
                  disabled={loading}
                  title={tab.url}
                >
                  <span>{tab.active ? '当前' : '读取'}</span>
                  <strong>{tab.title}</strong>
                </button>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
};

const ExtensionApp: React.FC = () => {
  const [tabs, setTabs] = useState<BrowserTab[]>([]);
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshTabs = async () => {
    try {
      const response = await sendRuntimeMessage<{ tabs: BrowserTab[] }>({ type: 'EIDO_LIST_TABS' });
      setTabs(response.tabs);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取标签页失败');
    }
  };

  const addPage = (page: CapturedPage) => {
    setPages((prev) => [page, ...prev.filter((item) => item.url !== page.url)].slice(0, 6));
  };

  const captureActive = async () => {
    setLoading(true);
    try {
      const response = await sendRuntimeMessage<{ page: BrowserPage }>({ type: 'EIDO_CAPTURE_ACTIVE_TAB' });
      addPage(response.page);
      setError(null);
      await refreshTabs();
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取当前页失败');
    } finally {
      setLoading(false);
    }
  };

  const captureTab = async (tabId: number) => {
    setLoading(true);
    try {
      const response = await sendRuntimeMessage<{ page: BrowserPage }>({ type: 'EIDO_CAPTURE_TAB', tabId });
      addPage({ ...response.page, tabId });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取标签页失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshTabs();
    captureActive();
  }, []);

  const browserContext = useMemo(() => buildBrowserContext(pages), [pages]);

  const openDebug = () => {
    sendRuntimeMessage<{ ok: boolean }>({ type: 'EIDO_OPEN_DEBUG_PAGE' }).catch((err) => {
      console.error('打开调试控制台失败', err);
    });
  };

  return (
    <div className="eido-extension-shell">
      <App
        browserContext={browserContext}
        extensionMode
        onAuthRequired={(loginUrl) => {
          console.warn('Eido extension auth required', { loginUrl });
        }}
      />
      <BrowserContextPanel
        pages={pages}
        tabs={tabs}
        loading={loading}
        error={error}
        onCaptureActive={captureActive}
        onCaptureTab={captureTab}
        onRemovePage={(url) => setPages((prev) => prev.filter((page) => page.url !== url))}
        onClearPages={() => setPages([])}
        onRefreshTabs={refreshTabs}
        onOpenDebug={openDebug}
      />
    </div>
  );
};

class ExtensionErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Eido extension React error', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="eido-extension-fatal">
        <div>
          <h1>插件加载失败</h1>
          <p>{this.state.error.message}</p>
          <button
            type="button"
            onClick={() => sendRuntimeMessage({ type: 'EIDO_OPEN_DEBUG_PAGE' })}
          >
            打开调试控制台
          </button>
        </div>
      </div>
    );
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ExtensionErrorBoundary>
      <ExtensionApp />
    </ExtensionErrorBoundary>
  </React.StrictMode>,
);
