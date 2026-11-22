import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAppController } from '../hooks/useAppController';
import { ViewType } from '../types';
import { api, type LoginProvider } from '../services/api';
import { BACKEND_URL } from '../constants';
import { getAssetUrl } from '../config';
import Chat from './Chat';
import { Home, Project, Resources, Skills, Tasks, Tools } from './Views';
import { Drawer, Empty, ErrorMessage, Icon, Sheet, errorText } from './ui';

const tabs = [
  { view: ViewType.HOME, label: '探索', icon: 'home' },
  { view: ViewType.SKILLS, label: '技能', icon: 'spark' },
  { view: ViewType.TOOLS, label: '工具', icon: 'tools' },
  { view: ViewType.SCHEDULED_TASKS, label: '自动任务', icon: 'clock' },
] as const;

function Login() {
  const [providers, setProviders] = useState<LoginProvider[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api
      .listLoginProviders()
      .then((items) => {
        if (!active) return;
        if (items.length === 1 && items[0].id === 'dev')
          window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        else setProviders(items);
      })
      .catch((e) => {
        if (active) setError(errorText(e));
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <main className="h5-login">
      <img src={getAssetUrl('/images/logo.png')} alt="Eido" />
      <div className="h5-eyebrow">YOUR EVERYDAY COPILOT</div>
      <h1>
        每个想法，
        <br />
        都值得向前。
      </h1>
      <p>登录 Eido，让灵感随时发生。</p>
      <div className="h5-form">
        {providers.map((p) => (
          <a
            className="h5-primary"
            key={p.id}
            href={`${BACKEND_URL}/api/v1/auth/login${p.id === 'cas' ? '' : `/${p.id}`}`}
          >
            使用 {p.name} 登录 ↗
          </a>
        ))}
        {!providers.length && !error && <p role="status">正在加载登录方式…</p>}
        <ErrorMessage error={error} />
        {error && <button onClick={() => location.reload()}>重新加载</button>}
      </div>
    </main>
  );
}

export default function App() {
  const app = useAppController({ referencesOpen: false });
  const [drawer, setDrawer] = useState(false);
  const [query, setQuery] = useState('');
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [apiKeyError, setApiKeyError] = useState('');
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [draftPreview, setDraftPreview] = useState(false);
  const isChat = app.activeView === ViewType.CHAT;

  // Follow the visual viewport as software keyboards and browser bars move.
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () => {
      document.documentElement.style.setProperty(
        '--h5-height',
        `${viewport?.height || window.innerHeight}px`,
      );
      document.documentElement.style.setProperty(
        '--h5-offset',
        `${viewport?.offsetTop || 0}px`,
      );
    };
    resize();
    viewport?.addEventListener('resize', resize);
    viewport?.addEventListener('scroll', resize);
    window.addEventListener('resize', resize);
    return () => {
      viewport?.removeEventListener('resize', resize);
      viewport?.removeEventListener('scroll', resize);
      window.removeEventListener('resize', resize);
    };
  }, []);

  const navigate = (view: ViewType) => {
    app.navigationRequestRef.current += 1;
    app.setActiveView(view);
    setDrawer(false);
  };
  const newChat = () => {
    setDrawer(false);
    void app.createNewSession({ projectId: null });
  };
  const title = isChat
    ? app.activeSession?.title || '新的对话'
    : app.activeView === ViewType.PROJECT
      ? app.activeProject?.name || '项目'
      : 'Eido';
  if (app.authLoading)
    return (
      <div className="h5-shell">
        <Empty>正在验证登录状态…</Empty>
      </div>
    );
  if (!app.currentUser)
    return (
      <div className="h5-shell">
        <Login />
      </div>
    );

  return (
    <div className="h5-shell">
      <header className="h5-header">
        <button
          className="h5-icon-button"
          aria-label="打开会话与项目"
          onClick={() => setDrawer(true)}
        >
          <Icon name="menu" />
        </button>
        <button
          className="h5-header-title"
          onClick={() => navigate(ViewType.HOME)}
        >
          {!isChat && app.activeView !== ViewType.PROJECT && (
            <img src={getAssetUrl('/images/logo.png')} alt="" />
          )}
          <span>{title}</span>
        </button>
        <button
          className="h5-icon-button"
          aria-label="新建对话"
          onClick={newChat}
        >
          <Icon name="plus" />
        </button>
      </header>
      <main className="h5-main">
        {app.activeView === ViewType.HOME && <Home app={app} />}
        {app.activeView === ViewType.PROJECT && app.activeProject && (
          <Project key={app.activeProject.id} app={app} />
        )}
        {app.activeView === ViewType.SKILLS && <Skills app={app} />}
        {app.activeView === ViewType.TOOLS && <Tools />}
        {app.activeView === ViewType.SCHEDULED_TASKS && <Tasks app={app} />}
        {isChat && (
          <Chat
            session={app.activeSession}
            skills={app.allSkills}
            onSendMessage={app.addMessageToSession}
            onUpdateMessage={app.updateAssistantMessage}
            onToggleReferences={() => app.setRightPanelOpen(true)}
            rightPanelOpen={app.rightPanelOpen}
            onExecuteAction={app.setExecutingAction}
            onUpdateSessionSkill={app.updateSessionSkill}
            project={app.activeSessionProject}
            projects={app.projects}
            onMoveSession={(id) =>
              app.activeSessionId
                ? app.moveSession(app.activeSessionId, id)
                : Promise.resolve()
            }
            onOpenProject={app.openProject}
            onImportProjectFile={
              app.activeSessionProject && !app.activeSessionProject.archived_at
                ? app.importSessionFileToProject
                : undefined
            }
            onRefreshSession={app.refreshSessionMessages}
            onRunningSessionsChange={app.setRunningSessionIds}
            model={app.activeSession?.model || ''}
            onModelChange={app.updateSessionModel}
            runtimeMode={app.activeSession?.runtimeMode || 'agent'}
            onRuntimeModeChange={app.updateSessionRuntimeMode}
          />
        )}
      </main>
      {!isChat && (
        <nav className="h5-tabs" aria-label="主导航">
          {tabs.map((t) => (
            <button
              key={t.view}
              aria-current={app.activeView === t.view ? 'page' : undefined}
              onClick={() => navigate(t.view)}
            >
              <Icon name={t.icon} size={21} />
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
      )}
      {drawer && (
        <Drawer
          title="Eido"
          onClose={() => setDrawer(false)}
          header={
            <>
              <button className="h5-secondary h5-wide" onClick={newChat}>
                <Icon name="plus" size={18} /> 新建会话
              </button>
            </>
          }
          footer={
            <>
              <div className="h5-account">
                <span className="h5-avatar">
                  {(app.currentUser.username || app.currentUser.user_id)
                    .slice(0, 1)
                    .toUpperCase()}
                </span>
                <strong>
                  {app.currentUser.username || app.currentUser.user_id}
                </strong>
                <button
                  disabled={apiKeyLoading}
                  onClick={async () => {
                    setApiKeyLoading(true);
                    setApiKeyError('');
                    try {
                      setApiKey(await api.getApiKey());
                      setDrawer(false);
                    } catch (e) {
                      setApiKeyError(errorText(e));
                    } finally {
                      setApiKeyLoading(false);
                    }
                  }}
                >
                  API Key
                </button>
                <button onClick={app.handleLogout}>退出</button>
              </div>
              <ErrorMessage error={apiKeyError} />
            </>
          }
        >
          <nav className="h5-drawer-nav" aria-label="抽屉导航">
            {tabs.map((t) => (
              <button
                key={t.view}
                aria-current={app.activeView === t.view ? 'page' : undefined}
                onClick={() => navigate(t.view)}
              >
                <Icon name={t.icon} size={19} />
                <span>
                  {
                    {
                      home: '探索发现',
                      skills: '我的技能',
                      tools: 'MCP 管理',
                      scheduled_tasks: '自动任务',
                    }[t.view]
                  }
                </span>
              </button>
            ))}
          </nav>
          <input
            className="h5-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索项目与会话"
            aria-label="搜索项目与会话"
          />
          <div className="h5-section-title">
            <h3>项目</h3>
            <button
              onClick={() => {
                setDrawer(false);
                setProjectName('');
                setProjectDescription('');
                app.setCreateProjectOpen(true);
              }}
            >
              新建 ＋
            </button>
          </div>
          <div className="h5-list">
            {app.projects
              .filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))
              .map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    setDrawer(false);
                    void app.openProject(p.id);
                  }}
                >
                  <Icon name="folder" />
                  <div>
                    <strong>{p.name}</strong>
                    <small>
                      {p.session_count} 段对话{p.archived_at ? ' · 已归档' : ''}
                    </small>
                  </div>
                  <span>›</span>
                </button>
              ))}
          </div>
          <div className="h5-section-title">
            <h3>最近对话</h3>
          </div>
          <div className="h5-history">
            {app.sessions
              .filter((s) =>
                s.title.toLowerCase().includes(query.toLowerCase()),
              )
              .map((s) => (
                <div
                  key={s.id}
                  className={s.id === app.activeSessionId ? 'is-active' : ''}
                >
                  <button
                    onClick={() => {
                      setDrawer(false);
                      void app.selectSession(s.id);
                    }}
                  >
                    <Icon name="chat" size={18} />
                    <span>{s.title}</span>
                    {app.runningSessionIds.has(s.id) && <small>执行中</small>}
                  </button>
                  <button
                    aria-label={`删除会话 ${s.title}`}
                    onClick={() => {
                      if (confirm(`删除会话「${s.title}」？`))
                        void app.deleteSession(s.id);
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
          </div>
        </Drawer>
      )}
      {isChat && app.rightPanelOpen && app.activeSessionId && (
        <Resources key={app.activeSessionId} app={app} />
      )}
      {app.createProjectOpen && (
        <Sheet title="新建项目" onClose={() => app.setCreateProjectOpen(false)}>
          <form
            className="h5-form"
            onSubmit={(e) => {
              e.preventDefault();
              void app.createProject({
                name: projectName.trim(),
                description: projectDescription.trim(),
              });
            }}
          >
            <label>
              项目名称
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                maxLength={80}
                required
                placeholder="例如：行业研究"
              />
            </label>
            <label>
              简介（可选）
              <textarea
                value={projectDescription}
                onChange={(e) => setProjectDescription(e.target.value)}
                rows={3}
                maxLength={2000}
                placeholder="你希望在这里完成什么？"
              />
            </label>
            <button
              className="h5-primary"
              disabled={app.creatingProject || !projectName.trim()}
            >
              {app.creatingProject ? '创建中…' : '创建项目'}
            </button>
          </form>
        </Sheet>
      )}
      {app.executingAction && (
        <Sheet
          title={app.executingAction.label}
          onClose={() => app.setExecutingAction(null)}
        >
          <div className="h5-segment">
            <button
              aria-pressed={!draftPreview}
              onClick={() => setDraftPreview(false)}
            >
              编辑草稿
            </button>
            <button
              aria-pressed={draftPreview}
              onClick={() => setDraftPreview(true)}
            >
              预览
            </button>
          </div>
          {draftPreview ? (
            <div className="markdown-body h5-skill-detail">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {app.workspaceContent}
              </ReactMarkdown>
            </div>
          ) : (
            <div className="h5-form">
              <textarea
                rows={14}
                aria-label="工作草稿"
                value={app.workspaceContent}
                onChange={(e) => app.setWorkspaceContent(e.target.value)}
              />
            </div>
          )}
          <button
            className="h5-primary h5-wide"
            onClick={app.handleCommitWorkspace}
          >
            提交更改
          </button>
        </Sheet>
      )}
      {apiKey !== null && (
        <Sheet title="我的 API Key" onClose={() => setApiKey(null)}>
          <p className="h5-muted">用于连接 Eido API，请妥善保管。</p>
          <textarea
            className="h5-key"
            readOnly
            value={apiKey}
            aria-label="我的 API Key"
            onFocus={(e) => e.target.select()}
          />
        </Sheet>
      )}
    </div>
  );
}
