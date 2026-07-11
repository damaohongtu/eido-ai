import React, { useCallback, useEffect, useState } from 'react';
import { Popup, Dialog, SpinLoading, Empty, Toast } from 'antd-mobile';
import type { WorkspaceFileNode } from '../shared';
import type { AgentRuntime } from '../runtime/types';

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

interface FilesPanelProps {
  sessionId: string;
  visible: boolean;
  onClose: () => void;
  agentRuntime: AgentRuntime;
}

const FilesPanel: React.FC<FilesPanelProps> = ({ sessionId, visible, onClose, agentRuntime }) => {
  const [tree, setTree] = useState<WorkspaceFileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!sessionId) return;
    setLoading(true);
    agentRuntime
      .listWorkspaceFiles(sessionId)
      .then(setTree)
      .catch(() => setTree([]))
      .finally(() => setLoading(false));
  }, [agentRuntime, sessionId]);

  useEffect(() => {
    if (visible) load();
  }, [visible, load]);

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const handleDelete = async (node: WorkspaceFileNode) => {
    const ok = await Dialog.confirm({
      content: `删除文件「${node.name}」？`,
      confirmText: '删除',
      cancelText: '取消',
    });
    if (!ok) return;
    setDeleting(node.path);
    try {
      await agentRuntime.deleteWorkspaceFile(sessionId, node.path);
      load();
    } catch {
      Toast.show('删除失败');
    } finally {
      setDeleting(null);
    }
  };

  const handleOpen = async (node: WorkspaceFileNode, download = false) => {
    if (!agentRuntime.openWorkspaceFile) return;
    try {
      await agentRuntime.openWorkspaceFile(node.path, {
        download,
        filename: node.name,
        sessionId,
      });
    } catch (error) {
      Toast.show({ content: error instanceof Error ? error.message : '读取文件失败' });
    }
  };

  const renderNode = (node: WorkspaceFileNode, depth: number): React.ReactNode => {
    const isDir = node.type === 'directory';
    const isExpanded = expanded.has(node.path);
    const isDeleting = deleting === node.path;
    const pad = depth * 14 + 12;

    return (
      <div key={node.path}>
        <div
          className="flex items-center gap-2 py-2.5 active:bg-gray-100"
          style={{ paddingLeft: pad, paddingRight: 12 }}
          onClick={() => isDir && toggle(node.path)}
        >
          <span className="shrink-0 text-base">
            {isDir ? (isExpanded ? '📂' : '📁') : getFileIcon(node.name)}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-700">
            {node.name}
          </span>

          {isDeleting ? (
            <span className="shrink-0 text-[11px] text-gray-400">删除中…</span>
          ) : (
            !isDir && (
              <div className="flex shrink-0 items-center gap-1">
                {agentRuntime.openWorkspaceFile ? (
                  <>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleOpen(node); }}
                      className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-gray-600 active:bg-gray-200"
                    >
                      预览
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleOpen(node, true); }}
                      className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-gray-600 active:bg-gray-200"
                    >
                      下载
                    </button>
                  </>
                ) : (
                  <>
                    <a
                      href={agentRuntime.getWorkspaceFileUrl(node.path, { sessionId })}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-gray-600 active:bg-gray-200"
                    >
                      预览
                    </a>
                    <a
                      href={agentRuntime.getWorkspaceFileUrl(node.path, { download: true, filename: node.name, sessionId })}
                      onClick={(e) => e.stopPropagation()}
                      className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-gray-600 active:bg-gray-200"
                    >
                      下载
                    </a>
                  </>
                )}
                {agentRuntime.canDeleteWorkspaceFiles !== false ? (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(node);
                    }}
                    className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-red-500 active:bg-red-50"
                  >
                    删除
                  </button>
                ) : null}
              </div>
            )
          )}
        </div>

        {isDir && isExpanded && node.children?.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  };

  return (
    <Popup
      visible={visible}
      onMaskClick={onClose}
      position="right"
      bodyStyle={{ width: '85vw', maxWidth: 420, height: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      <div className="flex h-full flex-col bg-white" style={{ paddingTop: 'var(--eido-safe-top)' }}>
        <header className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h3 className="text-base font-bold text-gray-900">会话文件</h3>
          <div className="flex items-center gap-1">
            <button
              onClick={load}
              disabled={loading}
              className="rounded-lg p-1.5 text-gray-400 active:bg-gray-100 disabled:opacity-50"
              title="刷新"
            >
              <svg
                className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
            </button>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 active:bg-gray-100"
              title="关闭"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </header>

        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
          {loading && tree.length === 0 ? (
            <div className="flex h-40 items-center justify-center">
              <SpinLoading color="default" />
            </div>
          ) : tree.length === 0 ? (
            <div className="pt-20">
              <Empty description="会话工作区中暂无文件输出" />
            </div>
          ) : (
            <div className="divide-y divide-gray-50 py-1">{tree.map((node) => renderNode(node, 0))}</div>
          )}
        </div>

        <div style={{ height: 'var(--eido-safe-bottom)' }} />
      </div>
    </Popup>
  );
};

export default FilesPanel;
