
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Input } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Message, ChatSession, Skill, SkillAction, ExecutionStep, Reference } from '../types';
import { api, getWorkspaceFileUrl } from '../services/api';
import Mermaid from './Mermaid';

interface ChatAreaProps {
  session: ChatSession | null;
  skills: Skill[];
  onSendMessage: (msg: Message) => void;
  onUpdateMessage: (id: string, updates: Partial<Message>) => void;
  onToggleReferences: () => void;
  rightPanelOpen: boolean;
  onExecuteAction: (action: SkillAction) => void;
  onUpdateSessionSkill?: (skillId: string) => void;
}

const ChatArea: React.FC<ChatAreaProps> = ({
  session,
  skills,
  onSendMessage,
  onUpdateMessage,
  onToggleReferences,
  rightPanelOpen,
  onExecuteAction,
  onUpdateSessionSkill
}) => {
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; path: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mentionMenu, setMentionMenu] = useState<{ visible: boolean; filter: string; index: number; pos: { top: number; left: number } }>({
    visible: false,
    filter: '',
    index: 0,
    pos: { top: 0, left: 0 }
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);
  const mentionMenuRef = useRef<HTMLDivElement>(null);
  const inputContainerRef = useRef<HTMLDivElement>(null);
  const previousSessionIdRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // 每条 assistant 消息的 thinking 事件累积日志：msgId → string[]
  const thinkingLogsRef = useRef<Record<string, string[]>>({});

  const getTextareaEl = () => {
    const ref = inputRef.current;
    // antd TextArea stores the real textarea in resizableTextArea.textArea
    return ref?.resizableTextArea?.textArea || ref || null;
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [session?.messages, isTyping]);

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
    }
  }, [session]);

  const activeSkill = useMemo(() => 
    session?.skillId ? skills.find(s => s.id === session.skillId) : null
  , [session?.skillId, skills]);

  const filteredSkills = useMemo(() => {
    return skills.filter(s => s.name.toLowerCase().includes(mentionMenu.filter.toLowerCase()));
  }, [skills, mentionMenu.filter]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    const cursorPosition = e.target.selectionStart || 0;
    const textBeforeCursor = value.slice(0, cursorPosition);
    const atMatch = textBeforeCursor.match(/@([\u4e00-\u9fa5\w\-]*)$/);

    if (atMatch) {
      const textareaEl = getTextareaEl() as HTMLTextAreaElement | null;
      const textareaRect = textareaEl?.getBoundingClientRect();

      const lines = textBeforeCursor.split('\n');
      const currentLine = lines.length - 1;
      const charInLine = lines[lines.length - 1].length;

      // Approximate caret position relative to viewport
      const caretLeft = (textareaRect?.left || 0) + 12 + charInLine * 8; // padding + char width
      const caretTop = (textareaRect?.top || 0) + 10 + currentLine * 22; // padding + line height

      setMentionMenu({ 
        visible: true, 
        filter: atMatch[1], 
        index: 0,
        pos: {
          top: caretTop,
          left: caretLeft
        }
      });
    } else {
      setMentionMenu(prev => ({ ...prev, visible: false }));
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
    const newValue = currentValue.slice(0, atPos) + `\`@${skill.name}\` ` + currentValue.slice(replaceEnd);
    setInput(newValue);
    setMentionMenu({ visible: false, filter: '', index: 0 });

    setTimeout(() => {
      textarea?.focus();
      const newPos = atPos + skill.name.length + 4; // `@name` plus trailing space
      textarea?.setSelectionRange(newPos, newPos);
    }, 0);
  };

  /** 构建单条消息的 thinking 累积回调 */
  const makeUpdater = (assistantId: string) => {
    thinkingLogsRef.current[assistantId] = [];
    return (content: string, thinking: string, steps?: any, confirmation?: any, references?: any, mermaid?: string) => {
      // 去重追加：thinking 不为空且与上一条不同时才记录
      if (thinking) {
        const log = thinkingLogsRef.current[assistantId];
        if (log[log.length - 1] !== thinking) {
          log.push(thinking);
        }
      }
      onUpdateMessage(assistantId, {
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
    msgs: Message[],
    assistantId: string,
    context?: string,
    skillHint?: string
  ) => {
    abortControllerRef.current = new AbortController();
    await api.streamChat(msgs, makeUpdater(assistantId), context, skillHint ?? undefined, abortControllerRef.current.signal);
  };

  /** 用户点击停止，中断当前执行 */
  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  /** 多技能串行流水线：每个技能独立生成一条 assistant 消息，前一步输出传给下一步 */
  const runPipeline = async (baseMessages: Message[], orderedSkills: typeof skills) => {
    let previousOutput = '';
    let contextMessages = [...baseMessages];
    abortControllerRef.current = new AbortController();

    for (let i = 0; i < orderedSkills.length; i++) {
      const skill = orderedSkills[i];
      const assistantId = `pipeline-${Date.now()}-${i}`;

      const placeholder: Message = {
        id: assistantId,
        role: 'assistant',
        content: '',
        thinking: `正在启动步骤 ${i + 1}/${orderedSkills.length}：${skill.name}...`,
        timestamp: Date.now(),
        references: []
      };
      onSendMessage(placeholder);

      let finalContent = '';
      const updater = makeUpdater(assistantId);
      try {
        await api.streamChat(
          contextMessages,
          (content, thinking, steps, confirmation, references, mermaid) => {
            finalContent = content;
            updater(content, thinking, steps, confirmation, references, mermaid);
          },
          previousOutput || undefined,
          skill.id,
          abortControllerRef.current?.signal
        );
      } catch {
        break;
      }
      previousOutput = finalContent;
      contextMessages = [...contextMessages, { ...placeholder, content: finalContent }];
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    const allowed = ['.md', '.pdf', '.csv', '.xls', '.xlsx'];
    setUploading(true);
    try {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        const ext = f.name.toLowerCase().slice(f.name.lastIndexOf('.'));
        if (!allowed.includes(ext)) {
          console.warn(`跳过不支持格式: ${f.name}`);
          continue;
        }
        const { path } = await api.uploadChatFile(f);
        setAttachments(prev => [...prev, { name: f.name, path }]);
      }
    } catch (err) {
      console.error('上传失败:', err);
    } finally {
      setUploading(false);
    }
    e.target.value = '';
  };

  const removeAttachment = (idx: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== idx));
  };

  const buildContentWithAttachments = (text: string): string => {
    if (attachments.length === 0) return text.trim();
    const parts: string[] = [text.trim()];
    parts.push('\n\n---\n\n**用户上传的文件（已保存至服务端，可直接读取）:**\n');
    for (const a of attachments) {
      parts.push(`\n- ${a.name}: \`${a.path}\`\n`);
    }
    return parts.join('');
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const hasContent = input.trim() || attachments.length > 0;
    if (!hasContent || isTyping) return;

    // 按在文本中出现的位置顺序，找出所有被 @ 提及的技能
    const textForMention = input.trim() || '请分析';
    const mentionedSkills = skills
      .map(s => ({ skill: s, pos: textForMention.indexOf(`@${s.name}`) }))
      .filter(({ pos }) => pos !== -1)
      .sort((a, b) => a.pos - b.pos)
      .map(({ skill }) => skill);

    const content = buildContentWithAttachments(input.trim() || '请分析我上传的文件。');

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: Date.now()
    };

    setInput('');
    setAttachments([]);
    onSendMessage(userMsg);

    const baseMessages = [...(session?.messages || []), userMsg];
    setIsTyping(true);

    try {
      if (mentionedSkills.length >= 2) {
        // 多技能流水线
        await runPipeline(baseMessages, mentionedSkills);
      } else {
        // 单次执行（有或无 @mention 均交由后端自动规划）
        const assistantId = (Date.now() + 1).toString();
        onSendMessage({
          id: assistantId,
          role: 'assistant',
          content: '',
          thinking: '正在分析请求，自动规划执行...',
          timestamp: Date.now(),
          references: []
        });
        await runSingleSkill(baseMessages, assistantId);
      }
    } catch (err) {
      console.error('执行失败:', err);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mentionMenu.visible) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionMenu(prev => ({ ...prev, index: (prev.index + 1) % (filteredSkills.length || 1) }));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionMenu(prev => ({ ...prev, index: (prev.index - 1 + (filteredSkills.length || 1)) % (filteredSkills.length || 1) }));
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (filteredSkills.length > 0) {
          e.preventDefault();
          insertMention(filteredSkills[mentionMenu.index]);
        }
      } else if (e.key === 'Escape') {
        setMentionMenu(prev => ({ ...prev, visible: false }));
      }
    } else if (e.key === 'Enter' && !e.shiftKey) {
      // Enter 发送，Shift+Enter 换行
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleConfirmation = async (approved: boolean, messageId: string) => {
    if (approved) {
      const msg = session?.messages.find(m => m.id === messageId);
      if (msg) {
        const updatedSteps = msg.executionSteps?.map(s => 
          s.status === 'waiting' ? { ...s, status: 'completed' as const, description: 'Access granted by user.' } : s
        );
        onUpdateMessage(messageId, { 
          pendingConfirmation: undefined,
          executionSteps: updatedSteps,
          thinking: "Access granted. Re-engaging evidence collection protocols..." 
        });
        
        const updatedMessages = session?.messages.map(m => 
          m.id === messageId ? { ...m, pendingConfirmation: undefined, executionSteps: updatedSteps } : m
        ) || [];
        
        setIsTyping(true);
        try {
          await runSingleSkill(updatedMessages, messageId);
        } finally {
          setIsTyping(false);
        }
      }
    } else {
      onUpdateMessage(messageId, { 
        pendingConfirmation: undefined,
        thinking: "Workflow halted. Data access denied by user." 
      });
      setIsTyping(false);
    }
  };

  const MermaidCollapsible: React.FC<{ chart: string }> = ({ chart }) => {
    const [expanded, setExpanded] = useState(true);
    return (
      <div>
        <button
          onClick={() => setExpanded(prev => !prev)}
          className="flex items-center space-x-1.5 text-[10px] font-black uppercase tracking-widest text-gray-500 hover:text-gray-700 transition-colors"
        >
          <svg
            className={`w-3 h-3 transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
          </svg>
          <span>工作流拓扑</span>
        </button>
        {expanded && (
          <div className="mt-2 animate-in fade-in slide-in-from-top-1">
            <Mermaid chart={chart} />
          </div>
        )}
      </div>
    );
  };

  const MarkdownComponents = {
    code({ node, inline, className, children, ...props }: any) {
      const match = /@/.test(String(children));
      if (inline && match) {
        const skillName = String(children).replace('@', '');
        const skill = skills.find(s => s.name === skillName);
        return (
          <span className="inline-flex items-center bg-gray-100 border border-gray-200 px-2 py-0.5 rounded-md text-gray-700 font-bold text-xs mx-0.5 shadow-sm">
            {skill && <span className="mr-1.5">{skill.icon}</span>}
            {children}
          </span>
        );
      }
      return <code className={className} {...props}>{children}</code>;
    },
    img({ node, src, alt, ...props }: any) {
      // 外部 URL 和 data URL 直接使用；本地/工作区路径通过 API 代理预览
      const isExternal = src?.startsWith('http://') || src?.startsWith('https://') || src?.startsWith('data:');
      const imgSrc = isExternal ? src : (src ? getWorkspaceFileUrl(src) : src);
      if (!imgSrc) return null;
      return (
        <span className="block my-3">
          <a href={imgSrc} target="_blank" rel="noopener noreferrer" className="inline-block">
            <img
              src={imgSrc}
              alt={alt || '图片'}
              className="max-w-full max-h-80 rounded-lg border border-gray-200 shadow-sm hover:shadow-md transition-shadow cursor-zoom-in object-contain"
              loading="lazy"
              {...props}
            />
          </a>
        </span>
      );
    }
  };

  if (!session) return (
    <div className="flex-1 flex items-center justify-center text-gray-500 font-medium bg-white">
      选择一个会话以激活 Eido 会话
    </div>
  );

  return (
    <div className="flex-1 flex flex-col h-full relative">
      <header className="h-16 border-b border-gray-200 flex items-center justify-between px-6 bg-white/80 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center space-x-3">
          <h2 className="font-bold text-lg text-gray-800">{session.title}</h2>
        </div>
        <button onClick={onToggleReferences} className={`p-2 rounded-lg transition-colors ${rightPanelOpen ? 'text-gray-700 bg-gray-200' : 'text-gray-500 hover:bg-gray-100'}`}>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
        {session.messages.map((m, idx) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] space-y-3 ${m.role === 'user' ? 'text-right' : ''}`}>
              
              {m.role === 'assistant' && (m.thinking || (m.executionSteps && m.executionSteps.length > 0) || m.workflowMermaid) && (
                <div className="bg-gray-100/80 rounded-2xl border border-gray-200 overflow-hidden shadow-sm">
                  <div className="px-4 py-3 bg-white/50 border-b border-gray-200 flex items-center justify-between">
                     <div className="flex items-center space-x-2">
                        <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-pulse"></span>
                        <span className="text-[10px] font-black uppercase tracking-widest text-gray-600">思维链执行追踪</span>
                     </div>
                  </div>
                  <div className="p-4 space-y-4">
                    {m.workflowMermaid && (
                      <MermaidCollapsible chart={m.workflowMermaid} />
                    )}
                    {m.executionSteps && m.executionSteps.length > 0 && (
                      <div className="space-y-3 border-l-2 border-gray-200 ml-2 pl-4 py-1">
                        {m.executionSteps.map((step) => (
                          <div key={step.id} className="relative">
                            <div className={`absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full border-2 bg-white transition-colors duration-500 ${
                              step.status === 'completed' ? 'bg-gray-600 border-gray-600' :
                              step.status === 'running' ? 'border-gray-500 animate-pulse bg-gray-200' :
                              step.status === 'waiting' ? 'bg-amber-400 border-amber-400' : 'border-gray-300'
                            }`} />
                            <div className="flex flex-col">
                              <div className="flex items-center space-x-2">
                                <span className={`text-[11px] font-bold ${
                                  step.status === 'running' ? 'text-gray-700' : 'text-gray-700'
                                }`}>@{step.label}</span>
                                {step.status === 'running' && <span className="text-[9px] bg-gray-200 text-gray-600 px-1.5 rounded uppercase font-black">活动</span>}
                                {step.status === 'waiting' && <span className="text-[9px] bg-amber-50 text-amber-600 px-1.5 rounded uppercase font-black animate-bounce">访问受限</span>}
                              </div>
                              <span className="text-[10px] text-gray-500 font-medium leading-tight">{step.description}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    <p className="text-xs text-gray-500 italic font-medium">"{m.thinking}"</p>
                  </div>
                </div>
              )}

              <div className={`inline-block px-5 py-4 rounded-2xl text-[15px] text-left shadow-sm ${
                m.role === 'user' ? 'bg-gray-700 text-white' : 'bg-white border border-gray-200 text-gray-800'
              }`}>
                <div className={`markdown-body ${m.role === 'user' ? 'text-white' : ''}`}>
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={MarkdownComponents}
                  >
                    {m.content || (isTyping && idx === session.messages.length - 1 ? "..." : "")}
                  </ReactMarkdown>
                </div>
              </div>

              {m.role === 'assistant' && activeSkill && !isTyping && idx === session.messages.length - 1 && activeSkill.actions && activeSkill.actions.length > 0 && m.content && (
                <div className="flex flex-wrap gap-2 mt-4 animate-in fade-in slide-in-from-top-2">
                  <div className="w-full text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1 ml-1">工作流部署:</div>
                  {activeSkill.actions.map(action => (
                    <button 
                      key={action.id}
                      onClick={() => onExecuteAction(action)}
                      className="flex items-center space-x-2 px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-xs font-bold text-gray-700 hover:border-gray-400 hover:bg-gray-50 transition-all group"
                    >
                      <span className="text-lg group-hover:scale-110 transition-transform">{action.icon}</span>
                      <span>{action.label}</span>
                    </button>
                  ))}
                </div>
              )}

              {m.pendingConfirmation && (
                <div className="p-5 bg-white border-2 border-amber-100 rounded-[2rem] shadow-xl animate-in slide-in-from-bottom-4">
                  <div className="flex items-start space-x-4 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center text-xl shrink-0">🛡️</div>
                    <div>
                      <h4 className="font-bold text-gray-900 leading-tight">安全接口访问</h4>
                      <p className="text-xs text-gray-500 mt-1">初始化 <b>@{m.pendingConfirmation.label}</b>?</p>
                    </div>
                  </div>
                  <p className="text-[12px] text-gray-600 mb-5 bg-gray-50 p-3 rounded-xl border border-gray-100 italic">
                    {m.pendingConfirmation.description}
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => handleConfirmation(true, m.id)} className="flex-1 py-2.5 bg-gray-700 text-white rounded-xl text-xs font-bold hover:bg-gray-800 transition-all">授予访问权限</button>
                    <button onClick={() => handleConfirmation(false, m.id)} className="px-4 py-2.5 bg-white border border-gray-200 text-gray-500 rounded-xl text-xs font-bold">拒绝请求</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="p-6 border-t border-gray-200 bg-white relative">
        {mentionMenu.visible && filteredSkills.length > 0 && (
          <div 
            ref={mentionMenuRef}
            className="fixed w-64 max-h-64 bg-white border border-gray-200 rounded-2xl shadow-2xl overflow-y-auto animate-in fade-in zoom-in-95 custom-scrollbar"
            style={{ top: `${mentionMenu.pos.top}px`, left: `${mentionMenu.pos.left}px`, transform: 'translateY(-110%)' }}
          >
             <div className="sticky top-0 z-10 px-3 py-2 bg-gray-50 border-b border-gray-100 text-[9px] font-black text-gray-500 uppercase tracking-widest">激活智能技能</div>
             {filteredSkills.map((s, i) => (
               <button 
                 key={s.id} 
                 onClick={() => insertMention(s)}
                 className={`w-full flex items-center space-x-3 px-4 py-3 text-left transition-all ${mentionMenu.index === i ? 'bg-gray-200 text-gray-900' : 'hover:bg-gray-50 text-gray-700'}`}
               >
                 <span className="text-xl">{s.icon}</span>
                 <span className="text-sm font-bold">{s.name}</span>
               </button>
             ))}
          </div>
        )}
        <form onSubmit={handleSubmit} className="relative max-w-4xl mx-auto">
          <input
            ref={fileInputRef}
            type="file"
            accept=".md,.pdf,.csv,.xls,.xlsx"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {attachments.map((a, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 border border-gray-200 rounded-lg text-xs font-medium text-gray-700"
                >
                  <span className="truncate max-w-[120px]">{a.name}</span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(i)}
                    className="text-gray-400 hover:text-red-500"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="relative" ref={inputContainerRef}>
            <Input.TextArea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask me anything... 支持上传 .md / .pdf / .csv / .xls / .xlsx 文件"
              autoSize={{ minRows: 4, maxRows: 8 }}
              disabled={isTyping}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isTyping || uploading}
              className="absolute left-4 bottom-4 p-2 rounded-xl text-gray-500 hover:bg-gray-100 transition-all disabled:opacity-50"
              title="上传文件 (.md / .pdf / .csv / .xls / .xlsx)"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </button>
            {isTyping ? (
              <button
                type="button"
                onClick={handleStop}
                className="absolute right-4 bottom-4 p-2 rounded-xl bg-red-100 text-red-600 hover:bg-red-200 transition-all"
                title="停止生成"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1" /></svg>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() && attachments.length === 0}
                className={`absolute right-4 bottom-4 p-2 rounded-xl transition-all ${(input.trim() || attachments.length > 0) ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500'}`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
};

export default ChatArea;
