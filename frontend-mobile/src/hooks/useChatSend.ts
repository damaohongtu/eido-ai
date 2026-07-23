import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatSession, Message, Skill } from '../shared';
import { eidoCloudRuntime } from '../runtime/eidoCloudRuntime';
import type { AgentRuntime } from '../runtime/types';

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
  addMessage: (sessionId: string, msg: Message) => void;
  updateMessage: (sessionId: string, id: string, updates: Partial<Message>) => void;
  browserContext?: string;
  agentRuntime?: AgentRuntime;
}

/**
 * 聊天发送：与 PC 端 ChatArea 行为一致。
 * - 单 @技能 / 无技能：交由后端自动规划，单次流式执行
 * - 多 @技能：串行流水线，前一步输出作为下一步 context
 */
export function useChatSend({
  session,
  skills,
  harness,
  addMessage,
  updateMessage,
  browserContext,
  agentRuntime = eidoCloudRuntime,
}: UseChatSendArgs) {
  const [isTyping, setIsTyping] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingLogsRef = useRef<Record<string, string[]>>({});

  useEffect(() => () => {
    abortRef.current?.abort();
  }, []);

  const makeUpdater = useCallback(
    (sessionId: string, assistantId: string) => {
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
        updateMessage(sessionId, assistantId, {
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
    async (sessionId: string, msgs: Message[], assistantId: string, localAgentHint?: string) => {
      abortRef.current = new AbortController();
      try {
        await agentRuntime.streamChat(
          msgs,
          makeUpdater(sessionId, assistantId),
          sessionId,
          assistantId,
          browserContext || undefined,
          agentRuntime.isLocal ? localAgentHint : undefined,
          abortRef.current.signal,
          harness
        );
      } finally {
        delete thinkingLogsRef.current[assistantId];
      }
    },
    [harness, makeUpdater, browserContext, agentRuntime]
  );

  const runPipeline = useCallback(
    async (sessionId: string, baseMessages: Message[], orderedSkills: Skill[]) => {
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
        addMessage(sessionId, placeholder);

        let finalContent = '';
        const updater = makeUpdater(sessionId, assistantId);
        try {
          await agentRuntime.streamChat(
            contextMessages,
            (content, thinking, steps, confirmation, references, mermaid) => {
              finalContent = content;
              updater(content, thinking, steps, confirmation, references, mermaid);
            },
            sessionId,
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
    [harness, addMessage, makeUpdater, browserContext, agentRuntime]
  );

  const buildContentWithAttachments = (text: string, attachments: Attachment[]): string => {
    if (attachments.length === 0) return text.trim();
    const parts: string[] = [text.trim()];
    if (agentRuntime.isLocal) {
      parts.push('\n\n---\n\n**用户随当前请求发送的本机附件:**\n');
      for (const attachment of attachments) parts.push(`\n- ${attachment.name}\n`);
    } else {
      parts.push('\n\n---\n\n**用户上传的文件（已保存至服务端，可直接读取）:**\n');
      for (const attachment of attachments) parts.push(`\n- ${attachment.name}: \`${attachment.path}\`\n`);
    }
    return parts.join('');
  };

  const send = useCallback(
    async (rawText: string, attachments: Attachment[]) => {
      const hasContent = rawText.trim() || attachments.length > 0;
      if (!hasContent || isTyping || !session) return;
      // 固定本轮的目标会话；抽屉切换不会改变异步流式结果的归属。
      const targetSessionId = session.id;

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
      addMessage(targetSessionId, userMsg);

      const baseMessages = [...session.messages, userMsg];
      setIsTyping(true);
      try {
        if (mentionedSkills.length >= 2) {
          await runPipeline(targetSessionId, baseMessages, mentionedSkills);
        } else {
          const assistantId = createMessageId('assistant');
          addMessage(targetSessionId, {
            id: assistantId,
            role: 'assistant',
            content: '',
            thinking: '正在分析请求，自动规划执行...',
            timestamp: Date.now(),
            references: [],
          });
          await runSingle(targetSessionId, baseMessages, assistantId, mentionedSkills[0]?.id || session.skillId);
        }
      } catch (err) {
        console.error('执行失败:', err);
      } finally {
        setIsTyping(false);
      }
    },
    [isTyping, session, skills, addMessage, runPipeline, runSingle, agentRuntime]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const respondToConfirmation = useCallback(
    async (messageId: string, approved: boolean) => {
      if (!session || !agentRuntime.respondToConfirmation) return;
      const message = session.messages.find((item) => item.id === messageId);
      const confirmation = message?.pendingConfirmation;
      if (!confirmation) return;
      await agentRuntime.respondToConfirmation(session.id, confirmation.toolId, approved);
      updateMessage(session.id, messageId, {
        pendingConfirmation: undefined,
        thinking: approved ? '已允许本次操作，继续执行...' : '已拒绝本次操作，等待 Agent 调整方案...',
      });
    },
    [agentRuntime, session, updateMessage]
  );

  return { isTyping, send, stop, respondToConfirmation };
}
