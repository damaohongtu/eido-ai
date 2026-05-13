
import React, { useState, useEffect, useMemo } from 'react';
import { ViewType, Skill, Message, ChatSession, Reference, SkillAction } from './types';
import { INITIAL_CHAT_STATE } from './constants';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import ReferenceArea from './components/ReferenceArea';
import HomeView from './components/HomeView';
import SkillManager from './components/SkillManager';
import SkillDetailPage from './components/SkillDetailPage';
import ScheduledTasksManager from './components/ScheduledTasksManager';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, hydrateSession, summaryToSession } from './services/api';
import { BACKEND_URL } from './constants';

const STORAGE_ACTIVE_SESSION_KEY = 'eido_active_session_id';

function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

function removeStorage(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {}
}

/** 修复从缓存恢复时处于 running 状态的步骤（连接已断开，不会再更新） */
function fixStaleRunningSteps(sessions: ChatSession[]): ChatSession[] {
  return sessions.map(session => ({
    ...session,
    messages: session.messages.map(msg => ({
      ...msg,
      executionSteps: msg.executionSteps?.map(step =>
        step.status === 'running' ? { ...step, status: 'waiting' as const } : step
      )
    }))
  }));
}

/** 从前端 Message 中抽取需要持久化的 extra 字段。 */
function buildMessageExtra(msg: Message): Record<string, any> {
  const extra: Record<string, any> = {};
  if (msg.thinking) extra.thinking = msg.thinking;
  if (msg.thinkingLog && msg.thinkingLog.length) extra.thinkingLog = msg.thinkingLog;
  if (msg.executionSteps && msg.executionSteps.length) extra.executionSteps = msg.executionSteps;
  if (msg.workflowMermaid) extra.workflowMermaid = msg.workflowMermaid;
  if (msg.references && msg.references.length) extra.references = msg.references;
  if (msg.pendingConfirmation) extra.pendingConfirmation = msg.pendingConfirmation;
  return extra;
}

const App: React.FC = () => {
  const [authChecked, setAuthChecked] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ user_id: string; username: string } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has('login')) {
      params.delete('login');
      const clean = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (clean ? `?${clean}` : ''));
    }

    api.checkAuth().then(user => {
      if (!user) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      setCurrentUser(user);
      setAuthChecked(true);
      // 异步预热 sandbox 容器；失败时不阻塞登录后续流程，
      // local/单镜像模式后端会返回 ready=true 直接 no-op
      api.warmupSandbox().catch(() => undefined);
    });
  }, []);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() =>
    readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null)
  );

  const [activeView, setActiveView] = useState<ViewType>(() => {
    const cachedId = readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null);
    return cachedId ? ViewType.CHAT : ViewType.HOME;
  });
  const [userSkills, setUserSkills] = useState<Skill[]>([]);
  const [systemSkills, setSystemSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);

  // Skill page view state
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);

  // Workspace (Report Editor) State
  const [executingAction, setExecutingAction] = useState<SkillAction | null>(null);
  const [workspaceContent, setWorkspaceContent] = useState('');
  const [isPreviewMode, setIsPreviewMode] = useState(false);

  // 持久化当前激活 session ID（仅作"上次打开"记忆，不再缓存全部消息）
  useEffect(() => {
    if (activeSessionId) {
      writeStorage(STORAGE_ACTIVE_SESSION_KEY, activeSessionId);
    } else {
      removeStorage(STORAGE_ACTIVE_SESSION_KEY);
    }
  }, [activeSessionId]);

  // 鉴权完成后从后端拉取会话列表
  useEffect(() => {
    if (!authChecked) return;
    (async () => {
      try {
        const list = await api.listSessions();
        const summaries = list.map(summaryToSession);
        setSessions(summaries);

        const cachedId = readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null);
        const target = cachedId && summaries.find(s => s.id === cachedId)
          ? cachedId
          : null;
        if (target) {
          try {
            const detail = await api.getSession(target);
            const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
            setSessions(prev => prev.map(s => s.id === target ? hydrated : s));
            setActiveSessionId(target);
            setActiveView(ViewType.CHAT);
          } catch (err) {
            console.warn('恢复上次会话失败:', err);
            setActiveSessionId(null);
            removeStorage(STORAGE_ACTIVE_SESSION_KEY);
          }
        }
      } catch (err) {
        console.error('加载会话列表失败:', err);
      }
    })();
  }, [authChecked]);

  // 加载系统技能和用户技能
  useEffect(() => {
    const loadSkills = async () => {
      setLoading(true);
      try {
        const [systemResult, userResult] = await Promise.all([
          api.getSkills({ is_system: true, limit: 100 }),
          api.getSkills({ is_system: false, limit: 100 }),
        ]);
        setSystemSkills(systemResult.items);
        setUserSkills(userResult.items);
      } catch (error) {
        console.error('加载技能失败:', error);
      } finally {
        setLoading(false);
      }
    };
    loadSkills();
  }, []);

  const activeSession = useMemo(() =>
    sessions.find(s => s.id === activeSessionId) || null
  , [sessions, activeSessionId]);

  const allSkills = useMemo(() => [...systemSkills, ...userSkills], [systemSkills, userSkills]);

  const refreshSkills = async () => {
    try {
      const [systemResult, userResult] = await Promise.all([
        api.getSkills({ is_system: true, limit: 100 }),
        api.getSkills({ is_system: false, limit: 100 }),
      ]);
      setSystemSkills(systemResult.items);
      setUserSkills(userResult.items);
    } catch (error) {
      console.error('刷新技能失败:', error);
    }
  };

  // Sync editor content with last assistant output
  useEffect(() => {
    if (executingAction && activeSession) {
      const lastAssistantMessage = [...activeSession.messages].reverse().find(m => m.role === 'assistant');
      setWorkspaceContent(lastAssistantMessage?.content || '');
    }
  }, [executingAction, activeSessionId]);

  /** 切换激活会话；若该会话尚未拉取过完整消息则按需拉取一次。 */
  const selectSession = async (id: string) => {
    const target = sessions.find(s => s.id === id);
    if (target && target.messages.length === 0) {
      try {
        const detail = await api.getSession(id);
        const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
        setSessions(prev => prev.map(s => s.id === id ? hydrated : s));
      } catch (err) {
        console.error('加载会话消息失败:', err);
        return;
      }
    }
    setActiveSessionId(id);
    setActiveView(ViewType.CHAT);
  };

  const createNewSession = async (skillId?: string) => {
    try {
      const created = await api.createSession({ skill_id: skillId ?? null });
      // 初始欢迎语是前端 UI 状态，不写入后端；id 按会话生成，避免本地渲染 key 冲突
      const initialMessages: Message[] = INITIAL_CHAT_STATE.map((m, i) => ({
        ...m,
        id: `${created.id}-init-${i}`,
        timestamp: Date.now(),
      }));
      const newSession: ChatSession = {
        id: created.id,
        title: created.title || '新建会话',
        skillId: created.skill_id || skillId,
        messages: initialMessages,
        updatedAt: Date.parse(created.updated_at) || Date.now(),
      };
      setSessions(prev => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
      setActiveView(ViewType.CHAT);

    } catch (err) {
      console.error('创建会话失败:', err);
    }
  };

  const deleteSession = async (id: string) => {
    try {
      await api.deleteSession(id);
    } catch (err) {
      console.error('删除会话失败:', err);
      return;
    }
    setSessions(prev => prev.filter(s => s.id !== id));
    if (activeSessionId === id) {
      setActiveSessionId(null);
      setActiveView(ViewType.HOME);
    }
  };

  /** 添加消息到当前会话；聊天消息由 /chat/chat 后端统一持久化。 */
  const addMessageToActiveSession = (msg: Message) => {
    if (!activeSessionId) return;
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        const messages = [...s.messages, msg];
        let title = s.title;
        const isFirstUserMsg = msg.role === 'user' && (s.title === '新建会话' || !s.title);
        if (isFirstUserMsg) {
          const cleaned = msg.content
            .replace(/`@[\u4e00-\u9fa5\w\-]+`/g, '')
            .replace(/@[\u4e00-\u9fa5\w\-]+/g, '')
            .trim();
          title = cleaned.slice(0, 24) + (cleaned.length > 24 ? '…' : '');
          if (!title) title = '新建会话';
        }
        if (title !== s.title) {
          api.patchSession(activeSessionId, { title }).catch(err =>
            console.warn('更新会话标题失败:', err)
          );
        }
        return { ...s, messages, title, updatedAt: Date.now() };
      }
      return s;
    }));

    // 非聊天系统消息仍可通过 sessions API 直接追加；user/assistant 由 /chat/chat 统一保存。
    if (msg.role === 'system') {
      api.appendMessage(activeSessionId, {
        id: msg.id,
        role: msg.role,
        content: msg.content,
        extra: buildMessageExtra(msg),
      }).catch(err => console.warn('追加消息失败:', err));
    }
  };

  const updateAssistantMessage = (id: string, updates: Partial<Message>) => {
    if (!activeSessionId) return;
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        const messages = s.messages.map(m => m.id === id ? { ...m, ...updates } : m);
        return { ...s, messages };
      }
      return s;
    }));
  };

  const updateSessionSkill = (skillId: string) => {
    if (!activeSessionId) return;
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        return { ...s, skillId, updatedAt: Date.now() };
      }
      return s;
    }));
    api.patchSession(activeSessionId, { skill_id: skillId }).catch(err =>
      console.warn('更新会话 skill_id 失败:', err)
    );
  };

  const updateSessionClaudeId = (claudeSessionId: string) => {
    if (!activeSessionId) return;
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        return { ...s, claudeSessionId, updatedAt: Date.now() };
      }
      return s;
    }));
  };

  const { activeReferences, activeThinkingLog } = useMemo(() => {
    if (!activeSession) return { activeReferences: [] as Reference[], activeThinkingLog: [] as string[] };

    const msgs = activeSession.messages;
    let references: Reference[] = [];
    let thinkingLog: string[] = [];

    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.role !== 'assistant') continue;
      if (!references.length && m.references?.length) {
        references = m.references.filter((v, i, a) => a.findIndex(t => t.url === v.url) === i);
      }
      if (!thinkingLog.length && m.thinkingLog?.length) {
        thinkingLog = m.thinkingLog;
      }
      if (references.length && thinkingLog.length) break;
    }

    return { activeReferences: references, activeThinkingLog: thinkingLog };
  }, [activeSession?.messages]);

  const handleLogout = () => {
    removeStorage(STORAGE_ACTIVE_SESSION_KEY);
    window.location.href = `${BACKEND_URL}/api/v1/auth/logout`;
  };

  const handleCommitWorkspace = () => {
    if (!activeSessionId) return;
    const commitMsg: Message = {
      id: Date.now().toString(),
      role: 'system',
      content: `Finalized draft in **${executingAction?.label}**. Intelligence record updated.`,
      timestamp: Date.now()
    };
    addMessageToActiveSession(commitMsg);
    setExecutingAction(null);
  };

  if (!authChecked) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-400 mx-auto mb-3"></div>
          <p className="text-gray-400 text-sm">正在验证登录状态...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full overflow-hidden text-gray-900 font-sans">
      <Sidebar 
        activeView={activeView}
        onNavigate={setActiveView}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => { selectSession(id); }}
        onNewChat={() => createNewSession()}
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
              <HomeView onStartSkill={createNewSession} skills={systemSkills} />
            )}

        {activeView === ViewType.CHAT && (
          <div className="flex h-full w-full overflow-hidden">
             <ChatArea 
                session={activeSession}
                skills={allSkills}
                onSendMessage={addMessageToActiveSession}
                onUpdateMessage={updateAssistantMessage}
                onToggleReferences={() => setRightPanelOpen(!rightPanelOpen)}
                rightPanelOpen={rightPanelOpen}
                onExecuteAction={setExecutingAction}
                onUpdateSessionSkill={updateSessionSkill}
                onUpdateSessionClaudeId={updateSessionClaudeId}
             />
             {rightPanelOpen && (
               <ReferenceArea
                references={activeReferences}
                thinkingLog={activeThinkingLog}
                onClose={() => setRightPanelOpen(false)}
                isFetching={activeSession?.messages.some(m => m.role === 'assistant' && m.executionSteps?.some(s => s.status === 'running'))}
               />
             )}
          </div>
        )}

        {activeView === ViewType.SKILLS && (
          <SkillManager
            onSelectSkill={(skill) => createNewSession(skill.id)}
            onViewDetail={(skill) => {
              setDetailSkill(skill);
              setActiveView(ViewType.SKILL_DETAIL);
            }}
            onRefreshAppSkills={refreshSkills}
          />
        )}

        {activeView === ViewType.SKILL_DETAIL && detailSkill && (
          <SkillDetailPage
            skill={detailSkill}
            onBack={() => {
              setDetailSkill(null);
              setActiveView(ViewType.SKILLS);
            }}
            onUseSkill={(skill) => {
              setDetailSkill(null);
              createNewSession(skill.id);
            }}
            onDeleted={() => {
              refreshSkills();
              setDetailSkill(null);
              setActiveView(ViewType.SKILLS);
            }}
          />
        )}

        {activeView === ViewType.SCHEDULED_TASKS && <ScheduledTasksManager />}

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
    </div>
  );
};

export default App;
