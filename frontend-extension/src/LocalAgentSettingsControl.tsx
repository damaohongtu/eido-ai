import React, { useEffect, useState } from 'react';
import { Toast } from 'antd-mobile';
import type { LocalAgentSettings } from './localAgentRuntime';
import { saveLocalAgentSettings, testLocalOpenCode } from './localAgentRuntime';

const LocalAgentSettingsControl: React.FC<{ settings: LocalAgentSettings }> = ({ settings }) => {
  const [draft, setDraft] = useState(settings);
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => setDraft(settings), [settings]);

  const save = async () => {
    try {
      await saveLocalAgentSettings({
        ...draft,
        opencodeUrl: draft.opencodeUrl.trim().replace(/\/+$/, ''),
        username: draft.username.trim(),
      });
      Toast.show({ content: '执行模式已保存' });
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(message);
      Toast.show({ content: message });
    }
  };

  const test = async () => {
    setTesting(true);
    setStatus(null);
    try {
      const health = await testLocalOpenCode(draft);
      if (!health.healthy) throw new Error('OpenCode 服务未就绪');
      setStatus(`已连接 OpenCode ${health.version || ''}`.trim());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[15px] font-semibold text-gray-800">执行位置</div>
          <div className="text-xs text-gray-400">
            {draft.mode === 'local' ? '认证外的数据仅在插件与 OpenCode 间流转' : '使用现有 Eido 服务'}
          </div>
        </div>
        <div className="inline-flex shrink-0 rounded-full bg-gray-100 p-1">
          <button
            type="button"
            onClick={() => setDraft((value) => ({ ...value, mode: 'cloud' }))}
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              draft.mode === 'cloud' ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
            }`}
          >
            云端
          </button>
          <button
            type="button"
            onClick={() => setDraft((value) => ({ ...value, mode: 'local' }))}
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              draft.mode === 'local' ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
            }`}
          >
            本机
          </button>
        </div>
      </div>

      {draft.mode === 'local' ? (
        <div className="mt-4 space-y-3 border-t border-gray-100 pt-4">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-gray-600">OpenCode 地址</span>
            <input
              value={draft.opencodeUrl}
              onChange={(event) => setDraft((value) => ({ ...value, opencodeUrl: event.target.value }))}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
              spellCheck={false}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block min-w-0">
              <span className="mb-1 block text-xs font-semibold text-gray-600">用户名</span>
              <input
                value={draft.username}
                onChange={(event) => setDraft((value) => ({ ...value, username: event.target.value }))}
                className="w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
                autoComplete="username"
              />
            </label>
            <label className="block min-w-0">
              <span className="mb-1 block text-xs font-semibold text-gray-600">密码（可选）</span>
              <input
                type="password"
                value={draft.password}
                onChange={(event) => setDraft((value) => ({ ...value, password: event.target.value }))}
                className="w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
                autoComplete="current-password"
              />
            </label>
          </div>
          {status ? <div className="break-words text-xs leading-relaxed text-gray-500">{status}</div> : null}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={test}
              disabled={testing}
              className="flex-1 rounded-lg border border-gray-300 bg-white py-2 text-xs font-bold text-gray-700 disabled:opacity-50"
            >
              {testing ? '检测中...' : '测试连接'}
            </button>
            <button
              type="button"
              onClick={save}
              className="flex-1 rounded-lg bg-gray-700 py-2 text-xs font-bold text-white"
            >
              保存并切换
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={save}
          className="mt-4 w-full rounded-lg bg-gray-700 py-2 text-xs font-bold text-white"
        >
          保存并切换
        </button>
      )}
    </div>
  );
};

export default LocalAgentSettingsControl;
