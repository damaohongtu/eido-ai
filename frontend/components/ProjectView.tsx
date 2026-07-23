import React, { useEffect, useRef, useState } from 'react';
import { ChatSession, Project, ProjectFile } from '../types';
import { getProjectFileUrl } from '../services/api';
import { canPreviewInBrowser, PROJECT_MATERIAL_ACCEPT } from '../utils/projectFiles';

interface CreateProjectModalProps {
  open: boolean;
  creating?: boolean;
  onClose: () => void;
  onCreate: (input: { name: string; description?: string; instructions?: string }) => Promise<void>;
}

export const CreateProjectModal: React.FC<CreateProjectModalProps> = ({ open, creating, onClose, onCreate }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
    }
  }, [open]);

  if (!open) return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() || creating) return;
    await onCreate({ name: name.trim(), description: description.trim() || undefined });
  };

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/25 px-4" onMouseDown={onClose}>
      <form
        onSubmit={submit}
        onMouseDown={(event) => event.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-2xl"
      >
        <h2 className="text-lg font-black text-gray-900">新建项目</h2>
        <p className="mt-1 text-sm text-gray-500">项目可汇总多段对话、共享说明和资料。</p>
        <label className="mt-5 block text-xs font-bold text-gray-600">
          项目名称
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={80}
            className="mt-2 w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-500"
            placeholder="例如：2026 行业研究"
          />
        </label>
        <label className="mt-4 block text-xs font-bold text-gray-600">
          简介（可选）
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={2000}
            rows={3}
            className="mt-2 w-full resize-none rounded-xl border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-500"
            placeholder="这个项目要解决什么问题？"
          />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 text-sm font-bold text-gray-500 hover:bg-gray-100">
            取消
          </button>
          <button
            type="submit"
            disabled={!name.trim() || creating}
            className="rounded-xl bg-gray-800 px-5 py-2 text-sm font-bold text-white hover:bg-gray-900 disabled:opacity-40"
          >
            {creating ? '创建中…' : '创建项目'}
          </button>
        </div>
      </form>
    </div>
  );
};

interface ProjectViewProps {
  project: Project;
  sessions: ChatSession[];
  files: ProjectFile[];
  filesLoading: boolean;
  saving: boolean;
  onNewChat: () => void;
  onOpenSession: (id: string) => void;
  onMoveSession: (sessionId: string, projectId: string | null) => Promise<void>;
  onSave: (patch: { name: string; description: string; instructions: string }) => Promise<void>;
  onDelete: () => Promise<void>;
  onUploadFile: (file: File) => Promise<void>;
  onDeleteFile: (fileId: string) => Promise<void>;
  onRefreshFiles: () => void;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

const ProjectView: React.FC<ProjectViewProps> = ({
  project,
  sessions,
  files,
  filesLoading,
  saving,
  onNewChat,
  onOpenSession,
  onMoveSession,
  onSave,
  onDelete,
  onUploadFile,
  onDeleteFile,
  onRefreshFiles,
}) => {
  const [tab, setTab] = useState<'overview' | 'sessions' | 'files'>('overview');
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || '');
  const [instructions, setInstructions] = useState(project.instructions || '');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || '');
    setInstructions(project.instructions || '');
    setTab('overview');
  }, [project.id]);

  const dirty = name.trim() !== project.name
    || description.trim() !== (project.description || '')
    || instructions.trim() !== (project.instructions || '');

  const handleFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = [...(event.target.files || [])];
    event.target.value = '';
    if (!selected.length) return;
    setUploading(true);
    try {
      for (const file of selected) await onUploadFile(file);
    } finally {
      setUploading(false);
    }
  };

  const confirmDeleteProject = async () => {
    if (!window.confirm(`删除项目「${project.name}」？项目内会话会保留并移至对话。`)) return;
    await onDelete();
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-black tracking-tight text-gray-900">{project.name}</h1>
            <p className="truncate text-sm font-medium text-gray-500">
              {project.description || '管理项目说明、会话与共享资料'}
            </p>
          </div>
          <button
            onClick={onNewChat}
            disabled={Boolean(project.archived_at)}
            className="shrink-0 rounded-lg bg-gray-700 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {project.archived_at ? '项目已归档' : '+ 项目内新建会话'}
          </button>
        </header>

        <nav aria-label="项目详情" className="mb-6 flex gap-6 overflow-x-auto border-b border-gray-200">
          {([
            ['overview', '概览与说明'],
            ['sessions', `会话 ${sessions.length}`],
            ['files', `共享资料 ${files.length}`],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`border-b-2 py-3 text-sm font-bold ${tab === key ? 'border-gray-800 text-gray-900' : 'border-transparent text-gray-400 hover:text-gray-700'}`}
            >
              {label}
            </button>
          ))}
        </nav>

        {tab === 'overview' ? (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)]">
            <section className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="flex items-center justify-between">
                <h2 className="font-black text-gray-900">项目设置</h2>
                <span className="text-xs text-gray-400">上下文版本 {project.context_revision}</span>
              </div>
              <label className="mt-5 block text-xs font-bold text-gray-600">
                名称
                <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-500" />
              </label>
              <label className="mt-4 block text-xs font-bold text-gray-600">
                简介
                <textarea value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} rows={3} className="mt-2 w-full resize-y rounded-xl border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-500" />
              </label>
              <label className="mt-4 block text-xs font-bold text-gray-600">
                项目说明
                <span className="ml-2 font-normal text-gray-400">每次项目会话执行时由服务端自动加入上下文</span>
                <textarea
                  value={instructions}
                  maxLength={20000}
                  onChange={(event) => setInstructions(event.target.value)}
                  rows={10}
                  className="mt-2 w-full resize-y rounded-xl border border-gray-300 px-3 py-2.5 text-sm leading-relaxed outline-none focus:border-gray-500"
                  placeholder="例如：默认使用中文回答；优先引用项目资料；结论需列出风险。"
                />
              </label>
              <div className="mt-5 flex justify-between gap-3">
                <button onClick={confirmDeleteProject} className="rounded-xl px-3 py-2 text-sm font-bold text-red-500 hover:bg-red-50">删除项目</button>
                <button
                  disabled={!dirty || !name.trim() || saving}
                  onClick={() => onSave({ name: name.trim(), description: description.trim(), instructions: instructions.trim() })}
                  className="rounded-xl bg-gray-800 px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
                >
                  {saving ? '保存中…' : '保存更改'}
                </button>
              </div>
            </section>

            <aside className="space-y-4">
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="text-xs font-bold text-gray-400">会话</div>
                <div className="mt-1 text-3xl font-black text-gray-900">{sessions.length}</div>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="text-xs font-bold text-gray-400">共享资料</div>
                <div className="mt-1 text-3xl font-black text-gray-900">{files.length}</div>
                <button onClick={() => setTab('files')} className="mt-3 text-xs font-bold text-gray-600 hover:text-gray-900">管理资料 →</button>
              </div>
            </aside>
          </div>
        ) : null}

        {tab === 'sessions' ? (
          <section className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            {sessions.length === 0 ? (
              <div className="p-12 text-center">
                <p className="text-sm text-gray-500">项目中还没有会话</p>
                {!project.archived_at ? <button onClick={onNewChat} className="mt-4 rounded-xl bg-gray-800 px-4 py-2 text-sm font-bold text-white">新建第一段会话</button> : null}
              </div>
            ) : sessions.map((session) => (
              <div key={session.id} className="flex items-center gap-3 border-b border-gray-100 px-5 py-4 last:border-0 hover:bg-gray-50">
                <button onClick={() => onOpenSession(session.id)} className="min-w-0 flex-1 text-left">
                  <div className="truncate text-sm font-bold text-gray-800">{session.title}</div>
                  <div className="mt-1 text-xs text-gray-400">{new Date(session.updatedAt).toLocaleString()}</div>
                </button>
                <button onClick={() => onMoveSession(session.id, null)} className="rounded-lg px-3 py-1.5 text-xs font-bold text-gray-400 hover:bg-gray-100 hover:text-gray-700">移出项目</button>
              </div>
            ))}
          </section>
        ) : null}

        {tab === 'files' ? (
          <section className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="font-black text-gray-900">共享资料</h2>
                <p className="mt-1 text-xs text-gray-500">这些资料由服务端按项目注入，不会自动发送到本机 OpenCode。</p>
              </div>
              <div className="flex gap-2">
                <button onClick={onRefreshFiles} className="rounded-xl border border-gray-200 px-3 py-2 text-xs font-bold text-gray-500 hover:bg-gray-50">刷新</button>
                <button onClick={() => fileRef.current?.click()} disabled={uploading || Boolean(project.archived_at)} className="rounded-xl bg-gray-800 px-4 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50">
                  {project.archived_at ? '项目已归档' : uploading ? '上传中…' : '上传资料'}
                </button>
                <input ref={fileRef} type="file" accept={PROJECT_MATERIAL_ACCEPT} multiple className="hidden" onChange={handleFiles} />
              </div>
            </div>
            <div className="mt-5 overflow-hidden rounded-xl border border-gray-200">
              {filesLoading ? (
                <div className="p-10 text-center text-sm text-gray-400">加载中…</div>
              ) : files.length === 0 ? (
                <div className="p-10 text-center text-sm text-gray-400">暂无共享资料</div>
              ) : files.map((file) => (
                <div key={file.id} className="flex items-center gap-3 border-b border-gray-100 px-4 py-3 last:border-0">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100">📄</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-bold text-gray-800">{file.display_name}</div>
                    <div className="text-xs text-gray-400">{file.media_type || '文件'} · {formatBytes(file.size_bytes)}</div>
                  </div>
                  {canPreviewInBrowser(file.display_name) && (
                    <a href={getProjectFileUrl(project.id, file.id, { preview: true })} target="_blank" rel="noopener noreferrer" className="rounded-lg px-2 py-1.5 text-xs font-bold text-gray-500 hover:bg-gray-100">预览</a>
                  )}
                  <a href={getProjectFileUrl(project.id, file.id, { download: true })} className="rounded-lg px-2 py-1.5 text-xs font-bold text-gray-500 hover:bg-gray-100">下载</a>
                  <button onClick={() => onDeleteFile(file.id)} className="rounded-lg px-2 py-1.5 text-xs font-bold text-red-400 hover:bg-red-50">删除</button>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
};

export default ProjectView;
