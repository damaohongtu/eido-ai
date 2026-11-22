import React from 'react';
import { ViewType } from './types';
import { useAppController } from './hooks/useAppController';
import Sidebar from './components/Sidebar';
import LoginView from './components/LoginView';
import ChatArea from './components/ChatArea';
import ReferenceArea from './components/ReferenceArea';
import HomeView from './components/HomeView';
import SkillManager from './components/SkillManager';
import SkillDetailPage from './components/SkillDetailPage';
import ScheduledTasksManager from './components/ScheduledTasksManager';
import ProjectView, { CreateProjectModal } from './components/ProjectView';
import McpToolsView from './components/McpToolsView';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const App: React.FC = () => {
  const {
    authLoading,
    currentUser,
    navigationRequestRef,
    activeView,
    setActiveView,
    sessions,
    projects,
    activeSession,
    activeProjectId,
    activeSessionId,
    runningSessionIds,
    selectSession,
    createNewSession,
    setCreateProjectOpen,
    openProject,
    deleteSession,
    handleLogout,
    loading,
    systemSkills,
    activeProject,
    projectFilesProjectId,
    projectFiles,
    projectFilesLoading,
    savingProject,
    moveSession,
    saveProject,
    deleteProject,
    uploadProjectFile,
    deleteProjectFile,
    loadProjectFiles,
    allSkills,
    addMessageToSession,
    updateAssistantMessage,
    rightPanelOpen,
    setRightPanelOpen,
    setExecutingAction,
    updateSessionSkill,
    activeSessionProject,
    importSessionFileToProject,
    refreshSessionMessages,
    setRunningSessionIds,
    updateSessionModel,
    updateSessionRuntimeMode,
    activeReferences,
    activeThinkingLog,
    refreshSkills,
    setDetailSkill,
    detailSkill,
    openTaskSession,
    executingAction,
    handleCommitWorkspace,
    workspaceContent,
    setWorkspaceContent,
    createProjectOpen,
    creatingProject,
    createProject
  } = useAppController();

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-400 mx-auto mb-3"></div>
          <p className="text-gray-400 text-sm">正在验证登录状态...</p>
        </div>
      </div>
    );
  }

  if (!currentUser) return <LoginView />;

  return (
    <div className="flex h-screen w-full overflow-hidden text-gray-900 font-sans">
      <Sidebar 
        activeView={activeView}
        onNavigate={(view) => {
          navigationRequestRef.current += 1;
          setActiveView(view);
        }}
        sessions={sessions}
        projects={projects}
        activeProjectId={activeView === ViewType.CHAT ? activeSession?.projectId ?? null : activeProjectId}
        activeSessionId={activeSessionId}
        runningSessionIds={runningSessionIds}
        onSelectSession={(id) => { selectSession(id); }}
        onNewChat={() => createNewSession({ projectId: null })}
        onNewProject={() => setCreateProjectOpen(true)}
        onSelectProject={openProject}
        onDeleteSession={deleteSession}
        currentUser={currentUser!}
        onLogout={handleLogout}
      />

      <main className="flex-1 flex flex-col relative min-w-0 bg-white shadow-lg shadow-gray-200/30">
        {loading && activeView === ViewType.HOME ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-500 mx-auto mb-4"></div>
              <p className="text-gray-500">加载系统技能中...</p>
            </div>
          </div>
        ) : (
          <>
            {activeView === ViewType.HOME && (
              <HomeView
                onStartSkill={(skillId) => createNewSession({ skillId, projectId: null })}
                skills={systemSkills}
              />
            )}

        {activeView === ViewType.PROJECT && activeProject && (
          <ProjectView
            project={activeProject}
            sessions={sessions.filter(session => session.projectId === activeProject.id)}
            files={projectFilesProjectId === activeProject.id ? projectFiles : []}
            filesLoading={projectFilesLoading}
            saving={savingProject}
            onNewChat={() => createNewSession({ projectId: activeProject.id })}
            onOpenSession={selectSession}
            onMoveSession={moveSession}
            onSave={saveProject}
            onDelete={deleteProject}
            onUploadFile={uploadProjectFile}
            onDeleteFile={deleteProjectFile}
            onRefreshFiles={() => loadProjectFiles(activeProject.id)}
          />
        )}

        {activeView === ViewType.CHAT && (
          <div className="flex h-full w-full overflow-hidden">
             <ChatArea 
                session={activeSession}
                skills={allSkills}
                onSendMessage={addMessageToSession}
                onUpdateMessage={updateAssistantMessage}
                onToggleReferences={() => setRightPanelOpen(!rightPanelOpen)}
                rightPanelOpen={rightPanelOpen}
                onExecuteAction={setExecutingAction}
                onUpdateSessionSkill={updateSessionSkill}
                project={activeSessionProject}
                projects={projects}
                onMoveSession={(projectId) => activeSessionId ? moveSession(activeSessionId, projectId) : Promise.resolve()}
                onOpenProject={openProject}
                onImportProjectFile={activeSessionProject && !activeSessionProject.archived_at ? importSessionFileToProject : undefined}
                onRefreshSession={refreshSessionMessages}
                onRunningSessionsChange={setRunningSessionIds}
                model={activeSession?.model || ''}
                onModelChange={updateSessionModel}
                runtimeMode={activeSession?.runtimeMode || 'agent'}
                onRuntimeModeChange={updateSessionRuntimeMode}
             />
             {rightPanelOpen && (
             <ReferenceArea
               references={activeReferences}
               thinkingLog={activeThinkingLog}
               sessionId={activeSessionId}
               project={activeSessionProject}
               projectFiles={projectFilesProjectId === activeSessionProject?.id ? projectFiles : []}
               projectFilesLoading={projectFilesLoading}
               onOpenProject={activeSessionProject ? () => openProject(activeSessionProject.id) : undefined}
               onRefreshProjectFiles={activeSessionProject ? () => loadProjectFiles(activeSessionProject.id) : undefined}
               onImportProjectFile={activeSessionProject && !activeSessionProject.archived_at ? importSessionFileToProject : undefined}
               onClose={() => setRightPanelOpen(false)}
               isFetching={activeSession?.messages.some(m => m.role === 'assistant' && m.executionSteps?.some(s => s.status === 'running'))}
             />
             )}
          </div>
        )}

        {activeView === ViewType.SKILLS && (
          <SkillManager
            onSelectSkill={(skill) => createNewSession({ skillId: skill.id, projectId: null })}
            onViewDetail={(skill) => {
              setDetailSkill(skill);
              setActiveView(ViewType.SKILL_DETAIL);
            }}
            onRefreshAppSkills={refreshSkills}
          />
        )}

        {activeView === ViewType.TOOLS && <McpToolsView />}

        {activeView === ViewType.SKILL_DETAIL && detailSkill && (
          <SkillDetailPage
            skill={detailSkill}
            onBack={() => {
              setDetailSkill(null);
              setActiveView(ViewType.SKILLS);
            }}
            onUseSkill={(skill) => {
              setDetailSkill(null);
              createNewSession({ skillId: skill.id, projectId: null });
            }}
            onDeleted={() => {
              refreshSkills();
              setDetailSkill(null);
              setActiveView(ViewType.SKILLS);
            }}
          />
        )}

        {activeView === ViewType.SCHEDULED_TASKS && (
          <ScheduledTasksManager onOpenSession={openTaskSession} />
        )}

          </>
        )}

        {executingAction && (
          <div className="fixed inset-0 z-[100] flex flex-col bg-white">
            <header className="h-16 border-b border-gray-100 px-8 flex items-center justify-between bg-white shrink-0">
              <div className="flex items-center space-x-6">
                <button onClick={() => setExecutingAction(null)} className="flex items-center space-x-2 px-3 py-1.5 hover:bg-gray-100 rounded-xl text-gray-500 hover:text-gray-800 transition-all font-bold text-sm">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" /></svg>
                  <span>返回</span>
                </button>
                <div className="flex items-center space-x-3">
                  <span className="text-xl">{executingAction.icon}</span>
                  <h2 className="text-sm font-black text-gray-900 uppercase tracking-tight">{executingAction.label}</h2>
                </div>
              </div>
              <div className="flex items-center space-x-4">
                <button onClick={handleCommitWorkspace} className="px-6 py-2 bg-gray-700 text-white rounded-xl text-[10px] font-black uppercase hover:bg-gray-800 transition-all">提交更改</button>
              </div>
            </header>
            <div className="flex-1 flex overflow-hidden">
              <textarea
                value={workspaceContent}
                onChange={(e) => setWorkspaceContent(e.target.value)}
                className="flex-1 p-12 lg:p-24 outline-none resize-none font-mono text-lg text-gray-700 leading-relaxed"
                placeholder="完成你的分析..."
              />
              <div className="flex-1 overflow-y-auto bg-gray-50/50 p-12 lg:p-24 border-l border-gray-100">
                <div className="max-w-3xl mx-auto markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{workspaceContent}</ReactMarkdown>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
      <CreateProjectModal
        open={createProjectOpen}
        creating={creatingProject}
        onClose={() => setCreateProjectOpen(false)}
        onCreate={createProject}
      />
    </div>
  );
};

export default App;
