import React, { useState, useRef, useEffect, useMemo } from 'react';
import type {
  Message,
  ChatSession,
  Skill,
  SkillAction,
  Project,
  RuntimeMode,
} from '../types';
import { api } from '../services/api';
import { isSupportedFileName } from '../utils/supportedFiles';
import type { GeneratedFile } from '../utils/chatFiles';
import { createMessageId } from '../utils/chatFiles';

export interface ChatAreaProps {
  session: ChatSession | null;
  skills: Skill[];
  onSendMessage: (sessionId: string, msg: Message) => void;
  onUpdateMessage: (
    sessionId: string,
    id: string,
    updates: Partial<Message>,
  ) => void;
  onToggleReferences: () => void;
  rightPanelOpen: boolean;
  onExecuteAction: (action: SkillAction) => void;
  onUpdateSessionSkill?: (skillId: string) => void;
  project: Project | null;
  projects: Project[];
  onMoveSession: (projectId: string | null) => Promise<void>;
  onOpenProject: (projectId: string) => void;
  onImportProjectFile?: (path: string, displayName: string) => Promise<void>;
  onRefreshSession: (sessionId: string) => Promise<void>;
  onRunningSessionsChange?: (sessionIds: Set<string>) => void;
  model: string;
  onModelChange: (model: string) => void;
  runtimeMode: RuntimeMode;
  onRuntimeModeChange: (mode: RuntimeMode) => void;
}

type ActiveExecution = {
  assistantId: string;
  controller: AbortController;
  model: string;
};

const activeExecutions = new Map<string, ActiveExecution>();
const serverRunningSessions = new Set<string>();
const pendingControlRuns = new Map<string, number>();
const controlRunTrackers = new Map<string, { cancelled: boolean }>();
const executionListeners = new Set<(sessionIds: Set<string>) => void>();
const FOLLOW_UP_MODE_KEY = 'eido-follow-up-mode';

function initialFollowUpMode(): 'queue' | 'steer' {
  try {
    return localStorage.getItem(FOLLOW_UP_MODE_KEY) === 'steer'
      ? 'steer'
      : 'queue';
  } catch {
    return 'queue';
  }
}

function publishExecutions() {
  const snapshot = new Set([
    ...activeExecutions.keys(),
    ...serverRunningSessions,
    ...[...pendingControlRuns.entries()]
      .filter(([, count]) => count > 0)
      .map(([sessionId]) => sessionId),
  ]);
  executionListeners.forEach((listener) => listener(snapshot));
}

export function useChatController({
  session,
  skills,
  onSendMessage,
  onUpdateMessage,
  project,
  onImportProjectFile,
  onRefreshSession,
  onRunningSessionsChange,
  model,
  runtimeMode,
}: ChatAreaProps) {
  const [input, setInput] = useState('');
  const [runningSessionIds, setRunningSessionIds] = useState<Set<string>>(
    () => new Set(activeExecutions.keys()),
  );
  const [deliveryMode, setDeliveryMode] = useState<'queue' | 'steer'>(
    initialFollowUpMode,
  );
  const [deliveryMenuOpen, setDeliveryMenuOpen] = useState(false);
  const [serverSteerAvailable, setServerSteerAvailable] = useState(false);
  const [attachments, setAttachments] = useState<
    { name: string; path: string }[]
  >([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [projectImportStatus, setProjectImportStatus] = useState<
    Record<string, 'adding' | 'added'>
  >({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mentionMenu, setMentionMenu] = useState<{
    visible: boolean;
    filter: string;
    index: number;
    pos: { top: number; left: number };
  }>({
    visible: false,
    filter: '',
    index: 0,
    pos: { top: 0, left: 0 },
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);
  const mentionMenuRef = useRef<HTMLDivElement>(null);
  const inputContainerRef = useRef<HTMLDivElement>(null);
  const previousSessionIdRef = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(session?.id ?? null);
  const visibleMessageIdsRef = useRef<Set<string>>(new Set());
  const visibleMessagesRef = useRef<Map<string, Message>>(new Map());
  const lastQueueStatusRef = useRef<Record<string, string>>({});
  currentSessionIdRef.current = session?.id ?? null;
  visibleMessageIdsRef.current = new Set(
    session?.messages.map((message) => message.id) || [],
  );
  visibleMessagesRef.current = new Map(
    (session?.messages || []).map((message) => [message.id, message]),
  );
  // 每条 assistant 消息的 thinking 事件累积日志：msgId → string[]
  const thinkingLogsRef = useRef<Record<string, string[]>>({});

  const persistedSessionRunning = Boolean(
    session?.messages.some(
      (message) => message.role === 'assistant' && message.streaming,
    ),
  );
  const activeSessionRunning = Boolean(
    session?.id &&
    (runningSessionIds.has(session.id) || persistedSessionRunning),
  );
  const activeSessionCanStop = Boolean(
    session?.id && activeExecutions.has(session.id),
  );
  const activeExecutionModel = session?.id
    ? activeExecutions.get(session.id)?.model
    : undefined;
  const steerAvailable = serverSteerAvailable;
  const effectiveDeliveryMode =
    deliveryMode === 'steer' && steerAvailable ? 'steer' : 'queue';
  const queuedMessages = useMemo(
    () =>
      (session?.messages || [])
        .filter(
          (message) =>
            message.role === 'user' && message.deliveryStatus === 'queued',
        )
        .sort(
          (left, right) =>
            (left.queuePosition || 0) - (right.queuePosition || 0),
        ),
    [session?.messages],
  );
  const conversationMessages = useMemo(
    () =>
      (session?.messages || []).filter(
        (message) =>
          message.deliveryStatus !== 'queued' &&
          message.deliveryStatus !== 'cancelled',
      ),
    [session?.messages],
  );

  useEffect(() => {
    executionListeners.add(setRunningSessionIds);
    publishExecutions();
    return () => {
      executionListeners.delete(setRunningSessionIds);
    };
  }, []);

  useEffect(() => {
    onRunningSessionsChange?.(runningSessionIds);
  }, [onRunningSessionsChange, runningSessionIds]);

  useEffect(() => {
    try {
      localStorage.setItem(FOLLOW_UP_MODE_KEY, deliveryMode);
    } catch {}
  }, [deliveryMode]);

  useEffect(() => {
    if (!activeSessionRunning) setDeliveryMenuOpen(false);
  }, [activeSessionRunning]);

  const markSessionRunning = (
    sessionId: string,
    execution?: ActiveExecution,
  ) => {
    if (execution) activeExecutions.set(sessionId, execution);
    else activeExecutions.delete(sessionId);
    publishExecutions();
  };

  const trackControlRun = (
    sessionId: string,
    messageId: string,
    assistantId: string,
  ) => {
    const tracker = { cancelled: false };
    controlRunTrackers.set(messageId, tracker);
    pendingControlRuns.set(
      sessionId,
      (pendingControlRuns.get(sessionId) || 0) + 1,
    );
    publishExecutions();
    void (async () => {
      try {
        for (let attempt = 0; attempt < 180; attempt += 1) {
          if (tracker.cancelled) return;
          await new Promise((resolve) => window.setTimeout(resolve, 1500));
          if (tracker.cancelled) return;
          const detail = await api.getSession(sessionId);
          if (detail.messages.some((message) => message.id === assistantId)) {
            await onRefreshSession(sessionId);
            return;
          }
        }
      } catch (error) {
        console.warn('刷新排队执行结果失败:', error);
      } finally {
        if (controlRunTrackers.get(messageId) === tracker) {
          controlRunTrackers.delete(messageId);
        }
        const remaining = Math.max(
          0,
          (pendingControlRuns.get(sessionId) || 1) - 1,
        );
        if (remaining) pendingControlRuns.set(sessionId, remaining);
        else pendingControlRuns.delete(sessionId);
        publishExecutions();
      }
    })();
  };

  useEffect(() => {
    if (!session?.id) return;
    const sessionId = session.id;
    let cancelled = false;
    const syncStatus = async () => {
      try {
        const status = await api.getChatQueue(sessionId);
        if (cancelled) return;
        setServerSteerAvailable(status.steer_available);

        status.items.forEach((item) => {
          if (visibleMessageIdsRef.current.has(item.message_id)) {
            const visible = visibleMessagesRef.current.get(item.message_id);
            if (
              visible?.queuePosition !== item.position ||
              visible.deliveryStatus !== 'queued'
            ) {
              onUpdateMessage(sessionId, item.message_id, {
                deliveryMode: item.mode,
                deliveryStatus: 'queued',
                queuePosition: item.position,
              });
            }
            return;
          }
          visibleMessageIdsRef.current.add(item.message_id);
          onSendMessage(sessionId, {
            id: item.message_id,
            role: 'user',
            content: item.content,
            deliveryMode: item.mode,
            deliveryStatus: 'queued',
            queuePosition: item.position,
            timestamp: Date.now(),
          });
        });

        const statusSignature = `${status.active}:${status.count}`;
        const previousStatus = lastQueueStatusRef.current[sessionId];
        lastQueueStatusRef.current[sessionId] = statusSignature;
        if (
          previousStatus !== undefined &&
          previousStatus !== statusSignature
        ) {
          await onRefreshSession(sessionId);
        }

        if (
          !activeExecutions.has(sessionId) &&
          !pendingControlRuns.has(sessionId)
        ) {
          if (status.active || status.count > 0)
            serverRunningSessions.add(sessionId);
          else serverRunningSessions.delete(sessionId);
        }
        publishExecutions();
      } catch {
        // An older backend may not expose queue status yet.
        setServerSteerAvailable(false);
      }
    };
    void syncStatus();
    const timer = window.setInterval(syncStatus, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      setServerSteerAvailable(false);
    };
  }, [session?.id]);

  const getTextareaEl = () => {
    const ref = inputRef.current;
    // antd TextArea stores the real textarea in resizableTextArea.textArea
    return ref?.resizableTextArea?.textArea || ref || null;
  };

  // 键盘上下选择技能时，让高亮项保持在菜单可视区内
  useEffect(() => {
    if (!mentionMenu.visible) return;
    const menu = mentionMenuRef.current;
    if (!menu) return;
    const item = menu.querySelectorAll('button')[mentionMenu.index] as
      HTMLElement | undefined;
    if (!item) return;
    if (mentionMenu.index === 0) {
      menu.scrollTop = 0;
      return;
    }
    const itemTop = item.offsetTop;
    const itemBottom = itemTop + item.offsetHeight;
    if (itemTop < menu.scrollTop) {
      menu.scrollTop = itemTop;
    } else if (itemBottom > menu.scrollTop + menu.clientHeight) {
      menu.scrollTop = itemBottom - menu.clientHeight;
    }
  }, [mentionMenu.visible, mentionMenu.index, mentionMenu.filter]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [session?.messages, activeSessionRunning]);

  // 当切换到财报点评技能的新会话时，自动设置默认输入
  useEffect(() => {
    if (session && session.id !== previousSessionIdRef.current) {
      previousSessionIdRef.current = session.id;

      // 检查是否是财报点评技能（s1）且是新会话（只有初始消息）
      if (session.skillId === 's1' && session.messages.length <= 1) {
        setInput('中望软件 2025三季报');
        // 聚焦输入框
        setTimeout(() => {
          inputRef.current?.focus();
        }, 100);
      } else {
        // 切换到其他会话时清空输入
        setInput('');
      }
      // 附件已上传到原会话工作区，绝不能跨会话复用路径。
      setAttachments([]);
      setUploadError('');
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [session]);

  useEffect(() => {
    setProjectImportStatus({});
  }, [session?.id, project?.id]);

  const activeSkill = useMemo(
    () =>
      session?.skillId ? skills.find((s) => s.id === session.skillId) : null,
    [session?.skillId, skills],
  );

  const importGeneratedFile = async (file: GeneratedFile) => {
    if (!onImportProjectFile || !project || projectImportStatus[file.path])
      return;
    setProjectImportStatus((prev) => ({ ...prev, [file.path]: 'adding' }));
    try {
      await onImportProjectFile(file.path, file.name);
      setProjectImportStatus((prev) => ({ ...prev, [file.path]: 'added' }));
    } catch (error) {
      setProjectImportStatus((prev) => {
        const next = { ...prev };
        delete next[file.path];
        return next;
      });
      window.alert(
        error instanceof Error
          ? error.message
          : `加入 ${project.name} 项目资料失败`,
      );
    }
  };

  const filteredSkills = useMemo(() => {
    return skills.filter((s) =>
      s.name.toLowerCase().includes(mentionMenu.filter.toLowerCase()),
    );
  }, [skills, mentionMenu.filter]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    const cursorPosition = e.target.selectionStart || 0;
    const textBeforeCursor = value.slice(0, cursorPosition);
    const atMatch = textBeforeCursor.match(/@([\u4e00-\u9fa5\w\-]*)$/);

    if (atMatch) {
      // 菜单锚定在输入框正上方并限制在视口内：逐字符估算光标坐标对中文严重偏移，
      // 且估算位置可能落入输入框区域，被后绘制的输入框盖住导致菜单项点不到
      const MENTION_MENU_WIDTH = 256; // w-64
      const MENTION_MENU_MARGIN = 8;
      const textareaEl = getTextareaEl() as HTMLTextAreaElement | null;
      const textareaRect = textareaEl?.getBoundingClientRect();
      const minLeft = MENTION_MENU_MARGIN;
      const maxLeft = Math.max(
        minLeft,
        window.innerWidth - MENTION_MENU_WIDTH - MENTION_MENU_MARGIN,
      );
      const left = textareaRect
        ? Math.min(maxLeft, Math.max(minLeft, textareaRect.left))
        : minLeft;
      const top = textareaRect
        ? Math.max(MENTION_MENU_MARGIN, textareaRect.top - MENTION_MENU_MARGIN)
        : MENTION_MENU_MARGIN;

      setMentionMenu({
        visible: true,
        filter: atMatch[1],
        index: 0,
        pos: { top, left },
      });
    } else {
      setMentionMenu((prev) => ({ ...prev, visible: false }));
    }
    setInput(value);
  };

  const insertMention = (skill: Skill) => {
    const textarea = getTextareaEl() as HTMLTextAreaElement | null;
    const currentValue = textarea?.value ?? input;
    const cursorPosition = textarea?.selectionStart ?? currentValue.length;
    const filterLength = mentionMenu.filter.length;

    let atPos = currentValue.lastIndexOf('@', Math.max(0, cursorPosition - 1));
    if (atPos === -1) atPos = currentValue.lastIndexOf('@');
    if (atPos === -1) return;

    const replaceEnd = Math.min(currentValue.length, atPos + 1 + filterLength);
    const newValue =
      currentValue.slice(0, atPos) +
      `\`@${skill.name}\` ` +
      currentValue.slice(replaceEnd);
    setInput(newValue);
    setMentionMenu((previous) => ({
      ...previous,
      visible: false,
      filter: '',
      index: 0,
    }));

    setTimeout(() => {
      textarea?.focus();
      const newPos = atPos + skill.name.length + 4; // `@name` plus trailing space
      textarea?.setSelectionRange(newPos, newPos);
    }, 0);
  };

  /** 构建单条消息的 thinking 累积回调 */
  const makeUpdater = (sessionId: string, assistantId: string) => {
    thinkingLogsRef.current[assistantId] = [];
    return (
      content: string,
      thinking: string,
      steps?: any,
      confirmation?: any,
      references?: any,
      mermaid?: string,
    ) => {
      if (thinking) {
        const log = thinkingLogsRef.current[assistantId];
        if (log[log.length - 1] !== thinking) {
          log.push(thinking);
        }
      }
      onUpdateMessage(sessionId, assistantId, {
        content,
        thinking,
        thinkingLog: [...thinkingLogsRef.current[assistantId]],
        executionSteps: steps,
        pendingConfirmation: confirmation,
        references,
        workflowMermaid: mermaid,
      });
    };
  };

  /** 单次执行：无论是否有技能提示，统一交由后端 claude_agent_sdk 自动规划 */
  const runSingleSkill = async (
    sessionId: string,
    msgs: Message[],
    assistantId: string,
  ) => {
    const controller = new AbortController();
    markSessionRunning(sessionId, { assistantId, controller, model });
    try {
      await api.streamChat(
        msgs,
        makeUpdater(sessionId, assistantId),
        sessionId,
        assistantId,
        undefined,
        undefined,
        controller.signal,
        model,
        runtimeMode,
      );
    } finally {
      delete thinkingLogsRef.current[assistantId];
      if (activeExecutions.get(sessionId)?.assistantId === assistantId) {
        markSessionRunning(sessionId);
      }
    }
  };

  /** 用户点击停止，中断当前执行 */
  const handleStop = () => {
    if (session) activeExecutions.get(session.id)?.controller.abort();
  };

  /** 多技能串行流水线：每个技能独立生成一条 assistant 消息，前一步输出传给下一步 */
  const runPipeline = async (
    sessionId: string,
    baseMessages: Message[],
    orderedSkills: typeof skills,
  ) => {
    let previousOutput = '';
    let contextMessages = [...baseMessages];
    const controller = new AbortController();

    for (let i = 0; i < orderedSkills.length; i++) {
      const skill = orderedSkills[i];
      const assistantId = createMessageId(`pipeline-${i}`);
      markSessionRunning(sessionId, { assistantId, controller, model });

      const placeholder: Message = {
        id: assistantId,
        role: 'assistant',
        content: '',
        thinking: `正在启动步骤 ${i + 1}/${orderedSkills.length}：${skill.name}...`,
        timestamp: Date.now(),
        references: [],
      };
      onSendMessage(sessionId, placeholder);

      let finalContent = '';
      const updater = makeUpdater(sessionId, assistantId);
      try {
        await api.streamChat(
          contextMessages,
          (content, thinking, steps, confirmation, references, mermaid) => {
            finalContent = content;
            updater(
              content,
              thinking,
              steps,
              confirmation,
              references,
              mermaid,
            );
          },
          sessionId,
          assistantId,
          previousOutput || undefined,
          skill.id,
          controller.signal,
          model,
          runtimeMode,
        );
      } catch {
        delete thinkingLogsRef.current[assistantId];
        break;
      }
      delete thinkingLogsRef.current[assistantId];
      previousOutput = finalContent;
      contextMessages = [
        ...contextMessages,
        { ...placeholder, content: finalContent },
      ];
    }
    if (activeExecutions.get(sessionId)?.controller === controller) {
      markSessionRunning(sessionId);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    if (!session) {
      console.warn('未选择会话，无法上传文件');
      return;
    }
    const targetSessionId = session.id;
    setUploading(true);
    setUploadError('');
    try {
      for (let i = 0; i < files.length; i++) {
        if (currentSessionIdRef.current !== targetSessionId) break;
        const f = files[i];
        if (!isSupportedFileName(f.name)) {
          setUploadError(`不支持的文件格式：${f.name}`);
          continue;
        }
        const { path } = await api.uploadChatFile(f, targetSessionId);
        // 上传请求不能取消；切会话后丢弃旧会话返回的路径，防止附件串入新会话。
        if (currentSessionIdRef.current === targetSessionId) {
          setAttachments((prev) => [...prev, { name: f.name, path }]);
        }
      }
    } catch (err) {
      console.error('上传失败:', err);
      if (currentSessionIdRef.current === targetSessionId) {
        setUploadError(err instanceof Error ? err.message : '上传失败，请重试');
      }
    } finally {
      setUploading(false);
    }
    e.target.value = '';
  };

  const removeAttachment = (idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  const buildContentWithAttachments = (text: string): string => {
    if (attachments.length === 0) return text.trim();
    const parts: string[] = [text.trim()];
    parts.push(
      '\n\n---\n\n**用户上传的文件（已保存至服务端，可直接读取）:**\n',
    );
    for (const a of attachments) {
      parts.push(`\n- ${a.name}: \`${a.path}\`\n`);
    }
    return parts.join('');
  };

  const submitFollowUp = async (
    content: string,
    requestedMode: 'queue' | 'steer',
    existingMessage?: Message,
  ) => {
    if (!session) return;
    const targetSessionId = session.id;
    const userMsg: Message = existingMessage || {
      id: createMessageId('user'),
      role: 'user',
      content,
      timestamp: Date.now(),
    };
    const nextStatus = requestedMode === 'queue' ? 'queued' : 'applied';
    if (existingMessage) {
      onUpdateMessage(targetSessionId, userMsg.id, {
        deliveryMode: requestedMode,
        deliveryStatus: nextStatus,
        queuePosition: undefined,
      });
    } else {
      onSendMessage(targetSessionId, {
        ...userMsg,
        deliveryMode: requestedMode,
        deliveryStatus: nextStatus,
      });
    }

    try {
      const assistantId = createMessageId('assistant');
      const controlModel = activeExecutionModel || model;
      const result = await api.controlChat({
        mode: requestedMode,
        session_id: targetSessionId,
        message: { id: userMsg.id, role: 'user', content },
        assistant_message_id: assistantId,
        model: controlModel,
        runtime_mode: runtimeMode,
      });
      onUpdateMessage(targetSessionId, userMsg.id, {
        deliveryMode: requestedMode,
        deliveryStatus: result.status === 'queued' ? 'queued' : 'applied',
        queuePosition: result.position,
      });
      if (result.status === 'queued') {
        trackControlRun(targetSessionId, userMsg.id, assistantId);
      } else if (existingMessage) {
        const tracker = controlRunTrackers.get(existingMessage.id);
        if (tracker) tracker.cancelled = true;
      }
    } catch (error) {
      onUpdateMessage(targetSessionId, userMsg.id, {
        deliveryStatus: 'failed',
      });
      window.alert(error instanceof Error ? error.message : '提交消息失败');
    }
  };

  const deleteQueuedMessage = async (message: Message) => {
    if (!session) return;
    try {
      await api.deleteQueuedChatMessage(session.id, message.id);
      const tracker = controlRunTrackers.get(message.id);
      if (tracker) tracker.cancelled = true;
      onUpdateMessage(session.id, message.id, { deliveryStatus: 'cancelled' });
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '删除排队消息失败');
      await onRefreshSession(session.id);
    }
  };

  const editQueuedMessage = async (message: Message) => {
    if (!session) return;
    try {
      await api.deleteQueuedChatMessage(session.id, message.id);
      const tracker = controlRunTrackers.get(message.id);
      if (tracker) tracker.cancelled = true;
      onUpdateMessage(session.id, message.id, { deliveryStatus: 'cancelled' });
      setInput(message.content);
      window.setTimeout(() => getTextareaEl()?.focus(), 0);
    } catch (error) {
      window.alert(
        error instanceof Error ? error.message : '消息已开始执行，无法编辑',
      );
      await onRefreshSession(session.id);
    }
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const hasContent = input.trim() || attachments.length > 0;
    if (!hasContent || !session) return;
    // 整次异步执行固定写回发起时的会话，切换侧栏不会改变目标。
    const targetSessionId = session.id;

    // 按在文本中出现的位置顺序，找出所有被 @ 提及的技能
    const textForMention = input.trim() || '请分析';
    const mentionedSkills = skills
      .map((s) => ({ skill: s, pos: textForMention.indexOf(`@${s.name}`) }))
      .filter(({ pos }) => pos !== -1)
      .sort((a, b) => a.pos - b.pos)
      .map(({ skill }) => skill);

    const content = buildContentWithAttachments(
      input.trim() || '请分析我上传的文件。',
    );

    if (activeSessionRunning) {
      const requestedMode = effectiveDeliveryMode;
      setInput('');
      setAttachments([]);
      await submitFollowUp(content, requestedMode);
      return;
    }

    const userMsg: Message = {
      id: createMessageId('user'),
      role: 'user',
      content,
      timestamp: Date.now(),
    };

    setInput('');
    setAttachments([]);
    onSendMessage(targetSessionId, userMsg);

    const baseMessages = [...(session?.messages || []), userMsg];
    try {
      if (mentionedSkills.length >= 2) {
        // 多技能流水线
        await runPipeline(targetSessionId, baseMessages, mentionedSkills);
      } else {
        // 单次执行（有或无 @mention 均交由后端自动规划）
        const assistantId = createMessageId('assistant');
        onSendMessage(targetSessionId, {
          id: assistantId,
          role: 'assistant',
          content: '',
          thinking: '正在分析请求，自动规划执行...',
          timestamp: Date.now(),
          references: [],
        });
        await runSingleSkill(targetSessionId, baseMessages, assistantId);
      }
    } catch (err) {
      console.error('执行失败:', err);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mentionMenu.visible) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionMenu((prev) => ({
          ...prev,
          index: (prev.index + 1) % (filteredSkills.length || 1),
        }));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionMenu((prev) => ({
          ...prev,
          index:
            (prev.index - 1 + (filteredSkills.length || 1)) %
            (filteredSkills.length || 1),
        }));
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (filteredSkills.length > 0) {
          e.preventDefault();
          insertMention(filteredSkills[mentionMenu.index]);
        }
      } else if (e.key === 'Escape') {
        setMentionMenu((prev) => ({ ...prev, visible: false }));
      }
      return;
    }
    if (e.key === 'Escape' && deliveryMenuOpen) {
      setDeliveryMenuOpen(false);
      return;
    }
    if (
      e.key === 'Enter' &&
      !e.shiftKey &&
      !(e.nativeEvent as KeyboardEvent).isComposing
    ) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const handleConfirmation = async (approved: boolean, messageId: string) => {
    if (!session) return;
    const targetSessionId = session.id;
    if (approved) {
      const msg = session?.messages.find((m) => m.id === messageId);
      if (msg) {
        const updatedSteps = msg.executionSteps?.map((s) =>
          s.status === 'waiting'
            ? {
                ...s,
                status: 'completed' as const,
                description: 'Access granted by user.',
              }
            : s,
        );
        onUpdateMessage(targetSessionId, messageId, {
          pendingConfirmation: undefined,
          executionSteps: updatedSteps,
          thinking:
            'Access granted. Re-engaging evidence collection protocols...',
        });

        const updatedMessages =
          session?.messages.map((m) =>
            m.id === messageId
              ? {
                  ...m,
                  pendingConfirmation: undefined,
                  executionSteps: updatedSteps,
                }
              : m,
          ) || [];

        await runSingleSkill(targetSessionId, updatedMessages, messageId);
      }
    } else {
      onUpdateMessage(targetSessionId, messageId, {
        pendingConfirmation: undefined,
        thinking: 'Workflow halted. Data access denied by user.',
      });
    }
  };

  return {
    input,
    setInput,
    activeSessionRunning,
    activeSessionCanStop,
    steerAvailable,
    effectiveDeliveryMode,
    deliveryMode,
    setDeliveryMode,
    deliveryMenuOpen,
    setDeliveryMenuOpen,
    attachments,
    uploading,
    uploadError,
    projectImportStatus,
    fileInputRef,
    mentionMenu,
    setMentionMenu,
    scrollRef,
    inputRef,
    mentionMenuRef,
    inputContainerRef,
    queuedMessages,
    conversationMessages,
    activeSkill,
    filteredSkills,
    handleInputChange,
    insertMention,
    importGeneratedFile,
    handleFileSelect,
    removeAttachment,
    handleSubmit,
    handleStop,
    handleKeyDown,
    handleConfirmation,
    submitFollowUp,
    deleteQueuedMessage,
    editQueuedMessage,
  };
}
