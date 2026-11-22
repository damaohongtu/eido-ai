import React, { lazy, Suspense, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  useChatController,
  type ChatAreaProps,
} from '../hooks/useChatController';
import { getWorkspaceFileUrl } from '../services/api';
import {
  extractGeneratedFiles,
  normalizeWorkspacePath,
} from '../utils/chatFiles';
import {
  canPreviewInBrowser,
  canRenderAsBrowserImage,
  isSupportedProjectMaterial,
} from '../utils/projectFiles';
import { SUPPORTED_FILE_ACCEPT } from '../utils/supportedFiles';
import ModelSelector from '../components/ModelSelector';
import RuntimeModeSelector from '../components/RuntimeModeSelector';
const Mermaid = lazy(() => import('../components/Mermaid'));
import { Empty, ErrorMessage, Icon, Sheet } from './ui';

export default function Chat(props: ChatAreaProps) {
  const c = useChatController(props);
  const [settings, setSettings] = useState(false);
  const [skillPicker, setSkillPicker] = useState(false);
  const [skillQuery, setSkillQuery] = useState('');
  const { session, project } = props;
  if (!session) return <Empty>选择或新建一段对话，开始探索。</Empty>;

  const fileUrl = (path: string, download = false) =>
    getWorkspaceFileUrl(path, {
      sessionId: session.id,
      download,
      preview: !download,
      filename: path.split('/').pop(),
    });
  const appendSkill = (name: string) => {
    c.setInput(
      (value) =>
        `${value}${value && !value.endsWith(' ') ? ' ' : ''}\`@${name}\` `,
    );
    setSkillPicker(false);
    c.inputRef.current?.focus();
  };
  return (
    <section className="h5-chat">
      <div className="h5-chat-context">
        <button onClick={() => setSettings(true)}>
          <Icon name="settings" size={16} />
          <span>
            {c.activeSkill?.name ||
              (props.runtimeMode === 'qa' ? '问答模式' : 'Agent 模式')}
          </span>
        </button>
        <button onClick={props.onToggleReferences}>
          <Icon name="file" size={16} />
          资料与执行记录
        </button>
      </div>
      <div ref={c.scrollRef} className="h5-messages">
        {c.conversationMessages.map((m) => (
          <article key={m.id} className={`h5-message h5-message-${m.role}`}>
            {m.role === 'assistant' && (
              <div className="h5-message-author">
                <span className="h5-mini-logo">e</span>Eido
              </div>
            )}
            {m.role === 'assistant' &&
              (m.thinking || m.executionSteps?.length || m.workflowMermaid) && (
                <details className="h5-trace">
                  <summary>{m.thinking || '查看执行过程'}</summary>
                  {m.executionSteps?.map((step) => (
                    <p key={step.id}>
                      {step.status === 'completed' ? '✓' : '·'} {step.label}{' '}
                      <small>{step.description}</small>
                    </p>
                  ))}
                  {m.workflowMermaid && (
                    <Suspense fallback={<p>正在加载流程图…</p>}>
                      <Mermaid chart={m.workflowMermaid} />
                    </Suspense>
                  )}
                </details>
              )}
            <div className="h5-bubble markdown-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const path = href && normalizeWorkspacePath(href);
                    return (
                      <a
                        href={
                          path
                            ? fileUrl(path, !canPreviewInBrowser(path))
                            : href
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {children}
                      </a>
                    );
                  },
                  img: ({ src, alt }) => {
                    if (!src) return null;
                    if (/^(https?:|data:)/i.test(src))
                      return (
                        <img src={src} alt={alt || '图片'} loading="lazy" />
                      );
                    if (!canRenderAsBrowserImage(src))
                      return (
                        <a
                          href={fileUrl(src, !canPreviewInBrowser(src))}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {alt || '查看文件'}
                        </a>
                      );
                    return (
                      <a
                        href={fileUrl(src)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <img
                          src={fileUrl(src)}
                          alt={alt || '生成图片'}
                          loading="lazy"
                        />
                      </a>
                    );
                  },
                }}
              >
                {m.content || (c.activeSessionRunning ? '正在思考…' : '')}
              </ReactMarkdown>
            </div>
            {m.role === 'assistant' &&
              !c.activeSessionRunning &&
              m.id === c.conversationMessages.at(-1)?.id &&
              c.activeSkill?.actions && (
                <div className="h5-actions">
                  {c.activeSkill.actions.map((action) => (
                    <button
                      key={action.id}
                      onClick={() => props.onExecuteAction(action)}
                    >
                      {action.icon} {action.label}
                    </button>
                  ))}
                </div>
              )}
            {m.deliveryMode && (
              <small className="h5-muted">
                {m.deliveryStatus === 'failed'
                  ? '提交失败'
                  : m.deliveryMode === 'steer'
                    ? 'Steer · 已应用'
                    : '排队任务 · ' + (m.deliveryStatus || '')}
              </small>
            )}
            {m.role === 'assistant' &&
              extractGeneratedFiles(m).map((file) => (
                <div className="h5-file" key={file.path}>
                  <Icon name="file" />
                  <div>
                    <strong>{file.name}</strong>
                    <div className="h5-actions">
                      {canPreviewInBrowser(file.path) && (
                        <a
                          href={fileUrl(file.path)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          预览
                        </a>
                      )}
                      <a href={fileUrl(file.path, true)}>下载</a>
                      {props.onImportProjectFile &&
                        isSupportedProjectMaterial(
                          file.path,
                          file.name,
                          session.id,
                        ) && (
                          <button
                            disabled={
                              c.activeSessionRunning ||
                              Boolean(c.projectImportStatus[file.path])
                            }
                            onClick={() => c.importGeneratedFile(file)}
                          >
                            {c.projectImportStatus[file.path] === 'added'
                              ? '已加入'
                              : c.projectImportStatus[file.path] === 'adding'
                                ? '加入中…'
                                : '加入项目'}
                          </button>
                        )}
                    </div>
                  </div>
                </div>
              ))}
            {m.pendingConfirmation && (
              <div className="h5-card">
                <strong>{m.pendingConfirmation.label}</strong>
                <p>{m.pendingConfirmation.description}</p>
                <div className="h5-actions">
                  <button onClick={() => c.handleConfirmation(true, m.id)}>
                    允许
                  </button>
                  <button onClick={() => c.handleConfirmation(false, m.id)}>
                    拒绝
                  </button>
                </div>
              </div>
            )}
          </article>
        ))}
      </div>
      <form className="h5-composer" onSubmit={c.handleSubmit}>
        <ErrorMessage error={c.uploadError} />
        {c.queuedMessages.length > 0 && (
          <details className="h5-queue">
            <summary>排队消息 · {c.queuedMessages.length}</summary>
            {c.queuedMessages.map((m) => (
              <div key={m.id}>
                <p>{m.content}</p>
                <div className="h5-actions">
                  <button
                    type="button"
                    disabled={!c.steerAvailable}
                    onClick={() => c.submitFollowUp(m.content, 'steer', m)}
                  >
                    立即引导
                  </button>
                  <button type="button" onClick={() => c.editQueuedMessage(m)}>
                    编辑
                  </button>
                  <button
                    type="button"
                    onClick={() => c.deleteQueuedMessage(m)}
                  >
                    移除
                  </button>
                </div>
              </div>
            ))}
          </details>
        )}
        {c.attachments.length > 0 && (
          <div className="h5-attachments">
            {c.attachments.map((a, i) => (
              <button
                type="button"
                key={a.path}
                onClick={() => c.removeAttachment(i)}
                aria-label={`移除附件 ${a.name}`}
              >
                {a.name} ×
              </button>
            ))}
          </div>
        )}
        {c.mentionMenu.visible && c.filteredSkills.length > 0 && (
          <div className="h5-mentions" ref={c.mentionMenuRef}>
            {c.filteredSkills.map((s) => (
              <button
                type="button"
                key={s.id}
                onClick={() => c.insertMention(s)}
              >
                {s.icon || '✧'} {s.name}
              </button>
            ))}
          </div>
        )}
        <div className="h5-input-wrap" ref={c.inputContainerRef}>
          <textarea
            ref={c.inputRef}
            value={c.input}
            onChange={c.handleInputChange}
            rows={2}
            placeholder={
              c.activeSessionRunning
                ? '补充要求，继续推进…'
                : '有什么想一起完成的？'
            }
            aria-label="消息内容"
            onKeyDown={(e) => {
              if (
                e.key === 'Enter' &&
                (e.ctrlKey || e.metaKey) &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                void c.handleSubmit();
              }
            }}
          />
          <div className="h5-composer-toolbar">
            <div className="h5-actions">
              <button
                type="button"
                className="h5-icon-button"
                onClick={() => c.fileInputRef.current?.click()}
                disabled={c.uploading}
                aria-label="上传附件"
              >
                <Icon name="attach" />
              </button>
              <button
                type="button"
                onClick={() => setSkillPicker(true)}
                aria-label="选择技能"
              >
                @ 技能
              </button>
              {c.uploading && <small role="status">上传中…</small>}
            </div>
            <div className="h5-actions">
              {c.activeSessionCanStop && (
                <button
                  type="button"
                  onClick={c.handleStop}
                  className="h5-stop"
                >
                  停止
                </button>
              )}
              {c.activeSessionRunning && (
                <select
                  aria-label="后续消息处理方式"
                  value={c.effectiveDeliveryMode}
                  onChange={(e) =>
                    c.setDeliveryMode(e.target.value as 'queue' | 'steer')
                  }
                >
                  <option value="queue">排队</option>
                  <option value="steer" disabled={!c.steerAvailable}>
                    引导
                  </option>
                </select>
              )}
              <button
                className="h5-send"
                type="submit"
                disabled={
                  c.uploading || (!c.input.trim() && !c.attachments.length)
                }
                aria-label="发送消息"
              >
                <Icon name="send" size={21} />
              </button>
            </div>
          </div>
        </div>
        <input
          type="file"
          ref={c.fileInputRef}
          accept={SUPPORTED_FILE_ACCEPT}
          multiple
          hidden
          onChange={c.handleFileSelect}
        />
        <p className="h5-composer-note">
          {project ? `项目 · ${project.name}` : 'Eido 随行，灵感随时发生'}
        </p>
      </form>
      {settings && (
        <Sheet title="会话设置" onClose={() => setSettings(false)}>
          <div className="h5-form">
            <ModelSelector
              value={props.model}
              onChange={props.onModelChange}
              disabled={c.activeSessionRunning}
            />
            <RuntimeModeSelector
              value={props.runtimeMode}
              onChange={props.onRuntimeModeChange}
              disabled={c.activeSessionRunning}
            />
            <label>
              项目归属
              <select
                aria-label="项目归属"
                value={project?.id || ''}
                disabled={c.activeSessionRunning}
                onChange={(e) =>
                  void props.onMoveSession(e.target.value || null)
                }
              >
                <option value="">未归属</option>
                {props.projects
                  .filter((p) => !p.archived_at || p.id === project?.id)
                  .map((p) => (
                    <option
                      key={p.id}
                      value={p.id}
                      disabled={Boolean(p.archived_at)}
                    >
                      {p.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
        </Sheet>
      )}
      {skillPicker && (
        <Sheet title="选择技能" onClose={() => setSkillPicker(false)}>
          <input
            className="h5-search"
            type="search"
            placeholder="搜索技能"
            value={skillQuery}
            onChange={(e) => setSkillQuery(e.target.value)}
            aria-label="搜索技能"
          />
          <div className="h5-list">
            {props.skills
              .filter((s) => s.name.includes(skillQuery))
              .map((s) => (
                <button key={s.id} onClick={() => appendSkill(s.name)}>
                  <span>{s.icon || '✧'}</span>
                  <div>
                    <strong>{s.name}</strong>
                    <p>{s.description}</p>
                  </div>
                  <span>＋</span>
                </button>
              ))}
          </div>
        </Sheet>
      )}
    </section>
  );
}
