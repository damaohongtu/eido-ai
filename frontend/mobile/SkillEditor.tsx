import React, { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { skillCanManage, type Skill } from '../types';
import { Empty, ErrorMessage, Sheet, errorText } from './ui';

type FileNode = {
  name: string;
  path: string;
  type: 'file' | 'dir';
  children?: FileNode[];
};
function allFiles(nodes: FileNode[]): FileNode[] {
  return nodes.flatMap((n) =>
    n.type === 'file' ? [n] : allFiles(n.children || []),
  );
}

export function SkillFiles({ skill }: { skill: Skill }) {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [path, setPath] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef(0);
  const writable = skillCanManage(skill);
  const load = async () => {
    try {
      setFiles(allFiles(await api.getSkillFiles(skill.id)));
    } catch (e) {
      setError(errorText(e));
    }
  };
  useEffect(() => {
    void load();
    return () => {
      request.current += 1;
    };
  }, [skill.id]);
  const read = async (nextPath: string) => {
    const id = ++request.current;
    setError('');
    setBusy(true);
    try {
      const text = await api.readSkillFile(skill.id, nextPath);
      if (request.current === id) {
        setContent(text);
        setPath(nextPath);
      }
    } catch (e) {
      if (request.current === id) setError(errorText(e));
    } finally {
      if (request.current === id) setBusy(false);
    }
  };
  return (
    <div>
      <ErrorMessage error={error} />
      <div className="h5-section-title">
        <h3>技能文件</h3>
        {writable && (
          <button
            disabled={busy}
            onClick={() => {
              setPath('');
              setContent('');
            }}
          >
            新建文件 ＋
          </button>
        )}
      </div>
      <p className="h5-muted">
        支持文本文件浏览{writable ? '、编辑与创建' : ''}。
      </p>
      <div className="h5-list">
        {files.map((f) => (
          <button disabled={busy} key={f.path} onClick={() => read(f.path)}>
            <div>
              <strong>{f.path}</strong>
            </div>
            ›
          </button>
        ))}
      </div>
      {!files.length && <Empty>暂无技能文件。</Empty>}
      {path !== null && (
        <Sheet
          title={path || '新建技能文件'}
          onClose={() => {
            request.current += 1;
            setBusy(false);
            setPath(null);
          }}
        >
          <form
            className="h5-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError('');
              try {
                await api.writeSkillFile(skill.id, path, content);
                await load();
                setPath(null);
              } catch (err) {
                setError(errorText(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            <ErrorMessage error={error} />
            <label>
              文件路径
              <input
                aria-label="文件路径"
                value={path}
                required
                readOnly={!writable}
                onChange={(e) => setPath(e.target.value)}
              />
            </label>
            <label>
              文件内容
              <textarea
                aria-label="文件内容"
                rows={14}
                value={content}
                readOnly={!writable}
                onChange={(e) => setContent(e.target.value)}
                spellCheck={false}
              />
            </label>
            {writable && (
              <>
                <button className="h5-primary" disabled={busy || !path.trim()}>
                  保存文件
                </button>
                {files.some((f) => f.path === path) && (
                  <button
                    type="button"
                    className="h5-danger"
                    disabled={busy}
                    onClick={async () => {
                      if (!confirm(`删除文件「${path}」？`)) return;
                      setBusy(true);
                      try {
                        await api.deleteSkillFile(skill.id, path);
                        await load();
                        setPath(null);
                      } catch (err) {
                        setError(errorText(err));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    删除文件
                  </button>
                )}
              </>
            )}
          </form>
        </Sheet>
      )}
    </div>
  );
}

export default function SkillEditor({
  skill,
  onClose,
  onSaved,
}: {
  skill?: Skill;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(skill?.name || '');
  const [description, setDescription] = useState(skill?.description || '');
  const [content, setContent] = useState(skill?.detail || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Sheet title={skill ? '编辑技能' : '新建技能'} onClose={onClose}>
      <form
        className="h5-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError('');
          try {
            const body = { name: name.trim(), description, content };
            if (skill) await api.updateSkill(skill.id, body);
            else await api.createSkill(body);
            await onSaved();
            onClose();
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorMessage error={error} />
        <label>
          技能名称
          <input
            value={name}
            required
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          简介
          <textarea
            rows={3}
            value={description}
            required
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <label>
          技能说明（Markdown）
          <textarea
            value={content}
            required
            rows={12}
            onChange={(e) => setContent(e.target.value)}
          />
        </label>
        <button className="h5-primary" disabled={busy || !name.trim()}>
          {busy ? '保存中…' : '保存技能'}
        </button>
      </form>
    </Sheet>
  );
}
