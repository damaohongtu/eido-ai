import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getWorkspaceFileUrl } from '../shared';
import type { Message } from '../shared';
import {
  extractGeneratedFiles,
  isWorkspaceFileLink,
  normalizeWorkspacePath,
} from '../utils/workspaceFiles';

interface MessageItemProps {
  message: Message;
  sessionId: string | null;
  isLast: boolean;
  isTyping: boolean;
  userName?: string;
}

const Avatar: React.FC<{ isUser: boolean; userName?: string }> = ({ isUser, userName }) => {
  if (isUser) {
    const initial = userName ? [...userName.trim()][0]?.toUpperCase() : '';
    return (
      <div className="eido-mobile-avatar mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-sm font-black text-gray-600">
        {initial || '我'}
      </div>
    );
  }
  return (
    <div className="eido-mobile-avatar mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-700 text-sm font-black text-white shadow-sm">
      E
    </div>
  );
};

const ThinkTrace: React.FC<{ message: Message }> = ({ message }) => {
  const [open, setOpen] = useState(false);
  const hasSteps = message.executionSteps && message.executionSteps.length > 0;
  const hasTrace = message.thinking || hasSteps || message.workflowMermaid;
  if (!hasTrace) return null;

  return (
    <div className="eido-mobile-think-trace mb-2 rounded-2xl border border-gray-200 bg-gray-50/80 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2"
      >
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gray-500" />
          <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
            思维链执行追踪
          </span>
        </span>
        <svg
          className={`h-3.5 w-3.5 text-gray-400 transition-transform ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>
      {open && (
        <div className="space-y-3 px-3 pb-3">
          {message.workflowMermaid && (
            <pre className="overflow-x-auto rounded-lg bg-gray-900 p-2 text-[11px] text-gray-100">
              {message.workflowMermaid}
            </pre>
          )}
          {hasSteps && (
            <div className="ml-1 space-y-2 border-l-2 border-gray-200 pl-3">
              {message.executionSteps!.map((step) => (
                <div key={step.id} className="relative">
                  <span
                    className={`absolute -left-[17px] top-1.5 h-2 w-2 rounded-full border-2 bg-white ${
                      step.status === 'completed'
                        ? 'border-gray-600 bg-gray-600'
                        : step.status === 'running'
                          ? 'animate-pulse border-gray-500 bg-gray-200'
                          : step.status === 'waiting'
                            ? 'border-amber-400 bg-amber-400'
                            : 'border-gray-300'
                    }`}
                  />
                  <div className="text-[11px] font-bold text-gray-700">@{step.label}</div>
                  <div className="text-[10px] leading-tight text-gray-500">{step.description}</div>
                </div>
              ))}
            </div>
          )}
          {message.thinking && (
            <p className="text-[11px] italic text-gray-500">"{message.thinking}"</p>
          )}
        </div>
      )}
    </div>
  );
};

const MessageItem: React.FC<MessageItemProps> = ({ message, sessionId, isLast, isTyping, userName }) => {
  const isUser = message.role === 'user';
  const generatedFiles = message.role === 'assistant' ? extractGeneratedFiles(message) : [];

  const markdownComponents = {
    img({ src, alt, ...props }: any) {
      const isExternal =
        src?.startsWith('http://') || src?.startsWith('https://') || src?.startsWith('data:');
      const imgSrc = isExternal ? src : src ? getWorkspaceFileUrl(src, { sessionId: sessionId || undefined }) : src;
      if (!imgSrc) return null;
      return (
        <a href={imgSrc} target="_blank" rel="noopener noreferrer" className="block">
          <img src={imgSrc} alt={alt || '图片'} loading="lazy" {...props} />
        </a>
      );
    },
    a({ href, children, ...props }: any) {
      if (isWorkspaceFileLink(href)) {
        const normalized = normalizeWorkspacePath(href);
        if (!normalized) return <span>{children}</span>;
        const filename = normalized.split('/').pop() || 'download';
        return (
          <a
            href={getWorkspaceFileUrl(normalized, { download: true, filename, sessionId: sessionId || undefined })}
            className="font-semibold text-blue-600 underline"
          >
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };

  return (
    <div className={`eido-mobile-message-row flex gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar isUser={isUser} userName={userName} />
      <div className={`eido-mobile-message-stack max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        {message.role === 'assistant' && <ThinkTrace message={message} />}

        <div
          className={`eido-mobile-message-bubble inline-block rounded-2xl px-3.5 py-2.5 text-[15px] shadow-sm ${
            isUser ? 'bg-gray-700 text-white' : 'border border-gray-200 bg-white text-gray-800'
          }`}
        >
          <div className={`markdown-body ${isUser ? 'on-dark' : ''}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {message.content || (isTyping && isLast ? '…' : '')}
            </ReactMarkdown>
          </div>
        </div>

        {generatedFiles.length > 0 && (
          <div className="eido-mobile-generated-files mt-2 w-full space-y-2 rounded-2xl border border-gray-200 bg-white p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-gray-500">生成文件</div>
            {generatedFiles.map((file) => (
              <div key={file.path} className="rounded-xl bg-gray-50 p-2.5">
                {file.isImage && (
                  <a
                    href={getWorkspaceFileUrl(file.path, { sessionId: sessionId || undefined })}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mb-2 block overflow-hidden rounded-lg border border-gray-200 bg-white"
                  >
                    <img
                      src={getWorkspaceFileUrl(file.path, { sessionId: sessionId || undefined })}
                      alt={file.name}
                      className="max-h-60 w-full object-contain"
                      loading="lazy"
                    />
                  </a>
                )}
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-gray-800">{file.name}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <a
                      href={getWorkspaceFileUrl(file.path, { sessionId: sessionId || undefined })}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-bold text-gray-600"
                    >
                      {file.isImage ? '查看' : '打开'}
                    </a>
                    <a
                      href={getWorkspaceFileUrl(file.path, { download: true, filename: file.name, sessionId: sessionId || undefined })}
                      className="rounded-lg bg-gray-700 px-2.5 py-1 text-xs font-bold text-white"
                    >
                      下载
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageItem;
