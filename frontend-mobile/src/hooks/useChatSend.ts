import { useCallback, useRef, useState } from 'react';
import { api } from '../shared';
import type { ChatSession, Message, Skill } from '../shared';

export function createMessageId(prefix = 'msg'): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface Attachment {
  name: string;
  path: string;
}

interface UseChatSendArgs {
  session: ChatSession | null;
  skills: Skill[];
  harness: string;
  addMessage: (msg: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  browserContext?: string;
}

/**
 * 聊天发送：与 PC 端 ChatArea 行为一致。
 * - 单 @技能 / 无技能：交由后端自动规划，单次流式执行
 * - 多 @技能：串行流水线，前一步输出作为下一步 context
 */
export function useChatSend({ session, skills, harness, addMessage, updateMessage, browserContext }: UseChatSendArgs) {
  const [isTyping, setIsTyping] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingLogsRef = useRef<Record<string, string[]>>({});

  const makeUpdater = useCallback(
    (assistantId: string) => {
      thinkingLogsRef.current[assistantId] = [];
      return (
        content: string,
        thinking: string,
        steps?: Message['executionSteps'],
        confirmation?: Message['pendingConfirmation'],
        references?: Message['references'],
        mermaid?: string
      ) => {
        if (thinking) {
          const log = thinkingLogsRef.current[assistantId];
          if (log && log[log.length - 1] !== thinking) log.push(thinking);
        }
        updateMessage(assistantId, {
          content,
          thinking,
          thinkingLog: [...(thinkingLogsRef.current[assistantId] || [])],
          executionSteps: steps,
          pendingConfirmation: confirmation,
          references,
          workflowMermaid: mermaid,
        });
      };
    },
    [updateMessage]
  );

  const runSingle = useCallback(
    async (msgs: Message[], assistantId: string) => {
      if (!session) return;
      abortRef.current = new AbortController();
      try {
        await api.streamChat(
          msgs,
          makeUpdater(assistantId),
          session.id,
          assistantId,
          browserContext || undefined,
          undefined,
          abortRef.current.signal,
          harness
        );
      } finally {
        delete thinkingLogsRef.current[assistantId];
      }
    },
    [session, harness, makeUpdater, browserContext]
  );

  const runPipeline = useCallback(
    async (baseMessages: Message[], orderedSkills: Skill[]) => {
      if (!session) return;
      let previousOutput = '';
      let contextMessages = [...baseMessages];
      abortRef.current = new AbortController();

      for (let i = 0; i < orderedSkills.length; i++) {
        const skill = orderedSkills[i];
        const assistantId = createMessageId(`pipeline-${i}`);
        const placeholder: Message = {
          id: assistantId,
          role: 'assistant',
          content: '',
          thinking: `正在启动步骤 ${i + 1}/${orderedSkills.length}：${skill.name}...`,
          timestamp: Date.now(),
          references: [],
        };
        addMessage(placeholder);

        let finalContent = '';
        const updater = makeUpdater(assistantId);
        try {
          await api.streamChat(
            contextMessages,
            (content, thinking, steps, confirmation, references, mermaid) => {
              finalContent = content;
              updater(content, thinking, steps, confirmation, references, mermaid);
            },
            session.id,
            assistantId,
            [browserContext, previousOutput].filter(Boolean).join('\n\n') || undefined,
            skill.id,
            abortRef.current?.signal,
            harness
          );
        } catch {
          delete thinkingLogsRef.current[assistantId];
          break;
        }
        delete thinkingLogsRef.current[assistantId];
        previousOutput = finalContent;
        contextMessages = [...contextMessages, { ...placeholder, content: finalContent }];
      }
    },
    [session, harness, addMessage, makeUpdater, browserContext]
  );

  const buildContentWithAttachments = (text: string, attachments: Attachment[]): string => {
    if (attachments.length === 0) return text.trim();
    const parts: string[] = [text.trim()];
    parts.push('\n\n---\n\n**用户上传的文件（已保存至服务端，可直接读取）:**\n');
    for (const a of attachments) parts.push(`\n- ${a.name}: \`${a.path}\`\n`);
    return parts.join('');
  };

  const send = useCallback(
    async (rawText: string, attachments: Attachment[]) => {
      const hasContent = rawText.trim() || attachments.length > 0;
      if (!hasContent || isTyping || !session) return;

      const textForMention = rawText.trim() || '请分析';
      const mentionedSkills = skills
        .map((s) => ({ skill: s, pos: textForMention.indexOf(`@${s.name}`) }))
        .filter(({ pos }) => pos !== -1)
        .sort((a, b) => a.pos - b.pos)
        .map(({ skill }) => skill);

      const content = buildContentWithAttachments(rawText.trim() || '请分析我上传的文件。', attachments);
      const userMsg: Message = {
        id: createMessageId('user'),
        role: 'user',
        content,
        timestamp: Date.now(),
      };
      addMessage(userMsg);

      const baseMessages = [...session.messages, userMsg];
      setIsTyping(true);
      try {
        if (mentionedSkills.length >= 2) {
          await runPipeline(baseMessages, mentionedSkills);
        } else {
          const assistantId = createMessageId('assistant');
          addMessage({
            id: assistantId,
            role: 'assistant',
            content: '',
            thinking: '正在分析请求，自动规划执行...',
            timestamp: Date.now(),
            references: [],
          });
          await runSingle(baseMessages, assistantId);
        }
      } catch (err) {
        console.error('执行失败:', err);
      } finally {
        setIsTyping(false);
      }
    },
    [isTyping, session, skills, addMessage, runPipeline, runSingle]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { isTyping, send, stop };
}
