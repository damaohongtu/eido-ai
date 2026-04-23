
import React, { useState, useEffect, useMemo } from 'react';
import { message } from 'antd';
import { ViewType, Skill, Agent, Tool, Message, ChatSession, Reference, SkillAction } from './types';
import { SYSTEM_SKILLS, SYSTEM_AGENTS, SYSTEM_TOOLS, INITIAL_CHAT_STATE } from './constants';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import ReferenceArea from './components/ReferenceArea';
import HomeView from './components/HomeView';
import SkillManager from './components/SkillManager';
import SkillDetailPage from './components/SkillDetailPage';
import SkillEditor from './components/SkillEditor';
import ScheduledTasksManager from './components/ScheduledTasksManager';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from './services/api';
import { BACKEND_URL } from './constants';

const STORAGE_SESSIONS_KEY = 'eido_chat_sessions';
const STORAGE_ACTIVE_SESSION_KEY = 'eido_active_session_id';

/** sessionStorage 读写工具，异常时静默降级 */
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
    });
  }, []);

  const [sessions, setSessions] = useState<ChatSession[]>(() =>
    fixStaleRunningSteps(readStorage<ChatSession[]>(STORAGE_SESSIONS_KEY, []))
  );

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
  const [editorSkill, setEditorSkill] = useState<Skill | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);

  // Workspace (Report Editor) State
  const [executingAction, setExecutingAction] = useState<SkillAction | null>(null);
  const [workspaceContent, setWorkspaceContent] = useState('');
  const [isPreviewMode, setIsPreviewMode] = useState(false);

  // 持久化会话列表到 sessionStorage
  useEffect(() => {
    writeStorage(STORAGE_SESSIONS_KEY, sessions);
  }, [sessions]);

  // 持久化当前会话 ID 到 sessionStorage
  useEffect(() => {
    if (activeSessionId) {
      writeStorage(STORAGE_ACTIVE_SESSION_KEY, activeSessionId);
    } else {
      removeStorage(STORAGE_ACTIVE_SESSION_KEY);
    }
  }, [activeSessionId]);

  // 加载系统技能和用户技能
  useEffect(() => {
    const loadSkills = async () => {
      setLoading(true);
      try {
        // 并行加载系统技能和用户技能
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

  const createNewSession = (skillId?: string) => {
    const skill = allSkills.find(s => s.id === skillId);
    const newSession: ChatSession = {
      id: Date.now().toString(),
      title: '新建会话',
      skillId,
      messages: [...INITIAL_CHAT_STATE],
      updatedAt: Date.now()
    };
    setSessions(prev => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    setActiveView(ViewType.CHAT);
  };

  const deleteSession = (id: string) => {
    setSessions(prev => prev.filter(s => s.id !== id));
    if (activeSessionId === id) {
      setActiveSessionId(null);
      setActiveView(ViewType.HOME);
    }
  };

  const addMessageToActiveSession = (msg: Message) => {
    if (!activeSessionId) return;
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        const messages = [...s.messages, msg];
        // 第一条用户消息到来时，用其内容（去掉 @技能 标记）更新会话标题
        let title = s.title;
        const isFirstUserMsg = msg.role === 'user' && s.title === '新建会话';
        if (isFirstUserMsg) {
          const cleaned = msg.content
            .replace(/`@[\u4e00-\u9fa5\w\-]+`/g, '')  // 去掉 `@技能名`
            .replace(/@[\u4e00-\u9fa5\w\-]+/g, '')     // 去掉 @技能名
            .trim();
          title = cleaned.slice(0, 24) + (cleaned.length > 24 ? '…' : '');
          if (!title) title = '新建会话';
        }
        return { ...s, messages, title, updatedAt: Date.now() };
      }
      return s;
    }));
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
  };

  // 从最新 assistant 消息中提取 references 和 thinkingLog
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
    try {
      sessionStorage.removeItem(STORAGE_SESSIONS_KEY);
      sessionStorage.removeItem(STORAGE_ACTIVE_SESSION_KEY);
    } catch {
      /* ignore */
    }
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
    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) return { ...s, messages: [...s.messages, commitMsg], updatedAt: Date.now() };
      return s;
    }));
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
        onSelectSession={(id) => {
          setActiveSessionId(id);
          setActiveView(ViewType.CHAT);
        }}
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
            onCreateSkill={() => {
              setEditorSkill(null);
              setActiveView(ViewType.SKILL_EDITOR);
            }}
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
            onEdit={(skill) => {
              setEditorSkill(skill);
              setActiveView(ViewType.SKILL_EDITOR);
            }}
            onDeleted={() => {
              refreshSkills();
              setDetailSkill(null);
              setActiveView(ViewType.SKILLS);
            }}
          />
        )}

        {activeView === ViewType.SKILL_EDITOR && (
          <SkillEditor
            skill={editorSkill}
            onSave={async (skill) => {
              if (editorSaving) return;
              setEditorSaving(true);
              try {
                if (!editorSkill) {
                  const lines = skill.description.split('\n');
                  const desc = lines[0]?.trim() || '';
                  await api.createSkill({
                    name: skill.name,
                    description: desc,
                    content: skill.description,
                    icon: skill.icon || undefined,
                  });
                  message.success('技能创建成功');
                } else {
                  await api.updateSkill(editorSkill.id, {
                    name: skill.name,
                    description: skill.description,
                    content: skill.description,
                    icon: skill.icon || undefined,
                  });
                  message.success('技能更新成功');
                }
                await refreshSkills();
                setEditorSkill(null);
                setActiveView(ViewType.SKILLS);
              } catch (err) {
                message.error(err instanceof Error ? err.message : '保存失败');
              } finally {
                setEditorSaving(false);
              }
            }}
            onCancel={() => {
              setEditorSkill(null);
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
