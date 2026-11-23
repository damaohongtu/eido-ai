import React, { lazy, Suspense, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAppController } from '../hooks/useAppController';
import { ViewType } from '../types';
import { api, type LoginProvider } from '../services/api';
import { BACKEND_URL } from '../constants';
import Brand from '../components/Brand';
import Sidebar from '../components/Sidebar';
import Chat from './Chat';
import HomeView from '../components/HomeView';
import ProjectView, { CreateProjectModal } from '../components/ProjectView';
import ReferenceArea from '../components/ReferenceArea';
const SkillManager = lazy(() => import('../components/SkillManager'));
const SkillDetailPage = lazy(() => import('../components/SkillDetailPage'));
const ScheduledTasksManager = lazy(
  () => import('../components/ScheduledTasksManager'),
);
const McpToolsView = lazy(() => import('../components/McpToolsView'));
import { Drawer, Empty, ErrorMessage, Icon, Sheet, errorText } from './ui';

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
      <Brand />
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
        <div className="h5-header-title">
          {!isChat && app.activeView !== ViewType.PROJECT && <Brand />}
          {(isChat || app.activeView === ViewType.PROJECT) && (
            <span>{title}</span>
          )}
        </div>
        <span className="h5-icon-button" aria-hidden="true" />
      </header>
      <main className="h5-main">
        {app.activeView === ViewType.HOME && (
          <div className="h5-management h5-home-view">
            <HomeView
              onStartSkill={(skillId) =>
                app.createNewSession({ skillId, projectId: null })
              }
              skills={app.systemSkills}
            />
          </div>
        )}
        {app.activeView === ViewType.PROJECT && app.activeProject && (
          <div className="h5-management">
            <ProjectView
              key={app.activeProject.id}
              project={app.activeProject}
              sessions={app.sessions.filter(
                (session) => session.projectId === app.activeProject.id,
              )}
              files={
                app.projectFilesProjectId === app.activeProject.id
                  ? app.projectFiles
                  : []
              }
              filesLoading={app.projectFilesLoading}
              saving={app.savingProject}
              onNewChat={() =>
                app.createNewSession({ projectId: app.activeProject.id })
              }
              onOpenSession={app.selectSession}
              onMoveSession={app.moveSession}
              onSave={app.saveProject}
              onDelete={app.deleteProject}
              onUploadFile={app.uploadProjectFile}
              onDeleteFile={app.deleteProjectFile}
              onRefreshFiles={() => app.loadProjectFiles(app.activeProject.id)}
            />
          </div>
        )}
        <Suspense fallback={<Empty>正在加载页面…</Empty>}>
          {app.activeView === ViewType.SKILLS && (
            <div className="h5-management">
              <SkillManager
                onSelectSkill={(skill) =>
                  app.createNewSession({ skillId: skill.id, projectId: null })
                }
                onViewDetail={(skill) => {
                  app.setDetailSkill(skill);
                  app.setActiveView(ViewType.SKILL_DETAIL);
                }}
                onRefreshAppSkills={app.refreshSkills}
              />
            </div>
          )}
          {app.activeView === ViewType.SKILL_DETAIL && app.detailSkill && (
            <div className="h5-management">
              <SkillDetailPage
                skill={app.detailSkill}
                onBack={() => {
                  app.setDetailSkill(null);
                  app.setActiveView(ViewType.SKILLS);
                }}
                onUseSkill={(skill) => {
                  app.setDetailSkill(null);
                  void app.createNewSession({
                    skillId: skill.id,
                    projectId: null,
                  });
                }}
                onDeleted={() => {
                  void app.refreshSkills();
                  app.setDetailSkill(null);
                  app.setActiveView(ViewType.SKILLS);
                }}
              />
            </div>
          )}
          {app.activeView === ViewType.TOOLS && (
            <div className="h5-management">
              <McpToolsView />
            </div>
          )}
          {app.activeView === ViewType.SCHEDULED_TASKS && (
            <div className="h5-management">
              <ScheduledTasksManager onOpenSession={app.openTaskSession} />
            </div>
          )}
        </Suspense>
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
      {drawer && (
        <Drawer title="对话与项目" onClose={() => setDrawer(false)}>
          <Sidebar
            activeView={app.activeView}
            onNavigate={navigate}
            sessions={app.sessions}
            projects={app.projects}
            activeProjectId={
              isChat
                ? (app.activeSession?.projectId ?? null)
                : app.activeProjectId
            }
            activeSessionId={app.activeSessionId}
            runningSessionIds={app.runningSessionIds}
            onSelectSession={(id) => {
              setDrawer(false);
              void app.selectSession(id);
            }}
            onNewChat={newChat}
            onNewProject={() => {
              setDrawer(false);
              app.setCreateProjectOpen(true);
            }}
            onSelectProject={(id) => {
              setDrawer(false);
              app.openProject(id);
            }}
            onDeleteSession={(id) => {
              if (confirm('删除这段会话？')) void app.deleteSession(id);
            }}
            currentUser={app.currentUser}
            onLogout={app.handleLogout}
          />
        </Drawer>
      )}
      {isChat && app.rightPanelOpen && app.activeSessionId && (
        <Sheet
          title="资料与执行记录"
          onClose={() => app.setRightPanelOpen(false)}
        >
          <div className="h5-reference">
            <ReferenceArea
              references={app.activeReferences}
              thinkingLog={app.activeThinkingLog}
              sessionId={app.activeSessionId}
              project={app.activeSessionProject}
              projectFiles={
                app.projectFilesProjectId === app.activeSessionProject?.id
                  ? app.projectFiles
                  : []
              }
              projectFilesLoading={app.projectFilesLoading}
              onOpenProject={
                app.activeSessionProject
                  ? () => {
                      app.setRightPanelOpen(false);
                      app.openProject(app.activeSessionProject.id);
                    }
                  : undefined
              }
              onRefreshProjectFiles={
                app.activeSessionProject
                  ? () => app.loadProjectFiles(app.activeSessionProject.id)
                  : undefined
              }
              onImportProjectFile={
                app.activeSessionProject &&
                !app.activeSessionProject.archived_at
                  ? app.importSessionFileToProject
                  : undefined
              }
              onClose={() => app.setRightPanelOpen(false)}
              isFetching={app.activeSession?.messages.some(
                (message) =>
                  message.role === 'assistant' &&
                  message.executionSteps?.some(
                    (step) => step.status === 'running',
                  ),
              )}
            />
          </div>
        </Sheet>
      )}
      <CreateProjectModal
        open={app.createProjectOpen}
        creating={app.creatingProject}
        onClose={() => app.setCreateProjectOpen(false)}
        onCreate={app.createProject}
      />
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
    </div>
  );
}
