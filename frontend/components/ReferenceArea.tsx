
import React, { useState, useEffect, useRef } from 'react';
import { Project, ProjectFile, Reference } from '../types';
import { api, getProjectFileUrl, getWorkspaceFileUrl, WorkspaceFileNode } from '../services/api';
import { isSupportedProjectMaterial, shouldForceWorkspaceDownload } from '../utils/projectFiles';

interface ReferenceAreaProps {
  references: Reference[];
  thinkingLog?: string[];
  sessionId?: string;
  project?: Project | null;
  projectFiles?: ProjectFile[];
  projectFilesLoading?: boolean;
  onOpenProject?: () => void;
  onRefreshProjectFiles?: () => void;
  onImportProjectFile?: (path: string, displayName: string) => Promise<void>;
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
  sessionId,
  project,
  projectFiles = [],
  projectFilesLoading,
  onOpenProject,
  onRefreshProjectFiles,
  onImportProjectFile,
  onClose,
  isFetching,
}) => {
  const [tab, setTab] = useState<'process' | 'refs' | 'files' | 'project'>('process');
  const logBottomRef = useRef<HTMLDivElement>(null);
  const [fileTree, setFileTree] = useState<WorkspaceFileNode[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());

  const loadFileTree = () => {
    if (!sessionId) return;
    setFilesLoading(true);
    api.listWorkspaceFiles(sessionId).then(setFileTree).catch(() => setFileTree([])).finally(() => setFilesLoading(false));
  };

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

  // 切换到文件标签时加载文件树
  useEffect(() => {
    if (tab === 'files' && sessionId) {
      loadFileTree();
    }
  }, [tab, sessionId]);

  useEffect(() => {
    if (tab === 'project' && project) onRefreshProjectFiles?.();
    if (tab === 'project' && !project) setTab('process');
    // callback identity is intentionally ignored; project id is the fetch boundary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, project?.id]);

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
          onClick={() => setTab('files')}
          className={`flex-1 py-2.5 text-[11px] font-black uppercase tracking-widest transition-colors ${
            tab === 'files'
              ? 'text-gray-800 border-b-2 border-gray-500'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          会话文件
        </button>
        {project ? (
          <button
            onClick={() => setTab('project')}
            className={`flex-1 py-2.5 text-[11px] font-black uppercase tracking-widest transition-colors ${
              tab === 'project'
                ? 'text-gray-800 border-b-2 border-gray-500'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            项目资料
            {projectFiles.length > 0 ? (
              <span className="ml-1 rounded-full bg-gray-200 px-1.5 py-0.5 text-[9px]">{projectFiles.length}</span>
            ) : null}
          </button>
        ) : null}
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

        {/* ── 项目资料 ── */}
        {tab === 'project' && project ? (
          <div className="p-4">
            <div className="mb-4 rounded-xl border border-gray-200 bg-white p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-black text-gray-800">📁 {project.name}</div>
                  <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-gray-500">
                    {project.description || '项目说明与资料会由服务端加入本项目会话的上下文。'}
                  </div>
                </div>
                <button onClick={onOpenProject} className="shrink-0 rounded-lg bg-gray-100 px-2 py-1 text-[10px] font-bold text-gray-600 hover:bg-gray-200">管理</button>
              </div>
            </div>
            {projectFilesLoading ? (
              <div className="py-12 text-center text-xs text-gray-400">加载中…</div>
            ) : projectFiles.length === 0 ? (
              <div className="py-12 text-center">
                <div className="text-2xl">📚</div>
                <div className="mt-2 text-xs font-bold text-gray-500">暂无项目资料</div>
                <button onClick={onOpenProject} className="mt-3 text-xs font-bold text-gray-700 underline">前往项目上传</button>
              </div>
            ) : (
              <div className="space-y-2">
                {projectFiles.map(file => (
                  <div key={file.id} className="rounded-xl border border-gray-200 bg-white p-3">
                    <div className="truncate text-xs font-bold text-gray-800">{file.display_name}</div>
                    <div className="mt-1 text-[10px] text-gray-400">{file.media_type || '文件'} · {(file.size_bytes / 1024).toFixed(file.size_bytes >= 1024 ? 1 : 0)} KB</div>
                    <div className="mt-2 flex gap-2">
                      <a href={getProjectFileUrl(project.id, file.id)} target="_blank" rel="noreferrer" className="text-[10px] font-bold text-gray-600 hover:underline">打开</a>
                      <a href={getProjectFileUrl(project.id, file.id, { download: true })} className="text-[10px] font-bold text-gray-600 hover:underline">下载</a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}

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

        {/* ── 会话文件 ── */}
        {tab === 'files' && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-black uppercase tracking-widest text-gray-400">文件目录</span>
              <button
                onClick={loadFileTree}
                disabled={filesLoading}
                className="p-1.5 hover:bg-gray-200 rounded-lg text-gray-400 hover:text-gray-600 transition-colors disabled:opacity-50"
                title="刷新文件列表"
              >
                <svg className={`w-3.5 h-3.5 ${filesLoading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            {filesLoading ? (
              <div className="flex items-center justify-center h-32">
                <span className="text-xs text-gray-400">加载中...</span>
              </div>
            ) : fileTree.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-center px-6 space-y-4">
                <div className="w-12 h-12 bg-white rounded-2xl shadow-sm border border-gray-200 flex items-center justify-center text-2xl">📁</div>
                <div>
                  <p className="text-sm font-bold text-gray-700">暂无文件</p>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                    会话工作区中暂无文件输出
                  </p>
                </div>
              </div>
            ) : (
              <FileTreeView
                nodes={fileTree}
                sessionId={sessionId!}
                expanded={expandedDirs}
                onToggleExpand={(path) => {
                  setExpandedDirs(prev => {
                    const next = new Set(prev);
                    if (next.has(path)) next.delete(path);
                    else next.add(path);
                    return next;
                  });
                }}
                onRefresh={loadFileTree}
                projectId={project?.id}
                projectName={project?.name}
                importDisabled={Boolean(isFetching)}
                onImportProjectFile={onImportProjectFile}
              />
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

// ── 文件树组件 ──────────────────────────────────────────────────────────── //

interface FileTreeViewProps {
  nodes: WorkspaceFileNode[];
  sessionId: string;
  expanded: Set<string>;
  onToggleExpand: (path: string) => void;
  onRefresh: () => void;
  projectId?: string;
  projectName?: string;
  importDisabled?: boolean;
  onImportProjectFile?: (path: string, displayName: string) => Promise<void>;
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return '🖼️';
  if (['py', 'js', 'ts', 'jsx', 'tsx', 'go', 'rs', 'java', 'c', 'cpp'].includes(ext)) return '📄';
  if (['md', 'txt', 'log'].includes(ext)) return '📝';
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '⚙️';
  if (['html', 'htm'].includes(ext)) return '🌐';
  if (['css', 'scss', 'less'].includes(ext)) return '🎨';
  if (['csv', 'xlsx', 'xls'].includes(ext)) return '📊';
  if (['pdf'].includes(ext)) return '📕';
  if (['zip', 'tar', 'gz', 'rar'].includes(ext)) return '📦';
  return '📄';
}

const FileTreeView: React.FC<FileTreeViewProps> = ({
  nodes,
  sessionId,
  expanded,
  onToggleExpand,
  onRefresh,
  projectId,
  projectName,
  importDisabled,
  onImportProjectFile,
}) => {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<Record<string, 'adding' | 'added'>>({});

  useEffect(() => {
    setImportStatus({});
  }, [sessionId, projectId]);

  const handleDelete = async (path: string) => {
    if (importDisabled) return;
    setDeleting(path);
    try {
      await api.deleteWorkspaceFile(sessionId, path);
      onRefresh();
    } catch {
      // ignore
    } finally {
      setDeleting(null);
    }
  };

  const handleImport = async (node: WorkspaceFileNode) => {
    if (!onImportProjectFile || importStatus[node.path]) return;
    setImportStatus(prev => ({ ...prev, [node.path]: 'adding' }));
    try {
      await onImportProjectFile(node.path, node.name);
      setImportStatus(prev => ({ ...prev, [node.path]: 'added' }));
    } catch (error) {
      setImportStatus(prev => {
        const next = { ...prev };
        delete next[node.path];
        return next;
      });
      window.alert(error instanceof Error ? error.message : '加入项目资料失败');
    }
  };

  const renderNode = (node: WorkspaceFileNode, depth: number) => {
    const isDir = node.type === 'directory';
    const isExpanded = expanded.has(node.path);
    const isDeleting = deleting === node.path;

    return (
      <div key={node.path}>
        <div
          className={`flex items-center gap-1.5 py-1.5 px-2 rounded-lg group hover:bg-gray-100 transition-colors cursor-pointer ${
            isDir && isExpanded ? 'bg-gray-50' : ''
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => isDir && onToggleExpand(node.path)}
          title={node.name}
        >
          <span className="text-xs shrink-0">{isDir ? (isExpanded ? '📂' : '📁') : getFileIcon(node.name)}</span>
          <span className="text-[11px] font-medium text-gray-700 truncate flex-1">{node.name}</span>

          {!isDir && !isDeleting && (
            <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
              {onImportProjectFile && isSupportedProjectMaterial(node.path, node.name, sessionId) && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); handleImport(node); }}
                  disabled={importDisabled || Boolean(importStatus[node.path])}
                  className="rounded-md px-1.5 py-1 text-[9px] font-bold text-gray-600 hover:bg-gray-200 disabled:text-gray-400"
                  title={importDisabled ? '会话执行完成后可加入项目资料' : `加入「${projectName || ''}」项目资料`}
                >
                  {importStatus[node.path] === 'adding'
                    ? '加入中'
                    : importStatus[node.path] === 'added'
                      ? '已加入'
                      : '加入项目'}
                </button>
              )}
              {!shouldForceWorkspaceDownload(node.path) && (
                <a
                  href={getWorkspaceFileUrl(node.path, { sessionId })}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="p-1 hover:bg-gray-200 rounded-md text-gray-400 hover:text-gray-600 transition-colors"
                  title="预览"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                </a>
              )}
              <a
                href={getWorkspaceFileUrl(node.path, { download: true, filename: node.name, sessionId })}
                onClick={(e) => e.stopPropagation()}
                className="p-1 hover:bg-gray-200 rounded-md text-gray-400 hover:text-gray-600 transition-colors"
                title="下载"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              </a>
              <button
                onClick={(e) => { e.stopPropagation(); handleDelete(node.path); }}
                disabled={importDisabled}
                className="p-1 hover:bg-red-100 rounded-md text-gray-400 hover:text-red-500 transition-colors disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                title={importDisabled ? '会话执行完成后可删除文件' : '删除'}
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          )}

          {isDeleting && (
            <span className="text-[9px] text-gray-400 shrink-0">删除中...</span>
          )}
        </div>

        {isDir && isExpanded && node.children?.map(child => renderNode(child, depth + 1))}
      </div>
    );
  };

  return <div className="space-y-0.5">{nodes.map(node => renderNode(node, 0))}</div>;
};

export default ReferenceArea;
