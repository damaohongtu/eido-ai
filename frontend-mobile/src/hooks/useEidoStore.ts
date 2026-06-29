import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  hydrateSession,
  summaryToSession,
  BACKEND_URL,
  INITIAL_CHAT_STATE,
} from '../shared';
import type { ChatSession, Message, Skill } from '../shared';

export type MobileTab = 'chat' | 'skills' | 'me';

const ACTIVE_SESSION_KEY = 'eido_m_active_session_id';
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
  currentUser: { user_id: string; username: string } | null;

  tab: MobileTab;
  setTab: (t: MobileTab) => void;

  sessions: ChatSession[];
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
  selectSession: (id: string) => Promise<void>;
  openChat: (id: string) => Promise<void>;
  createNewSession: (skillId?: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  addMessage: (msg: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  updateSessionSkill: (skillId: string) => void;
  logout: () => void;
}

export function useEidoStore(): EidoStore {
  const [authChecked, setAuthChecked] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ user_id: string; username: string } | null>(null);
  const [tab, setTab] = useState<MobileTab>('chat');

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 用 ref 读取当前会话 id，避免在 setState updater 内嵌套 setState（StrictMode 下会重复执行副作用）
  const activeSessionIdRef = useRef<string | null>(null);
  // 落地初始化只执行一次（避免 StrictMode 双调导致重复创建空会话）
  const bootstrappedRef = useRef(false);

  const [systemSkills, setSystemSkills] = useState<Skill[]>([]);
  const [userSkills, setUserSkills] = useState<Skill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);

  const [harness, setHarnessState] = useState<string>(() => readStorage<string>(HARNESS_KEY, 'claude_code'));

  const setHarness = useCallback((h: string) => {
    setHarnessState(h);
    writeStorage(HARNESS_KEY, h);
  }, []);

  // 鉴权（登录态来自 /api/v1/auth/me；未登录跳后端登录）
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has('login')) {
      params.delete('login');
      const clean = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (clean ? `?${clean}` : ''));
    }
    api.checkAuth().then((user) => {
      if (!user) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      setCurrentUser(user);
      setAuthChecked(true);
      api.warmupSandbox().catch(() => undefined);
    });
  }, []);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
    if (activeSessionId) writeStorage(ACTIVE_SESSION_KEY, activeSessionId);
    else removeStorage(ACTIVE_SESSION_KEY);
  }, [activeSessionId]);

  // 拉取会话列表 + 落地即进入聊天（恢复上次会话 / 打开最近会话 / 无则自动新建）
  useEffect(() => {
    if (!authChecked || bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    (async () => {
      try {
        const list = await api.listSessions();
        const summaries = list.map(summaryToSession);
        setSessions(summaries);

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
            activeSessionIdRef.current = targetId;
            setActiveSessionId(targetId);
          } catch {
            removeStorage(ACTIVE_SESSION_KEY);
            await createNewSession();
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
  }, [authChecked]);

  // 加载技能
  const refreshSkills = useCallback(async () => {
    try {
      const [systemResult, userResult] = await Promise.all([
        api.getSkills({ is_system: true, limit: 100 }),
        api.getSkills({ is_system: false, limit: 100 }),
      ]);
      setSystemSkills(systemResult.items);
      setUserSkills(userResult.items);
    } catch (error) {
      console.error('加载技能失败:', error);
    }
  }, []);

  useEffect(() => {
    if (!authChecked) return;
    setSkillsLoading(true);
    refreshSkills().finally(() => setSkillsLoading(false));
  }, [authChecked, refreshSkills]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || null,
    [sessions, activeSessionId]
  );
  const allSkills = useMemo(() => [...systemSkills, ...userSkills], [systemSkills, userSkills]);

  const refreshSessions = useCallback(async () => {
    try {
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
  }, []);

  const selectSession = useCallback(
    async (id: string) => {
      const target = sessions.find((s) => s.id === id);
      if (target && target.messages.length === 0) {
        try {
          const detail = await api.getSession(id);
          const hydrated = fixStaleRunningSteps(hydrateSession(detail));
          setSessions((prev) => prev.map((s) => (s.id === id ? hydrated : s)));
        } catch (err) {
          console.error('加载会话消息失败:', err);
          return;
        }
      }
      activeSessionIdRef.current = id;
      setActiveSessionId(id);
    },
    [sessions]
  );

  const openChat = useCallback(
    async (id: string) => {
      await selectSession(id);
      setTab('chat');
    },
    [selectSession]
  );

  const createNewSession = useCallback(async (skillId?: string) => {
    try {
      const created = await api.createSession({ skill_id: skillId ?? null });
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
      setSessions((prev) => [newSession, ...prev]);
      activeSessionIdRef.current = newSession.id;
      setActiveSessionId(newSession.id);
      setTab('chat');
    } catch (err) {
      console.error('创建会话失败:', err);
    }
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
      } catch (err) {
        console.error('删除会话失败:', err);
        return;
      }
      const remaining = sessions.filter((s) => s.id !== id);
      setSessions(remaining);
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
    [sessions, openChat]
  );

  const addMessage = useCallback((msg: Message) => {
    const curId = activeSessionIdRef.current;
    if (!curId) return;
    let titleToPatch: string | null = null;
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== curId) return s;
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
    if (titleToPatch) {
      api.patchSession(curId, { title: titleToPatch }).catch((err) => console.warn('更新标题失败:', err));
    }
    if (msg.role === 'system') {
      api
        .appendMessage(curId, {
          id: msg.id,
          role: msg.role,
          content: msg.content,
          extra: buildMessageExtra(msg),
        })
        .catch((err) => console.warn('追加消息失败:', err));
    }
  }, []);

  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    const curId = activeSessionIdRef.current;
    if (!curId) return;
    setSessions((prev) =>
      prev.map((s) =>
        s.id === curId
          ? { ...s, messages: s.messages.map((m) => (m.id === id ? { ...m, ...updates } : m)) }
          : s
      )
    );
  }, []);

  const updateSessionSkill = useCallback((skillId: string) => {
    const curId = activeSessionIdRef.current;
    if (!curId) return;
    setSessions((prev) => prev.map((s) => (s.id === curId ? { ...s, skillId, updatedAt: Date.now() } : s)));
    api.patchSession(curId, { skill_id: skillId }).catch((err) => console.warn('更新 skill_id 失败:', err));
  }, []);

  const logout = useCallback(() => {
    removeStorage(ACTIVE_SESSION_KEY);
    window.location.href = `${BACKEND_URL}/api/v1/auth/logout`;
  }, []);

  return {
    authChecked,
    currentUser,
    tab,
    setTab,
    sessions,
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
    selectSession,
    openChat,
    createNewSession,
    deleteSession,
    addMessage,
    updateMessage,
    updateSessionSkill,
    logout,
  };
}
