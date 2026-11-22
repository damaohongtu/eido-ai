import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  api,
  getProjectFileUrl,
  getWorkspaceFileUrl,
  type WorkspaceFileNode,
} from '../services/api';
import { skillCanManage, type Skill, type ScheduledTask } from '../types';
import type { useAppController } from '../hooks/useAppController';
import {
  PROJECT_MATERIAL_ACCEPT,
  canPreviewInBrowser,
  isSupportedProjectMaterial,
} from '../utils/projectFiles';
import { describeSchedule, getChatPrompt } from '../utils/scheduleTask';
import ScheduledTaskModal from '../components/ScheduledTaskModal';
import { Empty, ErrorMessage, Icon, Sheet, errorText } from './ui';
import SkillEditor, { SkillFiles } from './SkillEditor';

export type AppController = ReturnType<typeof useAppController>;

export function Home({ app }: { app: AppController }) {
  return (
    <div className="h5-page h5-home">
      <div className="h5-eyebrow">
        <span /> YOUR EVERYDAY COPILOT
      </div>
      <h1>
        让想法，
        <br />
        向前一步<span>。</span>
      </h1>
      <p className="h5-intro">从一个问题开始，把灵感变成答案。</p>
      <button
        className="h5-start"
        onClick={() => app.createNewSession({ projectId: null })}
      >
        <span>
          <Icon name="spark" size={28} />
          <strong>开启新的对话</strong>
          <small>思考、研究、创作，随时出发</small>
        </span>
        <Icon name="send" />
      </button>
      <div className="h5-section-title">
        <h2>你的项目</h2>
        <button onClick={() => app.setCreateProjectOpen(true)}>新建 ＋</button>
      </div>
      <div className="h5-project-strip">
        {app.projects
          .filter((p) => !p.archived_at)
          .slice(0, 6)
          .map((p) => (
            <button key={p.id} onClick={() => app.openProject(p.id)}>
              <Icon name="folder" />
              <strong>{p.name}</strong>
              <small>{p.session_count} 段对话</small>
            </button>
          ))}
        {!app.projects.some((p) => !p.archived_at) && (
          <button
            className="h5-project-placeholder"
            onClick={() => app.setCreateProjectOpen(true)}
          >
            <Icon name="plus" />
            <strong>给想法一个空间</strong>
            <small>用项目整理对话和资料</small>
          </button>
        )}
      </div>
      <div className="h5-section-title">
        <h2>发现技能</h2>
        <span className="h5-muted">为工作多一点可能</span>
      </div>
      {app.loading ? (
        <p role="status">正在加载技能…</p>
      ) : (
        <div className="h5-list">
          {app.systemSkills.slice(0, 6).map((s) => (
            <button
              key={s.id}
              onClick={() =>
                app.createNewSession({ skillId: s.id, projectId: null })
              }
            >
              <span className="h5-skill-icon">{s.icon || '✧'}</span>
              <div>
                <strong>{s.name}</strong>
                <p>{s.description}</p>
              </div>
              <span>↗</span>
            </button>
          ))}
        </div>
      )}
      {!app.loading && !app.systemSkills.length && (
        <Empty>技能库暂时为空，可以直接开启对话。</Empty>
      )}
    </div>
  );
}

export function Project({ app }: { app: AppController }) {
  const project = app.activeProject!;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [instructions, setInstructions] = useState(project.instructions);
  const [uploading, setUploading] = useState(false);
  const files =
    app.projectFilesProjectId === project.id ? app.projectFiles : [];
  return (
    <div className="h5-page">
      <div className="h5-eyebrow">
        <Icon name="folder" size={16} /> 项目空间
        {project.archived_at ? ' · 已归档' : ''}
      </div>
      <h1>{project.name}</h1>
      <p className="h5-intro">
        {project.description || '汇集对话与资料，让研究持续积累。'}
      </p>
      <div className="h5-actions">
        <button
          className="h5-primary"
          disabled={Boolean(project.archived_at)}
          onClick={() => app.createNewSession({ projectId: project.id })}
        >
          新建对话 ＋
        </button>
        <button className="h5-secondary" onClick={() => setEditing(true)}>
          项目设置
        </button>
      </div>
      <div className="h5-section-title">
        <h2>共享资料</h2>
        <label className="h5-upload">
          {uploading ? '上传中…' : '上传 ＋'}
          <input
            type="file"
            hidden
            accept={PROJECT_MATERIAL_ACCEPT}
            disabled={uploading || Boolean(project.archived_at)}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setUploading(true);
              try {
                await app.uploadProjectFile(file);
              } finally {
                setUploading(false);
                e.target.value = '';
              }
            }}
          />
        </label>
      </div>
      {app.projectFilesLoading ? (
        <p role="status">加载资料中…</p>
      ) : files.length ? (
        files.map((f) => (
          <div className="h5-file" key={f.id}>
            <Icon name="file" />
            <div>
              <strong>{f.display_name}</strong>
              <small>{Math.ceil(f.size_bytes / 1024)} KB</small>
              <div className="h5-actions">
                {canPreviewInBrowser(f.display_name) && (
                  <a
                    href={getProjectFileUrl(project.id, f.id, {
                      preview: true,
                    })}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    预览
                  </a>
                )}
                <a
                  href={getProjectFileUrl(project.id, f.id, { download: true })}
                >
                  下载
                </a>
                {!project.archived_at && (
                  <button onClick={() => app.deleteProjectFile(f.id)}>
                    删除
                  </button>
                )}
              </div>
            </div>
          </div>
        ))
      ) : (
        <p className="h5-muted">上传资料，同一项目中的对话都可以使用。</p>
      )}
      <div className="h5-section-title">
        <h2>项目对话</h2>
      </div>
      <div className="h5-list">
        {app.sessions
          .filter((s) => s.projectId === project.id)
          .map((s) => (
            <button key={s.id} onClick={() => app.selectSession(s.id)}>
              <Icon name="chat" />
              <div>
                <strong>{s.title}</strong>
                <small>
                  {new Date(s.updatedAt).toLocaleDateString('zh-CN')}
                </small>
              </div>
              <span>›</span>
            </button>
          ))}
      </div>
      {editing && (
        <Sheet title="项目设置" onClose={() => setEditing(false)}>
          <form
            className="h5-form"
            onSubmit={async (e) => {
              e.preventDefault();
              await app.saveProject({ name, description, instructions });
              setEditing(false);
            }}
          >
            <label>
              名称
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                required
              />
            </label>
            <label>
              简介
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </label>
            <label>
              共享说明
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                rows={6}
              />
            </label>
            <button className="h5-primary" disabled={app.savingProject}>
              保存更改
            </button>
            <button
              type="button"
              className="h5-danger"
              onClick={() => {
                if (
                  confirm(`删除项目「${project.name}」？项目内的对话将保留。`)
                )
                  void app.deleteProject();
              }}
            >
              删除项目
            </button>
          </form>
        </Sheet>
      )}
    </div>
  );
}

export function Skills({ app }: { app: AppController }) {
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  return (
    <div className="h5-page">
      <div className="h5-eyebrow">A LITTLE EXTRA POSSIBILITY</div>
      <h1>技能，让想法落地。</h1>
      <p className="h5-intro">找到适合你的能力，交给 Eido 一起完成。</p>
      <div className="h5-section-title">
        <h2>全部技能 · {app.allSkills.length}</h2>
        <button onClick={() => setCreating(true)}>新建</button>
        <label className="h5-upload">
          {uploading ? '上传中…' : '导入技能 ＋'}
          <input
            hidden
            type="file"
            accept=".zip,.md,.skill"
            disabled={uploading}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setUploading(true);
              setError('');
              try {
                await api.uploadSkill(file);
                await app.refreshSkills();
              } catch (err) {
                setError(errorText(err));
              } finally {
                setUploading(false);
                e.target.value = '';
              }
            }}
          />
        </label>
      </div>
      <ErrorMessage error={error} />
      <input
        type="search"
        className="h5-search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="搜索技能名称或描述"
        aria-label="搜索技能"
      />
      <div className="h5-list">
        {app.allSkills
          .filter((s) =>
            `${s.name} ${s.description}`
              .toLowerCase()
              .includes(query.toLowerCase()),
          )
          .map((s) => (
            <div className="h5-skill-row" key={s.id}>
              <button onClick={() => app.setDetailSkill(s)}>
                <span className="h5-skill-icon">{s.icon || '✧'}</span>
                <div>
                  <strong>{s.name}</strong>
                  <p>{s.description}</p>
                  <small>{s.is_system ? '系统技能' : '我的技能'}</small>
                </div>
              </button>
              <button
                className="h5-skill-use"
                onClick={() =>
                  app.createNewSession({ skillId: s.id, projectId: null })
                }
              >
                使用
              </button>
            </div>
          ))}
      </div>
      {!app.allSkills.length && <Empty>还没有可用技能，试试导入一个。</Empty>}
      {creating && (
        <SkillEditor
          onClose={() => setCreating(false)}
          onSaved={app.refreshSkills}
        />
      )}
      {app.detailSkill && (
        <SkillDetail
          key={app.detailSkill.id}
          skill={app.detailSkill}
          app={app}
        />
      )}
    </div>
  );
}

function SkillDetail({ skill, app }: { skill: Skill; app: AppController }) {
  const [tab, setTab] = useState<'detail' | 'files'>('detail');
  const [editing, setEditing] = useState(false);
  const [detail, setDetail] = useState(skill.detail || skill.description);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api
      .getSkill(skill.id)
      .then((s) => {
        if (active) setDetail(s.detail || s.description);
      })
      .catch((e) => {
        if (active) setError(errorText(e));
      });
    return () => {
      active = false;
    };
  }, [skill.id]);
  return (
    <Sheet title={skill.name} onClose={() => app.setDetailSkill(null)}>
      <ErrorMessage error={error} />
      <div className="h5-segment">
        <button
          aria-pressed={tab === 'detail'}
          onClick={() => setTab('detail')}
        >
          技能说明
        </button>
        <button aria-pressed={tab === 'files'} onClick={() => setTab('files')}>
          技能文件
        </button>
      </div>
      {tab === 'detail' ? (
        <div className="markdown-body h5-skill-detail">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail}</ReactMarkdown>
        </div>
      ) : (
        <SkillFiles skill={skill} />
      )}
      {editing && (
        <SkillEditor
          skill={{ ...skill, detail }}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            await app.refreshSkills();
            const updated = await api.getSkill(skill.id);
            setDetail(updated.detail || updated.description);
            app.setDetailSkill(updated);
          }}
        />
      )}
      {skillCanManage(skill) && (
        <button
          className="h5-secondary h5-wide"
          onClick={() => setEditing(true)}
        >
          编辑技能
        </button>
      )}
      <div className="h5-form">
        <button
          className="h5-primary"
          onClick={() => {
            app.setDetailSkill(null);
            void app.createNewSession({ skillId: skill.id, projectId: null });
          }}
        >
          使用此技能
        </button>
        {skillCanManage(skill) && (
          <button
            className="h5-danger"
            onClick={async () => {
              if (!confirm(`删除技能「${skill.name}」？`)) return;
              try {
                await api.deleteSkill(skill.id);
                await app.refreshSkills();
                app.setDetailSkill(null);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            删除技能
          </button>
        )}
      </div>
    </Sheet>
  );
}

export { default as Tools } from './McpManager';

export function Tasks({ app }: { app: AppController }) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = async () => {
    setError('');
    try {
      setTasks(await api.listTasks());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const act = async (id: string, action: () => Promise<unknown>) => {
    setBusy(id);
    setError('');
    try {
      await action();
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="h5-page">
      <div className="h5-eyebrow">MAKE TIME FOR WHAT MATTERS</div>
      <h1>把重复，交给时间。</h1>
      <p className="h5-intro">定时执行日常工作，让每一天从容一点。</p>
      <div className="h5-section-title">
        <h2>自动任务</h2>
        <button
          onClick={() => {
            setEditing(null);
            setModal(true);
          }}
        >
          新建 ＋
        </button>
      </div>
      <ErrorMessage error={error} />
      {loading && <p role="status">加载任务中…</p>}
      {tasks.map((t) => (
        <article className="h5-card" key={t.id}>
          <div className="h5-section-title">
            <h3>{t.name}</h3>
            <button
              role="switch"
              aria-checked={t.enabled}
              aria-label={`启用 ${t.name}`}
              disabled={busy === t.id}
              onClick={() =>
                act(t.id, () => api.updateTask(t.id, { enabled: !t.enabled }))
              }
            >
              {t.enabled ? '已开启 ●' : '已暂停 ○'}
            </button>
          </div>
          <small>{describeSchedule(t.schedule)}</small>
          <p>{getChatPrompt(t) || t.type}</p>
          <small>
            上次执行：
            {t.last_run_at
              ? new Date(t.last_run_at).toLocaleString('zh-CN')
              : '尚未执行'}
          </small>
          <div className="h5-actions">
            <button
              disabled={busy === t.id}
              onClick={() =>
                act(t.id, async () => {
                  const run = await api.runTaskNow(t.id);
                  await app.openTaskSession(run.session_id);
                })
              }
            >
              立即执行
            </button>
            {t.type === 'chat' && (
              <button
                onClick={() => {
                  setEditing(t);
                  setModal(true);
                }}
              >
                编辑
              </button>
            )}
            <button
              disabled={busy === t.id}
              onClick={() => {
                if (confirm(`删除任务「${t.name}」？`))
                  void act(t.id, () => api.deleteTask(t.id));
              }}
            >
              删除
            </button>
          </div>
        </article>
      ))}
      {!loading && !tasks.length && (
        <Empty>创建第一个自动任务，让 Eido 按时开始工作。</Empty>
      )}
      <ScheduledTaskModal
        visible={modal}
        onSuccess={() => setModal(false)}
        editing={editing}
        onClose={() => setModal(false)}
        onSubmit={async (payload) => {
          if (editing) await api.updateTask(editing.id, payload);
          else await api.createTask(payload);
          await load();
        }}
      />
    </div>
  );
}

function flattenFiles(nodes: WorkspaceFileNode[]): WorkspaceFileNode[] {
  return nodes.flatMap((n) =>
    n.type === 'file' ? [n] : flattenFiles(n.children || []),
  );
}

export function Resources({ app }: { app: AppController }) {
  const sessionId = app.activeSessionId!;
  const [tab, setTab] = useState<'files' | 'references' | 'process'>('files');
  const [files, setFiles] = useState<WorkspaceFileNode[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setFiles(flattenFiles(await api.listWorkspaceFiles(sessionId)));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, [sessionId]);
  return (
    <Sheet title="资料与执行记录" onClose={() => app.setRightPanelOpen(false)}>
      <div className="h5-segment">
        {(['files', 'references', 'process'] as const).map((key, i) => (
          <button
            key={key}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            {['会话文件', '参考来源', '执行记录'][i]}
          </button>
        ))}
      </div>
      <ErrorMessage error={error} />
      {tab === 'files' && (
        <>
          <div className="h5-section-title">
            <h3>工作区文件</h3>
            <button disabled={loading} onClick={load}>
              {loading ? '加载中…' : '刷新'}
            </button>
          </div>
          {files.map((f) => (
            <div className="h5-file" key={f.path}>
              <Icon name="file" />
              <div>
                <strong>{f.name}</strong>
                <div className="h5-actions">
                  {canPreviewInBrowser(f.path) && (
                    <a
                      href={getWorkspaceFileUrl(f.path, {
                        sessionId,
                        preview: true,
                      })}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      预览
                    </a>
                  )}
                  <a
                    href={getWorkspaceFileUrl(f.path, {
                      sessionId,
                      download: true,
                      filename: f.name,
                    })}
                  >
                    下载
                  </a>
                  {app.activeSessionProject &&
                    !app.activeSessionProject.archived_at &&
                    isSupportedProjectMaterial(f.path, f.name, sessionId) && (
                      <button
                        disabled={
                          Boolean(adding) ||
                          app.runningSessionIds.has(sessionId)
                        }
                        onClick={async () => {
                          setAdding(f.path);
                          try {
                            await app.importSessionFileToProject(
                              f.path,
                              f.name,
                            );
                          } catch (e) {
                            setError(errorText(e));
                          } finally {
                            setAdding(null);
                          }
                        }}
                      >
                        {adding === f.path ? '加入中…' : '加入项目'}
                      </button>
                    )}
                </div>
              </div>
            </div>
          ))}
          {!loading && !files.length && (
            <Empty>生成和上传的文件会出现在这里。</Empty>
          )}
        </>
      )}
      {tab === 'references' && (
        <div className="h5-list">
          {app.activeReferences.map((r, i) => (
            <a key={i} href={r.url} target="_blank" rel="noopener noreferrer">
              <div>
                <strong>{r.title}</strong>
                <p>{r.snippet}</p>
              </div>
              ↗
            </a>
          ))}
          {!app.activeReferences.length && (
            <Empty>当前对话还没有参考来源。</Empty>
          )}
        </div>
      )}
      {tab === 'process' && (
        <div className="h5-logs">
          {app.activeThinkingLog.map((log, i) => (
            <p key={i}>{log}</p>
          ))}
          {!app.activeThinkingLog.length && (
            <Empty>任务开始后可以在这里查看执行记录。</Empty>
          )}
        </div>
      )}
    </Sheet>
  );
}
