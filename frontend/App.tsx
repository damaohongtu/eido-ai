
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ViewType, Skill, Message, ChatSession, Reference, SkillAction, Project, ProjectFile, CreateSessionOptions } from './types';
import { INITIAL_CHAT_STATE } from './constants';
import Sidebar from './components/Sidebar';
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
      executionSteps: msg.streaming
        ? msg.executionSteps
        : msg.executionSteps?.map(step =>
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
  if (msg.deliveryMode) extra.deliveryMode = msg.deliveryMode;
  if (msg.deliveryStatus) extra.deliveryStatus = msg.deliveryStatus;
  if (msg.queuePosition) extra.queuePosition = msg.queuePosition;
  if (msg.streaming !== undefined) extra.streaming = msg.streaming;
  return extra;
}

interface AppProps {
  browserContext?: string;
  extensionMode?: boolean;
  onAuthRequired?: (loginUrl: string) => void;
}

const App: React.FC<AppProps> = ({ browserContext, extensionMode = false, onAuthRequired }) => {
  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authChecking, setAuthChecking] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ user_id: string; username: string } | null>(null);

  const checkAuthState = useCallback(async () => {
    setAuthChecking(true);
    try {
      const user = await api.checkAuth();
      if (!user) {
        const loginUrl = `${BACKEND_URL}/api/v1/auth/login`;
        if (extensionMode) {
          setAuthRequired(true);
          setAuthChecked(true);
          onAuthRequired?.(loginUrl);
          return false;
        }
        window.location.href = loginUrl;
        return false;
      }
      setAuthRequired(false);
      setCurrentUser(user);
      setAuthChecked(true);
      api.warmupSandbox().catch(() => undefined);
      return true;
    } finally {
      setAuthChecking(false);
    }
  }, [extensionMode, onAuthRequired]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has('login')) {
      params.delete('login');
      const clean = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (clean ? `?${clean}` : ''));
    }

    checkAuthState();
  }, [checkAuthState]);

  useEffect(() => {
    if (!extensionMode || !authRequired) return;
    const id = window.setInterval(() => {
      checkAuthState();
    }, 2500);
    const onFocus = () => checkAuthState();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [authRequired, checkAuthState, extensionMode]);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [runningSessionIds, setRunningSessionIds] = useState<Set<string>>(new Set());
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]);
  const [projectFilesLoading, setProjectFilesLoading] = useState(false);
  const [projectFilesProjectId, setProjectFilesProjectId] = useState<string | null>(null);
  const projectFilesRequestRef = useRef(0);
  const projectsRequestRef = useRef(0);
  const navigationRequestRef = useRef(0);
  const taskSessionPollTimerRef = useRef<number | null>(null);
  const taskSessionPollGenerationRef = useRef(0);
  const [createProjectOpen, setCreateProjectOpen] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() =>
    readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null)
  );
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
  activeSessionIdRef.current = activeSessionId;

  const [activeView, setActiveView] = useState<ViewType>(() => {
    const cachedId = readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null);
    return cachedId ? ViewType.CHAT : ViewType.HOME;
  });
  const [userSkills, setUserSkills] = useState<Skill[]>([]);
  const [systemSkills, setSystemSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [harness, setHarness] = useState<string>(() =>
    readStorage<string>('eido_harness', 'claude_code')
  );

  useEffect(() => {
    writeStorage('eido_harness', harness);
  }, [harness]);

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
      const requestId = ++navigationRequestRef.current;
      try {
        const list = await api.listSessions();
        const summaries = list.map(summaryToSession);
        setSessions(prev => {
          if (navigationRequestRef.current === requestId) return summaries;
          const known = new Set(prev.map(session => session.id));
          return [...prev, ...summaries.filter(session => !known.has(session.id))];
        });

        if (navigationRequestRef.current !== requestId) return;

        const cachedId = readStorage<string | null>(STORAGE_ACTIVE_SESSION_KEY, null);
        const target = cachedId && summaries.find(s => s.id === cachedId)
          ? cachedId
          : null;
        if (target) {
          try {
            const detail = await api.getSession(target);
            const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
            setSessions(prev => prev.map(s => s.id === target ? hydrated : s));
            if (navigationRequestRef.current !== requestId) return;
            setActiveSessionId(target);
            setActiveProjectId(hydrated.projectId);
            setActiveView(ViewType.CHAT);
          } catch (err) {
            console.warn('恢复上次会话失败:', err);
            if (navigationRequestRef.current === requestId) {
              setActiveSessionId(null);
              removeStorage(STORAGE_ACTIVE_SESSION_KEY);
            }
          }
        }
      } catch (err) {
        console.error('加载会话列表失败:', err);
      }
    })();
  }, [authChecked]);

  // 定时任务可能在页面打开期间创建会话；周期同步摘要，让新会话自动出现在左栏。
  useEffect(() => {
    if (!authChecked || authRequired) return;
    const refreshSessionSummaries = async () => {
      try {
        const summaries = (await api.listSessions()).map(summaryToSession);
        setSessions(previous => {
          const existing = new Map<string, ChatSession>(
            previous.map(session => [session.id, session] as const)
          );
          return summaries.map(summary => {
            const current = existing.get(summary.id);
            return current
              ? {
                  ...current,
                  title: summary.title,
                  projectId: summary.projectId,
                  skillId: summary.skillId,
                  updatedAt: summary.updatedAt,
                }
              : summary;
          });
        });
      } catch (err) {
        console.warn('同步自动任务会话失败:', err);
      }
    };
    const timer = window.setInterval(refreshSessionSummaries, 10_000);
    return () => window.clearInterval(timer);
  }, [authChecked, authRequired]);

  useEffect(() => () => {
    taskSessionPollGenerationRef.current += 1;
    if (taskSessionPollTimerRef.current !== null) {
      window.clearInterval(taskSessionPollTimerRef.current);
    }
  }, []);

  const refreshProjects = useCallback(async () => {
    const requestId = ++projectsRequestRef.current;
    try {
      // 已归档项目的既有会话仍可继续使用项目上下文，因此导航也要保留它们。
      const list = await api.listProjects({ include_archived: true });
      if (projectsRequestRef.current === requestId) setProjects(list);
    } catch (err) {
      // Project 是增量能力；旧后端不可用时不能阻塞原有聊天。
      console.warn('加载项目列表失败:', err);
    }
  }, []);

  useEffect(() => {
    if (!authChecked || authRequired) return;
    refreshProjects();
  }, [authChecked, authRequired, refreshProjects]);

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

  const activeProject = useMemo(
    () => projects.find(project => project.id === activeProjectId) || null,
    [projects, activeProjectId]
  );

  const activeSessionProject = useMemo(
    () => projects.find(project => project.id === activeSession?.projectId) || null,
    [projects, activeSession?.projectId]
  );

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

  /** 轮询服务端持久化消息，直到自动任务写入最终 assistant 回复。 */
  const pollTaskSession = (id: string) => {
    const generation = ++taskSessionPollGenerationRef.current;
    if (taskSessionPollTimerRef.current !== null) {
      window.clearInterval(taskSessionPollTimerRef.current);
    }
    let attempts = 0;
    taskSessionPollTimerRef.current = window.setInterval(async () => {
      attempts += 1;
      try {
        const detail = await api.getSession(id);
        if (taskSessionPollGenerationRef.current !== generation) return;
        const current = hydrateSession(detail);
        setSessions(previous => previous.map(session =>
          session.id === id ? current : session
        ));
        // hydrateSession 会为空会话补一条前端欢迎语；结束判断必须只看后端消息。
        const latest = detail.messages[detail.messages.length - 1];
        if (latest?.role === 'assistant' && latest.extra?.streaming !== true) {
          if (taskSessionPollTimerRef.current !== null) {
            window.clearInterval(taskSessionPollTimerRef.current);
            taskSessionPollTimerRef.current = null;
          }
        }
      } catch {
        if (
          taskSessionPollGenerationRef.current === generation
          && taskSessionPollTimerRef.current !== null
        ) {
          window.clearInterval(taskSessionPollTimerRef.current);
          taskSessionPollTimerRef.current = null;
        }
      }
      if (
        attempts >= 60
        && taskSessionPollGenerationRef.current === generation
        && taskSessionPollTimerRef.current !== null
      ) {
        window.clearInterval(taskSessionPollTimerRef.current);
        taskSessionPollTimerRef.current = null;
      }
    }, 1500);
  };

  /** 切换激活会话；若该会话尚未拉取过完整消息则按需拉取一次。 */
  const selectSession = async (id: string) => {
    const requestId = ++navigationRequestRef.current;
    let target = sessions.find(s => s.id === id);
    if (!target) return;
    if (target && target.messages.length === 0) {
      try {
        const detail = await api.getSession(id);
        const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
        setSessions(prev => prev.map(s => s.id === id ? hydrated : s));
        target = hydrated;
      } catch (err) {
        console.error('加载会话消息失败:', err);
        return;
      }
    }
    if (navigationRequestRef.current !== requestId) return;
    setActiveSessionId(id);
    setActiveProjectId(target?.projectId ?? null);
    setActiveView(ViewType.CHAT);
    if (target?.title.startsWith('[自动任务]')) {
      pollTaskSession(id);
    } else if (taskSessionPollTimerRef.current !== null) {
      taskSessionPollGenerationRef.current += 1;
      window.clearInterval(taskSessionPollTimerRef.current);
      taskSessionPollTimerRef.current = null;
    }
  };

  /** 自动任务会在服务端先创建会话；刷新列表后立即打开，并短期轮询执行结果。 */
  const openTaskSession = async (id: string) => {
    const requestId = ++navigationRequestRef.current;
    try {
      const [detail, list] = await Promise.all([
        api.getSession(id),
        api.listSessions(),
      ]);
      if (navigationRequestRef.current !== requestId) return;
      const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
      const summaries = list.map(summaryToSession);
      setSessions([
        hydrated,
        ...summaries.filter(session => session.id !== id),
      ]);
      setActiveSessionId(id);
      setActiveProjectId(hydrated.projectId);
      setActiveView(ViewType.CHAT);

      // 后端执行与页面跳转并行；定时刷新让用户能在新会话里看到结果出现。
      pollTaskSession(id);
    } catch (err) {
      console.error('打开自动任务会话失败:', err);
      window.alert(err instanceof Error ? err.message : '打开自动任务会话失败');
    }
  };

  const createNewSession = async (options: CreateSessionOptions = {}) => {
    const requestId = ++navigationRequestRef.current;
    try {
      const created = await api.createSession({
        skill_id: options.skillId ?? null,
        project_id: options.projectId ?? null,
      });
      // 初始欢迎语是前端 UI 状态，不写入后端；id 按会话生成，避免本地渲染 key 冲突
      const initialMessages: Message[] = INITIAL_CHAT_STATE.map((m, i) => ({
        ...m,
        id: `${created.id}-init-${i}`,
        timestamp: Date.now(),
      }));
      const newSession: ChatSession = {
        id: created.id,
        title: created.title || '新建会话',
        projectId: created.project_id ?? options.projectId ?? null,
        skillId: created.skill_id || options.skillId,
        messages: initialMessages,
        updatedAt: Date.parse(created.updated_at) || Date.now(),
      };
      setSessions(prev => [newSession, ...prev]);
      if (navigationRequestRef.current === requestId) {
        setActiveSessionId(newSession.id);
        setActiveProjectId(newSession.projectId);
        setActiveView(ViewType.CHAT);
      }
      refreshProjects();

    } catch (err) {
      console.error('创建会话失败:', err);
    }
  };

  const deleteSession = async (id: string) => {
    const navigationVersion = navigationRequestRef.current;
    const deletedSession = sessions.find(session => session.id === id);
    try {
      await api.deleteSession(id);
    } catch (err) {
      console.error('删除会话失败:', err);
      return;
    }
    setSessions(prev => prev.filter(s => s.id !== id));
    refreshProjects();
    if (
      activeSessionIdRef.current === id
      && navigationRequestRef.current === navigationVersion
    ) {
      navigationRequestRef.current += 1;
      setActiveSessionId(null);
      if (deletedSession?.projectId && projects.some(project => project.id === deletedSession.projectId)) {
        setActiveProjectId(deletedSession.projectId);
        setActiveView(ViewType.PROJECT);
      } else {
        setActiveProjectId(null);
        setActiveView(ViewType.HOME);
      }
    }
  };

  /** 按明确会话写入，避免流式执行期间切换侧栏后把结果写进另一项目。 */
  const addMessageToSession = (sessionId: string, msg: Message) => {
    setSessions(prev => prev.map(s => {
      if (s.id === sessionId) {
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
          api.patchSession(sessionId, { title }).catch(err =>
            console.warn('更新会话标题失败:', err)
          );
        }
        return { ...s, messages, title, updatedAt: Date.now() };
      }
      return s;
    }));

    // 非聊天系统消息仍可通过 sessions API 直接追加；user/assistant 由 /chat/chat 统一保存。
    if (msg.role === 'system') {
      api.appendMessage(sessionId, {
        id: msg.id,
        role: msg.role,
        content: msg.content,
        extra: buildMessageExtra(msg),
      }).catch(err => console.warn('追加消息失败:', err));
    }
  };

  const updateAssistantMessage = (sessionId: string, id: string, updates: Partial<Message>) => {
    setSessions(prev => prev.map(s => {
      if (s.id === sessionId) {
        const messages = s.messages.map(m => m.id === id ? { ...m, ...updates } : m);
        return { ...s, messages };
      }
      return s;
    }));
  };

  const refreshSessionMessages = async (sessionId: string) => {
    const detail = await api.getSession(sessionId);
    const hydrated = fixStaleRunningSteps([hydrateSession(detail)])[0];
    setSessions(previous => previous.map(session => {
      if (session.id !== sessionId) return session;
      const persistedIds = new Set(hydrated.messages.map(message => message.id));
      const locallyQueued = session.messages.filter(message =>
        !persistedIds.has(message.id) && !message.id.includes('-init-')
      );
      return { ...hydrated, messages: [...hydrated.messages, ...locallyQueued] };
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

  const loadProjectFiles = useCallback(async (projectId: string) => {
    const requestId = ++projectFilesRequestRef.current;
    setProjectFilesLoading(true);
    setProjectFilesProjectId(projectId);
    try {
      const files = await api.listProjectFiles(projectId);
      if (projectFilesRequestRef.current === requestId) setProjectFiles(files);
    } catch (err) {
      console.warn('加载项目资料失败:', err);
      if (projectFilesRequestRef.current === requestId) setProjectFiles([]);
    } finally {
      if (projectFilesRequestRef.current === requestId) setProjectFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!activeProjectId) {
      projectFilesRequestRef.current += 1;
      setProjectFiles([]);
      setProjectFilesProjectId(null);
      setProjectFilesLoading(false);
      return;
    }
    loadProjectFiles(activeProjectId);
  }, [activeProjectId, loadProjectFiles]);

  const openProject = (projectId: string) => {
    navigationRequestRef.current += 1;
    setActiveProjectId(projectId);
    setActiveView(ViewType.PROJECT);
  };

  const createProject = async (input: { name: string; description?: string; instructions?: string }) => {
    setCreatingProject(true);
    try {
      const created = await api.createProject(input);
      setProjects(prev => [created, ...prev.filter(project => project.id !== created.id)]);
      setCreateProjectOpen(false);
      openProject(created.id);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setCreatingProject(false);
    }
  };

  const saveProject = async (patch: { name: string; description: string; instructions: string }) => {
    if (!activeProjectId) return;
    setSavingProject(true);
    try {
      const updated = await api.patchProject(activeProjectId, patch);
      setProjects(prev => prev.map(project => project.id === updated.id ? updated : project));
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '保存项目失败');
    } finally {
      setSavingProject(false);
    }
  };

  const deleteProject = async () => {
    if (!activeProjectId) return;
    const deletedId = activeProjectId;
    try {
      await api.deleteProject(deletedId);
      setProjects(prev => prev.filter(project => project.id !== deletedId));
      setSessions(prev => prev.map(session => session.projectId === deletedId ? { ...session, projectId: null } : session));
      setActiveProjectId(null);
      setActiveView(ViewType.HOME);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除项目失败');
    }
  };

  const moveSession = async (sessionId: string, projectId: string | null) => {
    try {
      await api.patchSession(sessionId, { project_id: projectId });
      setSessions(prev => prev.map(session => session.id === sessionId
        ? { ...session, projectId, updatedAt: Date.now() }
        : session));
      if (activeView === ViewType.CHAT && activeSessionId === sessionId) setActiveProjectId(projectId);
      await refreshProjects();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '移动会话失败');
    }
  };

  const uploadProjectFile = async (file: File) => {
    if (!activeProjectId) return;
    try {
      await api.uploadProjectFile(activeProjectId, file);
      await loadProjectFiles(activeProjectId);
      await refreshProjects();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : `上传 ${file.name} 失败`);
    }
  };

  const deleteProjectFile = async (fileId: string) => {
    if (!activeProjectId) return;
    if (!window.confirm('删除这份项目资料？')) return;
    try {
      await api.deleteProjectFile(activeProjectId, fileId);
      await loadProjectFiles(activeProjectId);
      await refreshProjects();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除项目资料失败');
    }
  };

  const importSessionFileToProject = async (path: string, displayName: string) => {
    const sessionId = activeSession?.id;
    const projectId = activeSession?.projectId;
    if (!sessionId || !projectId) {
      throw new Error('当前会话未归属项目，不能加入项目资料');
    }
    await api.importProjectFile(projectId, {
      session_id: sessionId,
      path,
      display_name: displayName,
    });
    await Promise.all([
      loadProjectFiles(projectId),
      refreshProjects(),
    ]);
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
    addMessageToSession(activeSessionId, commitMsg);
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

  if (authRequired) {
    const loginUrl = `${BACKEND_URL}/api/v1/auth/login`;
    return (
      <div className="flex h-screen items-center justify-center bg-white px-6">
        <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 text-lg font-black text-gray-700">E</div>
          <h1 className="text-lg font-black text-gray-900">需要登录 Eido</h1>
          <p className="mt-2 text-sm leading-relaxed text-gray-500">
            插件侧边栏不能直接跳转到登录页。请在新标签页完成登录后，回到插件重新打开或刷新。
          </p>
          <button
            type="button"
            onClick={() => window.open(loginUrl, '_blank', 'noopener,noreferrer')}
            className="mt-5 w-full rounded-lg bg-gray-800 px-4 py-2.5 text-sm font-bold text-white hover:bg-gray-900"
          >
            打开登录页
          </button>
          <button
            type="button"
            onClick={() => checkAuthState()}
            disabled={authChecking}
            className="mt-3 w-full rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-bold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {authChecking ? '正在检测...' : '我已完成登录，重新检测'}
          </button>
        </div>
      </div>
    );
  }

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
        harness={harness}
        onHarnessChange={setHarness}
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
                harness={harness}
                browserContext={browserContext}
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
