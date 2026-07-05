import React, { useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { createRoot } from 'react-dom/client';
import { unstableSetRender } from 'antd-mobile';
import App from '../../frontend-mobile/src/App';
import '../../frontend-mobile/src/index.css';
import './extension.css';

unstableSetRender((node, container) => {
  const target = container as Element & { _reactRoot?: ReturnType<typeof createRoot> };
  target._reactRoot ||= createRoot(target);
  const root = target._reactRoot;
  root.render(node);
  return async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    root.unmount();
  };
});

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
  open: boolean;
  pages: CapturedPage[];
  tabs: BrowserTab[];
  loading: boolean;
  error: string | null;
  onCaptureActive: () => void;
  onCaptureTab: (tabId: number) => void;
  onRemovePage: (url: string) => void;
  onClearPages: () => void;
  onRefreshTabs: () => void;
  onClose: () => void;
}> = ({
  open,
  pages,
  tabs,
  loading,
  error,
  onCaptureActive,
  onCaptureTab,
  onRemovePage,
  onClearPages,
  onRefreshTabs,
  onClose,
}) => {
  if (!open) return null;
  return (
    <div className="eido-extension-context">
        <section className="eido-extension-context__panel">
          <header className="eido-extension-context__header">
            <div>
              <h2>网页上下文</h2>
              <p>选择当前页或其他标签页，发送消息时会自动附加给 Eido。</p>
            </div>
            <button type="button" onClick={onClose} aria-label="关闭">×</button>
          </header>

          <div className="eido-extension-context__actions">
            <button type="button" onClick={onCaptureActive} disabled={loading}>读取当前页</button>
            <button type="button" onClick={onRefreshTabs} disabled={loading}>刷新标签</button>
            <button type="button" onClick={onClearPages} disabled={!pages.length}>清空</button>
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
    </div>
  );
};

const BrowserContextButton: React.FC<{
  count: number;
  loading: boolean;
  onClick: () => void;
}> = ({ count, loading, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={loading}
    className="eido-extension-context-inline-button eido-mobile-icon-button mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-gray-500 active:bg-gray-100 disabled:opacity-40"
    aria-label="网页上下文"
    title="网页上下文"
  >
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 3a9 9 0 100 18 9 9 0 000-18z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M3.6 9h16.8M3.6 15h16.8M12 3c2 2.4 3 5.4 3 9s-1 6.6-3 9M12 3c-2 2.4-3 5.4-3 9s1 6.6 3 9"
      />
    </svg>
    {count > 0 ? <span className="eido-extension-context-inline-badge">{count}</span> : null}
  </button>
);

const DebugSettingsItem: React.FC<{ onClick: () => void }> = ({ onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="flex w-full items-center justify-between px-5 py-4 text-left active:bg-gray-50"
  >
    <div>
      <div className="text-[15px] font-semibold text-gray-800">插件调试控制台</div>
      <div className="text-xs text-gray-400">查看插件运行日志和错误信息</div>
    </div>
    <svg className="h-4 w-4 shrink-0 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
    </svg>
  </button>
);

const ExtensionApp: React.FC = () => {
  const [tabs, setTabs] = useState<BrowserTab[]>([]);
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);

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
        browserContextControl={
          <BrowserContextButton
            count={pages.length}
            loading={loading}
            onClick={() => setContextPanelOpen(true)}
          />
        }
        debugControl={<DebugSettingsItem onClick={openDebug} />}
        extensionMode
        onAuthRequired={(loginUrl) => {
          console.warn('Eido extension auth required', { loginUrl });
        }}
      />
      <BrowserContextPanel
        open={contextPanelOpen}
        pages={pages}
        tabs={tabs}
        loading={loading}
        error={error}
        onCaptureActive={captureActive}
        onCaptureTab={captureTab}
        onRemovePage={(url) => setPages((prev) => prev.filter((page) => page.url !== url))}
        onClearPages={() => setPages([])}
        onRefreshTabs={refreshTabs}
        onClose={() => setContextPanelOpen(false)}
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
