
import React, { useState, useEffect, useRef } from 'react';
import { Reference } from '../types';

interface ReferenceAreaProps {
  references: Reference[];
  thinkingLog?: string[];
  onClose: () => void;
  isFetching?: boolean;
}

// ── 执行日志条目类型解析 ─────────────────────────────────────────────── //

type LogEntryKind =
  | 'tool_call'    // 工具调用
  | 'tool_ok'      // 工具完成
  | 'tool_error'   // 工具出错
  | 'thinking'     // 深度思考
  | 'init'         // 初始化
  | 'result'       // 执行结果统计
  | 'general';     // 其他

function classifyEntry(text: string): LogEntryKind {
  if (text.startsWith('✓ 工具完成')) return 'tool_ok';
  if (text.startsWith('✗ 工具出错')) return 'tool_error';
  if (
    text.startsWith('读取文件:') ||
    text.startsWith('执行命令:') ||
    text.startsWith('写入文件:') ||
    text.startsWith('编辑文件:') ||
    text.startsWith('批量编辑:') ||
    text.startsWith('查找文件:') ||
    text.startsWith('获取网页:') ||
    text.startsWith('搜索内容:') ||
    text.startsWith('搜索:') ||
    text.startsWith('正在调用工具:')
  ) return 'tool_call';
  if (text.startsWith('[深度思考]')) return 'thinking';
  if (text.startsWith('已加载工具:')) return 'init';
  if (text.startsWith('执行完成 |')) return 'result';
  return 'general';
}

const KIND_META: Record<LogEntryKind, { icon: string; dot: string; label: string; text: string }> = {
  tool_call:  { icon: '⚙️', dot: 'bg-gray-500',   label: 'text-gray-600',   text: 'text-gray-700' },
  tool_ok:    { icon: '✅', dot: 'bg-gray-600',   label: 'text-gray-600',   text: 'text-gray-700' },
  tool_error: { icon: '❌', dot: 'bg-gray-700',    label: 'text-gray-700',   text: 'text-gray-800' },
  thinking:   { icon: '💭', dot: 'bg-gray-500',   label: 'text-gray-600',   text: 'text-gray-700' },
  init:       { icon: '🔧', dot: 'bg-gray-400',   label: 'text-gray-500',   text: 'text-gray-600' },
  result:     { icon: '📊', dot: 'bg-gray-600',   label: 'text-gray-600',   text: 'text-gray-700' },
  general:    { icon: '💡', dot: 'bg-gray-400',   label: 'text-gray-500',   text: 'text-gray-600' },
};

// ── 引用来源颜色/图标 ─────────────────────────────────────────────────── //

function getSourceStyle(source: string) {
  switch (source) {
    case 'web':       return 'bg-gray-100 text-gray-600 border-gray-200';
    case 'knowledge': return 'bg-gray-100 text-gray-600 border-gray-200';
    case 'tool':      return 'bg-gray-100 text-gray-600 border-gray-200';
    default:          return 'bg-gray-100 text-gray-500 border-gray-200';
  }
}
function getSourceIcon(source: string) {
  switch (source) {
    case 'web':       return '🌐';
    case 'knowledge': return '📚';
    case 'tool':      return '⚙️';
    default:          return '📍';
  }
}

// ── 主组件 ────────────────────────────────────────────────────────────── //

const ReferenceArea: React.FC<ReferenceAreaProps> = ({
  references,
  thinkingLog = [],
  onClose,
  isFetching,
}) => {
  const [tab, setTab] = useState<'process' | 'refs'>('process');
  const logBottomRef = useRef<HTMLDivElement>(null);

  // 切换到"执行过程"标签并在有数据时自动选中
  useEffect(() => {
    if (thinkingLog.length > 0) setTab('process');
  }, [thinkingLog.length > 0]);

  // 执行中自动滚到底部
  useEffect(() => {
    if (isFetching) {
      logBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [thinkingLog.length, isFetching]);

  return (
    <aside className="w-96 border-l border-gray-200 flex flex-col h-full animate-in slide-in-from-right duration-500 shadow-lg z-20 bg-white">

      {/* Header */}
      <header className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-white shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="font-black text-gray-900 text-sm tracking-tight">证据链</h3>
          {isFetching && (
            <span className="flex gap-0.5 ml-1">
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce" />
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce delay-75" />
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce delay-150" />
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-gray-100 rounded-xl text-gray-500 hover:text-gray-700 transition-all"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </header>

      {/* Tab bar */}
      <div className="flex border-b border-gray-100 bg-white shrink-0">
        <button
          onClick={() => setTab('process')}
          className={`flex-1 py-2.5 text-[11px] font-black uppercase tracking-widest transition-colors ${
            tab === 'process'
              ? 'text-gray-800 border-b-2 border-gray-500'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          执行过程
          {thinkingLog.length > 0 && (
            <span className="ml-1.5 px-1.5 py-0.5 bg-gray-200 text-gray-700 rounded-full text-[9px] font-black">
              {thinkingLog.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab('refs')}
          className={`flex-1 py-2.5 text-[11px] font-black uppercase tracking-widest transition-colors ${
            tab === 'refs'
              ? 'text-gray-800 border-b-2 border-gray-500'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          引用来源
          {references.length > 0 && (
            <span className="ml-1.5 px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded-full text-[9px] font-black">
              {references.length}
            </span>
          )}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar bg-gray-50/50">

        {/* ── 执行过程 ── */}
        {tab === 'process' && (
          <div className="p-4">
            {thinkingLog.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-center px-6 space-y-4">
                <div className="w-12 h-12 bg-white rounded-2xl shadow-sm border border-gray-200 flex items-center justify-center text-2xl">⚡</div>
                <div>
                  <p className="text-sm font-bold text-gray-700">等待执行</p>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                    发送消息后，执行过程将在此实时显示
                  </p>
                </div>
              </div>
            ) : (
              <ol className="relative pl-5 border-l-2 border-gray-200 space-y-0">
                {thinkingLog.map((entry, idx) => {
                  const kind = classifyEntry(entry);
                  const meta = KIND_META[kind];
                  const isLast = idx === thinkingLog.length - 1;
                  return (
                    <li
                      key={idx}
                      className={`relative pb-4 animate-in fade-in slide-in-from-left-2 duration-200`}
                    >
                      {/* 时间线圆点 */}
                      <span
                        className={`absolute -left-[1.4rem] top-1 w-2.5 h-2.5 rounded-full border-2 border-white ${meta.dot} ${
                          isLast && isFetching ? 'animate-pulse' : ''
                        }`}
                      />

                      {/* 条目卡片 */}
                      <div className="bg-white rounded-xl border border-gray-200 px-3 py-2 shadow-sm hover:shadow-md transition-shadow">
                        <div className="flex items-start gap-2">
                          <span className="text-sm shrink-0 mt-0.5">{meta.icon}</span>
                          <p className={`text-[11px] font-medium leading-relaxed break-words ${meta.text}`}>
                            {entry}
                          </p>
                        </div>
                      </div>
                    </li>
                  );
                })}
                {/* 执行中末尾动态光标 */}
                {isFetching && (
                  <li className="relative pb-2">
                    <span className="absolute -left-[1.4rem] top-1 w-2.5 h-2.5 rounded-full border-2 border-white bg-gray-400 animate-pulse" />
                    <div className="bg-white rounded-xl border border-gray-200 px-3 py-2 shadow-sm">
                      <span className="flex gap-1 items-center">
                        <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce" />
                        <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce delay-75" />
                        <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce delay-150" />
                      </span>
                    </div>
                  </li>
                )}
                <div ref={logBottomRef} />
              </ol>
            )}
          </div>
        )}

        {/* ── 引用来源 ── */}
        {tab === 'refs' && (
          <div className="p-5 space-y-4">
            {references.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-center px-6 space-y-4">
                <div className="w-12 h-12 bg-white rounded-2xl shadow-sm border border-gray-200 flex items-center justify-center text-2xl">🔍</div>
                <div>
                  <p className="text-sm font-bold text-gray-700">暂无引用</p>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                    分析完成后，来源引用将显示在此
                  </p>
                </div>
              </div>
            ) : (
              references.map((ref, idx) => (
                <div
                  key={idx}
                  className="group bg-white border border-gray-200 p-4 rounded-2xl shadow-sm hover:shadow-md hover:border-gray-300 transition-all duration-300 animate-in fade-in slide-in-from-bottom-2"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[9px] font-black uppercase tracking-wider ${getSourceStyle(ref.source)}`}>
                      <span>{getSourceIcon(ref.source)}</span>
                      <span>{ref.source}</span>
                    </div>
                    <div className="text-[10px] text-gray-400 font-black">REF #{idx + 1}</div>
                  </div>
                  <h4 className="text-sm font-black text-gray-900 leading-tight mb-2 group-hover:text-gray-700 transition-colors">
                    {ref.title}
                  </h4>
                  {ref.snippet && (
                    <p className="text-[11px] text-gray-600 line-clamp-4 leading-relaxed bg-gray-50 p-2.5 rounded-xl border border-gray-100 italic mb-3">
                      "{ref.snippet}"
                    </p>
                  )}
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-[9px] text-gray-500 truncate font-mono flex-1">{ref.url}</div>
                    <button
                      onClick={() => window.open(ref.url, '_blank')}
                      className="shrink-0 p-1.5 bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 rounded-lg transition-all"
                      title="打开来源"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Footer（仅引用来源标签页有内容时显示） */}
      {tab === 'refs' && references.length > 0 && (
        <footer className="p-5 bg-white border-t border-gray-100 shrink-0">
          <div className="bg-gray-100 p-3.5 rounded-2xl border border-gray-200">
            <p className="text-[10px] text-gray-600 font-bold leading-relaxed">
              <span className="mr-1">🛡️</span>
              事实核查已验证。Eido交叉引用内部和外部数据以确保高保真结果。
            </p>
          </div>
        </footer>
      )}
    </aside>
  );
};

export default ReferenceArea;
