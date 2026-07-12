import React, { useRef, useState } from 'react';
import { Popup, Toast } from 'antd-mobile';
import type { Skill } from '../shared';
import type { Attachment } from '../hooks/useChatSend';
import type { AgentRuntime } from '../runtime/types';

const ALLOWED_EXT = ['.md', '.pdf', '.csv', '.xls', '.xlsx'];

interface ComposerProps {
  sessionId: string;
  skills: Skill[];
  isTyping: boolean;
  onSend: (text: string, attachments: Attachment[]) => void;
  onStop: () => void;
  browserContextControl?: React.ReactNode;
  agentRuntime: AgentRuntime;
}

const Composer: React.FC<ComposerProps> = ({
  sessionId,
  skills,
  isTyping,
  onSend,
  onStop,
  browserContextControl,
  agentRuntime,
}) => {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const filteredSkills = skills.filter((s) =>
    s.name.toLowerCase().includes(mentionFilter.toLowerCase())
  );

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);
    const cursor = e.target.selectionStart || 0;
    const before = value.slice(0, cursor);
    const m = before.match(/@([\u4e00-\u9fa5\w-]*)$/);
    if (m) {
      setMentionFilter(m[1]);
      setMentionOpen(true);
    } else {
      setMentionOpen(false);
    }
  };

  const insertMention = (skill: Skill) => {
    const cur = input;
    const atPos = cur.lastIndexOf('@');
    const next = atPos === -1
      ? `${cur}\`@${skill.name}\` `
      : cur.slice(0, atPos) + `\`@${skill.name}\` ` + cur.slice(atPos + 1 + mentionFilter.length);
    setInput(next);
    setMentionOpen(false);
    setTimeout(() => taRef.current?.focus(), 0);
  };

  const handleFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    setUploading(true);
    try {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        const ext = f.name.toLowerCase().slice(f.name.lastIndexOf('.'));
        if (!ALLOWED_EXT.includes(ext)) {
          Toast.show({ content: `不支持的格式: ${f.name}` });
          continue;
        }
        const { path } = await agentRuntime.uploadChatFile(f, sessionId);
        setAttachments((prev) => [...prev, { name: f.name, path }]);
      }
    } catch (err) {
      Toast.show({ content: `上传失败: ${err}` });
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const submit = () => {
    if (isTyping) return;
    if (!input.trim() && attachments.length === 0) return;
    onSend(input, attachments);
    setInput('');
    setAttachments([]);
  };

  return (
    <div
      className="eido-mobile-composer border-t border-gray-200 bg-white px-3 pt-2"
      style={{ paddingBottom: 'calc(8px + var(--eido-safe-bottom))' }}
    >
      {attachments.length > 0 && (
        <div className="eido-mobile-attachments mb-2 flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-100 px-2.5 py-1 text-xs text-gray-700"
            >
              <span className="max-w-[120px] truncate">{a.name}</span>
              <button
                onClick={() => setAttachments((prev) => prev.filter((_, idx) => idx !== i))}
                className="text-gray-400"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="eido-mobile-composer-row flex items-end gap-2">
        <input
          ref={fileRef}
          type="file"
          accept=".md,.pdf,.csv,.xls,.xlsx"
          multiple
          className="hidden"
          onChange={handleFiles}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={isTyping || uploading}
          className="eido-mobile-icon-button mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-gray-500 active:bg-gray-100 disabled:opacity-40"
          aria-label="上传文件"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>
        {browserContextControl}

        <textarea
          ref={taRef}
          value={input}
          onChange={handleChange}
          rows={1}
          placeholder="发消息…（@ 可选技能）"
          className="eido-mobile-composer-input max-h-32 min-h-[40px] flex-1 resize-none rounded-2xl border border-gray-200 bg-gray-50 px-3.5 py-2 text-[15px] outline-none focus:border-gray-400"
          disabled={isTyping}
        />

        {isTyping ? (
          <button
            onClick={onStop}
            className="eido-mobile-icon-button mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-600"
            aria-label="停止"
          >
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="1" />
            </svg>
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!input.trim() && attachments.length === 0}
            className={`eido-mobile-icon-button mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors ${
              input.trim() || attachments.length > 0 ? 'bg-gray-700 text-white' : 'bg-gray-200 text-gray-400'
            }`}
            aria-label="发送"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        )}
      </div>

      <Popup
        visible={mentionOpen && filteredSkills.length > 0}
        onMaskClick={() => setMentionOpen(false)}
        bodyStyle={{ borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: '50vh', overflow: 'auto' }}
      >
        <div className="px-4 py-3">
          <div className="mb-2 text-[10px] font-black uppercase tracking-widest text-gray-400">
            激活智能技能
          </div>
          <div className="space-y-1 pb-2">
            {filteredSkills.map((s) => (
              <button
                key={s.id}
                onClick={() => insertMention(s)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left active:bg-gray-100"
              >
                <span className="text-xl">{s.icon}</span>
                <span className="text-sm font-bold text-gray-700">{s.name}</span>
              </button>
            ))}
          </div>
        </div>
      </Popup>
    </div>
  );
};

export default Composer;
