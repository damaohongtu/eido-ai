import React, { useEffect, useState } from 'react';
import { api, McpConfigFile } from '../services/api';

const EMPTY_CONFIG: McpConfigFile = { mcpServers: {} };

function formatConfig(config: McpConfigFile): string {
  return JSON.stringify(config, null, 2);
}

export default function McpSettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [value, setValue] = useState(formatConfig(EMPTY_CONFIG));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    setSaved(false);
    try {
      setValue(formatConfig(await api.getMcpConfigFile()));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (open) load(); }, [open]);

  const format = () => {
    setError('');
    try {
      const parsed = JSON.parse(value);
      setValue(JSON.stringify(parsed, null, 2));
    } catch (err) {
      setError(`JSON 格式错误：${err instanceof Error ? err.message : '无法解析'}`);
    }
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const parsed = JSON.parse(value) as McpConfigFile;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !parsed.mcpServers || typeof parsed.mcpServers !== 'object' || Array.isArray(parsed.mcpServers)) {
        throw new Error('根对象必须包含 mcpServers 对象');
      }
      const result = await api.replaceMcpConfigFile(parsed);
      setValue(formatConfig(result));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/30 p-6" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-gray-100 px-6 py-5">
          <div>
            <h2 className="text-lg font-black text-gray-900">MCP 配置文件</h2>
            <p className="mt-1 text-xs text-gray-500">配置仅对当前用户生效，格式与 Claude Code 的 mcpServers 配置一致。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100" aria-label="关闭">×</button>
        </header>

        <div className="min-h-0 flex-1 p-6">
          <textarea
            value={value}
            onChange={event => { setValue(event.target.value); setSaved(false); }}
            spellCheck={false}
            aria-label="MCP JSON 配置"
            className="h-[52vh] min-h-80 w-full resize-none rounded-xl border border-gray-200 bg-gray-950 p-4 font-mono text-sm leading-6 text-gray-100 outline-none focus:border-blue-400"
            disabled={loading}
          />
          <div className="mt-3 grid gap-2 text-xs text-gray-500 sm:grid-cols-2">
            <p><code>disabled: true</code> 表示保留配置但不加载该 MCP。</p>
            <p className="sm:text-right">已保存的 Header/环境变量显示为 <code>__EIDO_SECRET__</code>，保留即可继续使用原值。</p>
          </div>
          <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">Stdio 命令会在当前 Eido 运行环境中执行，请只配置可信的 MCP Server。</p>
          {error ? <div className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600">{error}</div> : null}
          {saved ? <div className="mt-3 rounded-xl bg-green-50 px-3 py-2 text-sm text-green-700">配置已保存，新的 Claude 会话将立即使用。</div> : null}
        </div>

        <footer className="flex justify-end gap-2 border-t border-gray-100 px-6 py-4">
          <button type="button" onClick={load} disabled={loading || saving} className="rounded-xl px-4 py-2 text-sm font-bold text-gray-500 hover:bg-gray-100 disabled:opacity-50">重新载入</button>
          <button type="button" onClick={format} disabled={loading || saving} className="rounded-xl px-4 py-2 text-sm font-bold text-gray-600 hover:bg-gray-100 disabled:opacity-50">格式化 JSON</button>
          <button type="button" onClick={save} disabled={loading || saving} className="rounded-xl bg-gray-800 px-5 py-2 text-sm font-bold text-white disabled:opacity-50">{saving ? '保存中…' : '保存配置'}</button>
        </footer>
      </section>
    </div>
  );
}
