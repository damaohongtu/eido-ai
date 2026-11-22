import React, { useState } from 'react';
import { Input } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getWorkspaceFileUrl } from '../services/api';
import {
  canPreviewInBrowser,
  canRenderAsBrowserImage,
  isSupportedProjectMaterial,
} from '../utils/projectFiles';
import {
  SUPPORTED_FILE_ACCEPT,
  SUPPORTED_FILE_HINT,
} from '../utils/supportedFiles';
import Mermaid from './Mermaid';
import ModelSelector from './ModelSelector';
import RuntimeModeSelector from './RuntimeModeSelector';

import { extractGeneratedFiles, isWorkspaceFileLink, normalizeWorkspacePath } from '../utils/chatFiles';
import { useChatController, type ChatAreaProps } from '../hooks/useChatController';

const ChatArea: React.FC<ChatAreaProps> = ({
  session,
  skills,
  onSendMessage,
  onUpdateMessage,
  onToggleReferences,
  rightPanelOpen,
  onExecuteAction,
  onUpdateSessionSkill,
  project,
  projects,
  onMoveSession,
  onOpenProject,
  onImportProjectFile,
  onRefreshSession,
  onRunningSessionsChange,
  model,
  onModelChange,
  runtimeMode,
  onRuntimeModeChange,
}) => {
  const {
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
    editQueuedMessage
  } = useChatController({
    session,
    skills,
    onSendMessage,
    onUpdateMessage,
    onToggleReferences,
    rightPanelOpen,
    onExecuteAction,
    onUpdateSessionSkill,
    project,
    projects,
    onMoveSession,
    onOpenProject,
    onImportProjectFile,
    onRefreshSession,
    onRunningSessionsChange,
    model,
    onModelChange,
    runtimeMode,
    onRuntimeModeChange
  });

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
      if (!isExternal && src && !canRenderAsBrowserImage(src)) {
        const filename = src.split('/').pop() || 'download';
        const canPreview = canPreviewInBrowser(src);
        return (
          <a
            href={getWorkspaceFileUrl(src, {
              download: !canPreview,
              preview: canPreview,
              filename,
              sessionId: session?.id,
            })}
            target={canPreview ? '_blank' : undefined}
            rel="noopener noreferrer"
          >
            {canPreview ? '预览文件' : '下载文件'}：{alt || filename}
          </a>
        );
      }
      const imgSrc = isExternal ? src : (src ? getWorkspaceFileUrl(src, { preview: true, sessionId: session?.id }) : src);
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
    },
    a({ node, href, children, ...props }: any) {
      if (isWorkspaceFileLink(href)) {
        const normalizedPath = normalizeWorkspacePath(href);
        if (!normalizedPath) return <span>{children}</span>;
        const filename = normalizedPath.split('/').pop() || 'download';
        const canPreview = canPreviewInBrowser(normalizedPath);
        return (
          <span className="inline-flex items-center gap-2 my-1 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
            <a
              href={getWorkspaceFileUrl(normalizedPath, {
                download: !canPreview,
                preview: canPreview,
                filename,
                sessionId: session?.id,
              })}
              target={canPreview ? '_blank' : undefined}
              rel="noopener noreferrer"
              className="font-semibold text-gray-700 hover:text-gray-900 hover:underline"
            >
              {children}
            </a>
            <a
              href={getWorkspaceFileUrl(normalizedPath, { download: true, filename, sessionId: session?.id })}
              className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-xs font-bold text-gray-600 hover:border-gray-400 hover:text-gray-900"
            >
              下载
            </a>
          </span>
        );
      }

      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 underline underline-offset-2 hover:text-blue-700"
          {...props}
        >
          {children}
        </a>
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
      <header className="min-h-16 border-b border-gray-200 flex items-center justify-between gap-4 px-6 py-2 bg-white/80 backdrop-blur-md sticky top-0 z-10">
        <div className="min-w-0">
          {project ? (
            <button
              type="button"
              onClick={() => onOpenProject(project.id)}
              className="mb-0.5 block max-w-full truncate text-[10px] font-black uppercase tracking-widest text-gray-400 hover:text-gray-700"
              title={`打开项目 ${project.name}`}
            >
              📁 {project.name} / 会话
            </button>
          ) : (
            <div className="mb-0.5 text-[10px] font-black uppercase tracking-widest text-gray-400">对话</div>
          )}
          <h2 className="truncate font-bold text-lg text-gray-800">{session.title}</h2>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button onClick={onToggleReferences} className={`p-2 rounded-lg transition-colors ${rightPanelOpen ? 'text-gray-700 bg-gray-200' : 'text-gray-500 hover:bg-gray-100'}`}>
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
          </button>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
        {conversationMessages.map((m, idx) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] min-w-0 space-y-3 [overflow-wrap:anywhere] ${m.role === 'user' ? 'text-right' : ''}`}>
              {(() => {
                const generatedFiles = m.role === 'assistant' ? extractGeneratedFiles(m) : [];
                return (
                  <>
              
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
                    {m.content || (activeSessionRunning && idx === conversationMessages.length - 1 ? "..." : "")}
                  </ReactMarkdown>
                </div>
              </div>
              {m.role === 'user' && m.deliveryMode && (
                <div className="flex justify-end">
                  <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${
                    m.deliveryStatus === 'failed'
                      ? 'bg-red-50 text-red-600'
                      : m.deliveryMode === 'steer'
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-gray-100 text-gray-500'
                  }`}>
                    {m.deliveryStatus === 'failed'
                      ? '提交失败'
                      : m.deliveryMode === 'steer'
                        ? 'Steer · 已应用'
                        : m.deliveryStatus === 'completed'
                          ? '排队任务 · 已完成'
                          : m.deliveryStatus === 'running'
                            ? '排队任务 · 执行中'
                            : `排队中${m.queuePosition ? ` · 第 ${m.queuePosition} 位` : ''}`}
                  </span>
                </div>
              )}

              {m.role === 'assistant' && generatedFiles.length > 0 && (
                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-gray-500">生成文件</div>
                  <div className="space-y-2">
                    {generatedFiles.map(file => (
                      <div key={file.path} className="rounded-xl bg-gray-50 px-3 py-3">
                        {file.isImage && canRenderAsBrowserImage(file.path) && (
                          <a
                            href={getWorkspaceFileUrl(file.path, { preview: true, sessionId: session?.id })}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mb-3 block overflow-hidden rounded-xl border border-gray-200 bg-white"
                          >
                            <img
                              src={getWorkspaceFileUrl(file.path, { preview: true, sessionId: session?.id })}
                              alt={file.name}
                              className="max-h-72 w-full object-contain"
                              loading="lazy"
                            />
                          </a>
                        )}
                        <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-gray-800">{file.name}</div>
                          <div className="truncate text-xs text-gray-500">{file.path}</div>
                        </div>
                        <div className="flex items-center gap-2">
                          {onImportProjectFile && isSupportedProjectMaterial(file.path, file.name, session.id) && (
                            <button
                              type="button"
                              onClick={() => importGeneratedFile(file)}
                              disabled={activeSessionRunning || Boolean(projectImportStatus[file.path])}
                              className="rounded-lg border border-gray-700 bg-white px-3 py-1.5 text-xs font-bold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:border-gray-300 disabled:text-gray-400"
                              title={activeSessionRunning ? '会话执行完成后可加入项目资料' : `加入「${project?.name || ''}」项目资料`}
                            >
                              {projectImportStatus[file.path] === 'adding'
                                ? '加入中...'
                                : projectImportStatus[file.path] === 'added'
                                  ? '已加入项目'
                                  : '加入项目资料'}
                            </button>
                          )}
                          {canPreviewInBrowser(file.path) && (
                            <a
                              href={getWorkspaceFileUrl(file.path, { preview: true, sessionId: session?.id })}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-bold text-gray-600 hover:border-gray-400 hover:text-gray-900"
                            >
                              预览
                            </a>
                          )}
                          <a
                            href={getWorkspaceFileUrl(file.path, { download: true, filename: file.name, sessionId: session?.id })}
                            className="rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-gray-800"
                          >
                            下载
                          </a>
                        </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {m.role === 'assistant' && activeSkill && !activeSessionRunning && idx === conversationMessages.length - 1 && activeSkill.actions && activeSkill.actions.length > 0 && m.content && (
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
                  </>
                );
              })()}
            </div>
          </div>
        ))}
      </div>

      <div className="p-6 border-t border-gray-200 bg-white relative">
        {mentionMenu.visible && filteredSkills.length > 0 && (
          <div
            ref={mentionMenuRef}
            className="fixed z-50 w-64 max-h-64 bg-white border border-gray-200 rounded-2xl shadow-2xl overflow-y-auto animate-in fade-in zoom-in-95 custom-scrollbar"
            style={{ top: `${mentionMenu.pos.top}px`, left: `${mentionMenu.pos.left}px`, transform: 'translateY(-100%)' }}
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
            accept={SUPPORTED_FILE_ACCEPT}
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
          {queuedMessages.length > 0 && (
            <div className="mb-2 max-h-48 space-y-1 overflow-y-auto rounded-2xl border border-gray-200 bg-gray-50 p-2 shadow-sm">
              <div className="flex items-center justify-between px-2 py-1 text-[10px] font-black uppercase tracking-widest text-gray-400">
                <span>已排队 · {queuedMessages.length}</span>
                <span className="normal-case tracking-normal">当前任务完成后依次执行</span>
              </div>
              {queuedMessages.map((message, index) => (
                <div
                  key={message.id}
                  className="group flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-left ring-1 ring-gray-200"
                >
                  <span className="shrink-0 text-[10px] font-bold text-gray-400">{index + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-gray-700">
                    {message.content}
                  </span>
                  <button
                    type="button"
                    disabled={!steerAvailable}
                    onClick={() => void submitFollowUp(message.content, 'steer', message)}
                    className="shrink-0 rounded-lg px-2 py-1 text-[11px] font-bold text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                    title={steerAvailable ? '不打断当前任务，立即注入这条指令' : '正在连接 Claude Code，暂不可 Steer'}
                  >
                    Steer
                  </button>
                  <button
                    type="button"
                    onClick={() => void editQueuedMessage(message)}
                    className="shrink-0 rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                    title="编辑排队消息"
                    aria-label="编辑排队消息"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7m-1.5-9.5a2.121 2.121 0 013 3L12 16l-4 1 1-4 9.5-9.5z" /></svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => void deleteQueuedMessage(message)}
                    className="shrink-0 rounded-lg p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                    title="删除排队消息"
                    aria-label="删除排队消息"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                  </button>
                </div>
              ))}
            </div>
          )}
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
              placeholder={`Ask me anything... 支持上传${SUPPORTED_FILE_HINT}`}
              autoSize={{ minRows: 4, maxRows: 8 }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="absolute left-4 bottom-4 p-2 rounded-xl text-gray-500 hover:bg-gray-100 transition-all disabled:opacity-50"
              title={`上传${SUPPORTED_FILE_HINT}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </button>
            {activeSessionRunning && (
              <div className="absolute bottom-4 right-14 z-20">
                <button
                  type="button"
                  onClick={() => setDeliveryMenuOpen(open => !open)}
                  className="flex h-9 items-center gap-1 rounded-xl border border-gray-200 bg-white px-2.5 text-[11px] font-bold text-gray-600 shadow-sm hover:bg-gray-50"
                  title="选择追问发送方式"
                  aria-expanded={deliveryMenuOpen}
                >
                  <span>{effectiveDeliveryMode === 'queue' ? '排队' : 'Steer'}</span>
                  <svg className={`h-3 w-3 transition-transform ${deliveryMenuOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
                </button>
                {deliveryMenuOpen && (
                  <div className="absolute bottom-11 right-0 w-64 overflow-hidden rounded-xl border border-gray-200 bg-white p-1.5 text-left shadow-xl">
                    <button
                      type="button"
                      onClick={() => { setDeliveryMode('queue'); setDeliveryMenuOpen(false); }}
                      className={`w-full rounded-lg px-3 py-2 text-left ${deliveryMode === 'queue' ? 'bg-gray-100' : 'hover:bg-gray-50'}`}
                    >
                      <div className="text-xs font-bold text-gray-800">加入队列</div>
                      <div className="mt-0.5 text-[11px] text-gray-500">当前任务完成后按顺序执行</div>
                    </button>
                    <button
                      type="button"
                      disabled={!steerAvailable}
                      onClick={() => { setDeliveryMode('steer'); setDeliveryMenuOpen(false); }}
                      className={`mt-1 w-full rounded-lg px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-40 ${deliveryMode === 'steer' ? 'bg-gray-100' : 'hover:bg-gray-50'}`}
                    >
                      <div className="text-xs font-bold text-gray-800">Steer 当前任务</div>
                      <div className="mt-0.5 text-[11px] text-gray-500">不打断模型，立即补充或调整方向</div>
                    </button>
                  </div>
                )}
              </div>
            )}
            {activeSessionCanStop && !input.trim() && attachments.length === 0 ? (
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
                title={activeSessionRunning ? (effectiveDeliveryMode === 'steer' ? 'Steer 当前任务' : '加入队列') : '发送'}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
              </button>
            )}
          </div>
          {activeSessionRunning && (
            <div className="mt-2 px-1 text-[11px] font-medium text-gray-400">
              Enter {effectiveDeliveryMode === 'queue' ? '加入队列' : 'Steer 当前任务'} · Shift + Enter 换行
            </div>
          )}
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2 px-1">
            <ModelSelector
              value={model}
              onChange={onModelChange}
              disabled={activeSessionRunning}
            />
            <RuntimeModeSelector
              value={runtimeMode}
              onChange={onRuntimeModeChange}
              disabled={activeSessionRunning}
            />
            <label className="flex min-w-0 items-center gap-2 text-xs font-semibold text-gray-500">
              <span className="shrink-0">项目归属</span>
              <select
                value={project?.id || ''}
                disabled={activeSessionRunning}
                onChange={(event) => onMoveSession(event.target.value || null).catch(() => undefined)}
                className="min-w-0 max-w-56 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-semibold text-gray-700 outline-none hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                title={activeSessionRunning ? '执行中不能移动会话' : '移动会话到项目'}
              >
                <option value="">未归属</option>
                {projects.filter(item => !item.archived_at || item.id === project?.id).map(item => (
                  <option key={item.id} value={item.id} disabled={Boolean(item.archived_at)}>
                    {item.name}{item.archived_at ? '（已归档）' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ChatArea;
