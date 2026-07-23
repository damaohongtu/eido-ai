import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  hydrateSession,
  summaryToSession,
  BACKEND_URL,
  INITIAL_CHAT_STATE,
} from '../shared';
import type { ChatSession, CreateSessionOptions, Message, Project, Skill } from '../shared';
import type { AgentRuntime } from '../runtime/types';

export type MobileTab = 'chat' | 'skills' | 'me';

const ACTIVE_SESSION_KEY = 'eido_m_active_session_id';
const LOCAL_ACTIVE_SESSION_KEY = 'eido_local_active_session_id';
const LOCAL_SESSIONS_PREFIX = 'eido_local_sessions_';
const HARNESS_KEY = 'eido_m_harness';

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
  } catch {
    /* ignore */
  }
}
function removeStorage(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/** 修复从缓存恢复时处于 running 状态的步骤（连接已断开，不会再更新） */
function fixStaleRunningSteps(session: ChatSession): ChatSession {
  return {
    ...session,
    projectId: session.projectId ?? null,
    messages: session.messages.map((msg) => ({
      ...msg,
      executionSteps: msg.executionSteps?.map((step) =>
        step.status === 'running' ? { ...step, status: 'waiting' as const } : step
      ),
    })),
  };
}

function buildMessageExtra(msg: Message): Record<string, unknown> {
  const extra: Record<string, unknown> = {};
  if (msg.thinking) extra.thinking = msg.thinking;
  if (msg.thinkingLog && msg.thinkingLog.length) extra.thinkingLog = msg.thinkingLog;
  if (msg.executionSteps && msg.executionSteps.length) extra.executionSteps = msg.executionSteps;
  if (msg.workflowMermaid) extra.workflowMermaid = msg.workflowMermaid;
  if (msg.references && msg.references.length) extra.references = msg.references;
  if (msg.pendingConfirmation) extra.pendingConfirmation = msg.pendingConfirmation;
  return extra;
}

export interface EidoStore {
  authChecked: boolean;
  authRequired: boolean;
  authChecking: boolean;
  checkAuthState: () => Promise<boolean>;
  currentUser: { user_id: string; username: string } | null;

  tab: MobileTab;
  setTab: (t: MobileTab) => void;

  sessions: ChatSession[];
  projects: Project[];
  projectsEnabled: boolean;
  activeSessionId: string | null;
  activeSession: ChatSession | null;

  systemSkills: Skill[];
  userSkills: Skill[];
  allSkills: Skill[];
  skillsLoading: boolean;
  refreshSkills: () => Promise<void>;

  harness: string;
  setHarness: (h: string) => void;

  refreshSessions: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  selectSession: (id: string) => Promise<boolean>;
  openChat: (id: string) => Promise<void>;
  createNewSession: (options?: CreateSessionOptions) => Promise<void>;
  moveSession: (id: string, projectId: string | null) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  addMessage: (sessionId: string, msg: Message) => void;
  updateMessage: (sessionId: string, id: string, updates: Partial<Message>) => void;
  updateSessionSkill: (skillId: string) => void;
  logout: () => void;
}

interface UseEidoStoreOptions {
  extensionMode?: boolean;
  onAuthRequired?: (loginUrl: string) => void;
  localMode?: boolean;
  agentRuntime?: AgentRuntime;
}

export function useEidoStore(options: UseEidoStoreOptions = {}): EidoStore {
  const { extensionMode = false, onAuthRequired, localMode = false, agentRuntime } = options;
  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authChecking, setAuthChecking] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ user_id: string; username: string } | null>(null);
  const [tab, setTabState] = useState<MobileTab>('chat');

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 用 ref 读取当前会话 id，避免在 setState updater 内嵌套 setState（StrictMode 下会重复执行副作用）
  const activeSessionIdRef = useRef<string | null>(null);
  const navigationRequestRef = useRef(0);
  const projectsRequestRef = useRef(0);
  const setTab = useCallback((nextTab: MobileTab) => {
    navigationRequestRef.current += 1;
    setTabState(nextTab);
  }, []);
  // 落地初始化只执行一次（避免 StrictMode 双调导致重复创建空会话）
  const bootstrappedRef = useRef(false);
  const localStoreReadyRef = useRef(false);

  const [systemSkills, setSystemSkills] = useState<Skill[]>([]);
  const [userSkills, setUserSkills] = useState<Skill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);

  const [harness, setHarnessState] = useState<string>(() => readStorage<string>(HARNESS_KEY, 'claude_code'));

  const setHarness = useCallback((h: string) => {
    setHarnessState(h);
    writeStorage(HARNESS_KEY, h);
  }, []);

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
      if (!localMode) {
        api.warmupSandbox().catch(() => undefined);
      }
      return true;
    } finally {
      setAuthChecking(false);
    }
  }, [extensionMode, localMode, onAuthRequired]);

  // 鉴权（登录态来自 /api/v1/auth/me；未登录跳后端登录）
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

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
    const key = localMode ? LOCAL_ACTIVE_SESSION_KEY : ACTIVE_SESSION_KEY;
    if (activeSessionId) writeStorage(key, activeSessionId);
    else removeStorage(key);
  }, [activeSessionId, localMode]);

  const localSessionsKey = useMemo(
    () => `${LOCAL_SESSIONS_PREFIX}${currentUser?.user_id || 'anonymous'}`,
    [currentUser?.user_id]
  );

  useEffect(() => {
    if (!localMode || !localStoreReadyRef.current) return;
    try {
      localStorage.setItem(localSessionsKey, JSON.stringify(sessions));
    } catch (err) {
      console.warn('保存本地会话失败:', err);
    }
  }, [localMode, localSessionsKey, sessions]);

  // 拉取会话列表 + 落地即进入聊天（恢复上次会话 / 打开最近会话 / 无则自动新建）
  useEffect(() => {
    if (!authChecked || authRequired || bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    (async () => {
      const requestId = ++navigationRequestRef.current;
      try {
        if (localMode) {
          const raw = localStorage.getItem(localSessionsKey);
          const localSessions = raw ? (JSON.parse(raw) as ChatSession[]).map(fixStaleRunningSteps) : [];
          setSessions(localSessions);
          localStoreReadyRef.current = true;

          const cachedId = readStorage<string | null>(LOCAL_ACTIVE_SESSION_KEY, null);
          const targetId =
            cachedId && localSessions.some((session) => session.id === cachedId)
              ? cachedId
              : localSessions[0]?.id ?? null;
          if (targetId) {
            if (navigationRequestRef.current !== requestId) return;
            activeSessionIdRef.current = targetId;
            setActiveSessionId(targetId);
          } else {
            await createNewSession();
          }
          return;
        }

        const list = await api.listSessions();
        const summaries = list.map(summaryToSession);
        setSessions((prev) => {
          if (navigationRequestRef.current === requestId) return summaries;
          const known = new Set(prev.map((session) => session.id));
          return [...prev, ...summaries.filter((session) => !known.has(session.id))];
        });
        if (navigationRequestRef.current !== requestId) return;

        const cachedId = readStorage<string | null>(ACTIVE_SESSION_KEY, null);
        const targetId =
          cachedId && summaries.find((s) => s.id === cachedId)
            ? cachedId
            : summaries[0]?.id ?? null;

        if (targetId) {
          try {
            const detail = await api.getSession(targetId);
            const hydrated = fixStaleRunningSteps(hydrateSession(detail));
            setSessions((prev) => prev.map((s) => (s.id === targetId ? hydrated : s)));
            if (navigationRequestRef.current !== requestId) return;
            activeSessionIdRef.current = targetId;
            setActiveSessionId(targetId);
          } catch {
            if (navigationRequestRef.current === requestId) {
              removeStorage(ACTIVE_SESSION_KEY);
              await createNewSession();
            }
          }
        } else {
          // 无任何历史会话：自动创建一个，落地即可直接聊天
          await createNewSession();
        }
      } catch (err) {
        console.error('加载会话列表失败:', err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authChecked, authRequired, localMode, localSessionsKey]);

  // 加载技能
  const refreshSkills = useCallback(async () => {
    try {
      if (localMode) {
        const localSkills = agentRuntime?.listSkills ? await agentRuntime.listSkills() : [];
        setSystemSkills(localSkills);
        setUserSkills([]);
        return;
      }
      const [systemResult, userResult] = await Promise.all([
        api.getSkills({ is_system: true, limit: 100 }),
        api.getSkills({ is_system: false, limit: 100 }),
      ]);
      setSystemSkills(systemResult.items);
      setUserSkills(userResult.items);
    } catch (error) {
      console.error('加载技能失败:', error);
    }
  }, [agentRuntime, localMode]);

  const refreshProjects = useCallback(async () => {
    const requestId = ++projectsRequestRef.current;
    if (localMode) {
      if (projectsRequestRef.current === requestId) setProjects([]);
      return;
    }
    try {
      // 归档项目不再接收新资料，但其既有会话仍需出现在导航中并可继续使用上下文。
      const result = await api.listProjects({ include_archived: true });
      if (projectsRequestRef.current === requestId) setProjects(result);
    } catch (error) {
      console.warn('加载项目失败:', error);
    }
  }, [localMode]);

  useEffect(() => {
    if (!authChecked || authRequired) return;
    setSkillsLoading(true);
    refreshSkills().finally(() => setSkillsLoading(false));
  }, [authChecked, authRequired, refreshSkills]);

  useEffect(() => {
    if (!authChecked || authRequired) return;
    refreshProjects();
  }, [authChecked, authRequired, refreshProjects]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || null,
    [sessions, activeSessionId]
  );
  const allSkills = useMemo(() => [...systemSkills, ...userSkills], [systemSkills, userSkills]);

  const refreshSessions = useCallback(async () => {
    try {
      if (localMode) {
        const raw = localStorage.getItem(localSessionsKey);
        if (raw) setSessions((JSON.parse(raw) as ChatSession[]).map(fixStaleRunningSteps));
        return;
      }
      const list = await api.listSessions();
      const summaries = list.map(summaryToSession);
      setSessions((prev) =>
        summaries.map((sum) => {
          const existing = prev.find((p) => p.id === sum.id);
          // 保留已拉取过的完整消息，避免下拉刷新清空当前会话内容
          return existing && existing.messages.length > 0 ? { ...sum, messages: existing.messages } : sum;
        })
      );
    } catch (err) {
      console.error('刷新会话列表失败:', err);
    }
  }, [localMode, localSessionsKey]);

  const selectSession = useCallback(
    async (id: string) => {
      const requestId = ++navigationRequestRef.current;
      const target = sessions.find((s) => s.id === id);
      if (!target) return false;
      if (!localMode && target && target.messages.length === 0) {
        try {
          const detail = await api.getSession(id);
          const hydrated = fixStaleRunningSteps(hydrateSession(detail));
          setSessions((prev) => prev.map((s) => (s.id === id ? hydrated : s)));
        } catch (err) {
          console.error('加载会话消息失败:', err);
          return false;
        }
      }
      if (navigationRequestRef.current !== requestId) return false;
      activeSessionIdRef.current = id;
      setActiveSessionId(id);
      return true;
    },
    [localMode, sessions]
  );

  const openChat = useCallback(
    async (id: string) => {
      if (await selectSession(id)) setTab('chat');
    },
    [selectSession]
  );

  const createNewSession = useCallback(async (options: CreateSessionOptions = {}) => {
    const requestId = ++navigationRequestRef.current;
    const { skillId } = options;
    try {
      if (localMode) {
        const id = typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
          : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`.slice(0, 12);
        // Bind the new local conversation to the OpenCode directory visible at
        // creation time. Later global /path changes must not migrate it.
        await agentRuntime?.prepareSession?.(id);
        const initialMessages: Message[] = INITIAL_CHAT_STATE.map((message, index) => ({
          ...message,
          id: `${id}-init-${index}`,
          timestamp: Date.now(),
        }));
        const localSession: ChatSession = {
          id,
          title: '新建会话',
          projectId: null,
          skillId,
          messages: initialMessages,
          updatedAt: Date.now(),
        };
        setSessions((prev) => [localSession, ...prev]);
        if (navigationRequestRef.current === requestId) {
          activeSessionIdRef.current = id;
          setActiveSessionId(id);
          setTab('chat');
        }
        return;
      }

      const created = await api.createSession({
        skill_id: skillId ?? null,
        project_id: options.projectId ?? null,
      });
      const initialMessages: Message[] = INITIAL_CHAT_STATE.map((m, i) => ({
        ...m,
        id: `${created.id}-init-${i}`,
        timestamp: Date.now(),
      }));
      const newSession: ChatSession = {
        id: created.id,
        title: created.title || '新建会话',
        projectId: created.project_id ?? options.projectId ?? null,
        skillId: created.skill_id || skillId,
        messages: initialMessages,
        updatedAt: Date.parse(created.updated_at) || Date.now(),
      };
      setSessions((prev) => [newSession, ...prev]);
      if (navigationRequestRef.current === requestId) {
        activeSessionIdRef.current = newSession.id;
        setActiveSessionId(newSession.id);
        setTab('chat');
      }
      refreshProjects();
    } catch (err) {
      console.error('创建会话失败:', err);
    }
  }, [agentRuntime, localMode, refreshProjects]);

  const moveSession = useCallback(async (id: string, projectId: string | null) => {
    if (localMode) return;
    try {
      await api.patchSession(id, { project_id: projectId });
      setSessions((prev) => prev.map((session) => session.id === id
        ? { ...session, projectId, updatedAt: Date.now() }
        : session));
      await refreshProjects();
    } catch (error) {
      console.error('移动会话失败:', error);
      throw error;
    }
  }, [localMode, refreshProjects]);

  const deleteSession = useCallback(
    async (id: string) => {
      if (localMode) {
        agentRuntime?.deleteSession?.(id).catch((err) => console.warn('删除本地 Agent 会话失败:', err));
      } else {
        try {
          await api.deleteSession(id);
        } catch (err) {
          console.error('删除会话失败:', err);
          return;
        }
      }
      const remaining = sessions.filter((s) => s.id !== id);
      setSessions(remaining);
      if (!localMode) refreshProjects();
      // 删除的是当前会话：自动切到最近一条，无则置空
      if (activeSessionIdRef.current === id) {
        const next = remaining[0];
        if (next) {
          openChat(next.id);
        } else {
          activeSessionIdRef.current = null;
          setActiveSessionId(null);
        }
      }
    },
    [agentRuntime, localMode, sessions, openChat, refreshProjects]
  );

  const addMessage = useCallback((sessionId: string, msg: Message) => {
    let titleToPatch: string | null = null;
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== sessionId) return s;
        const messages = [...s.messages, msg];
        let title = s.title;
        const isFirstUserMsg = msg.role === 'user' && (s.title === '新建会话' || !s.title);
        if (isFirstUserMsg) {
          const cleaned = msg.content
            .replace(/`@[\u4e00-\u9fa5\w-]+`/g, '')
            .replace(/@[\u4e00-\u9fa5\w-]+/g, '')
            .trim();
          title = cleaned.slice(0, 24) + (cleaned.length > 24 ? '…' : '');
          if (!title) title = '新建会话';
        }
        if (title !== s.title) titleToPatch = title;
        return { ...s, messages, title, updatedAt: Date.now() };
      })
    );
    if (titleToPatch && !localMode) {
      api.patchSession(sessionId, { title: titleToPatch }).catch((err) => console.warn('更新标题失败:', err));
    }
    if (msg.role === 'system' && !localMode) {
      api
        .appendMessage(sessionId, {
          id: msg.id,
          role: msg.role,
          content: msg.content,
          extra: buildMessageExtra(msg),
        })
        .catch((err) => console.warn('追加消息失败:', err));
    }
  }, [localMode]);

  const updateMessage = useCallback((sessionId: string, id: string, updates: Partial<Message>) => {
    setSessions((prev) =>
      prev.map((s) =>
        s.id === sessionId
          ? { ...s, messages: s.messages.map((m) => (m.id === id ? { ...m, ...updates } : m)) }
          : s
      )
    );
  }, []);

  const updateSessionSkill = useCallback((skillId: string) => {
    const curId = activeSessionIdRef.current;
    if (!curId) return;
    setSessions((prev) => prev.map((s) => (s.id === curId ? { ...s, skillId, updatedAt: Date.now() } : s)));
    if (!localMode) {
      api.patchSession(curId, { skill_id: skillId }).catch((err) => console.warn('更新 skill_id 失败:', err));
    }
  }, [localMode]);

  const logout = useCallback(() => {
    removeStorage(ACTIVE_SESSION_KEY);
    window.location.href = `${BACKEND_URL}/api/v1/auth/logout`;
  }, []);

  return {
    authChecked,
    authRequired,
    authChecking,
    checkAuthState,
    currentUser,
    tab,
    setTab,
    sessions,
    projects,
    projectsEnabled: !localMode,
    activeSessionId,
    activeSession,
    systemSkills,
    userSkills,
    allSkills,
    skillsLoading,
    refreshSkills,
    harness,
    setHarness,
    refreshSessions,
    refreshProjects,
    selectSession,
    openChat,
    createNewSession,
    moveSession,
    deleteSession,
    addMessage,
    updateMessage,
    updateSessionSkill,
    logout,
  };
}
