import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

/** Shared by desktop, mobile and the browser extension. */
export default function ModelSelector({ value, onChange }: {
  value: string;
  onChange: (model: string) => void;
}) {
  const [catalog, setCatalog] = useState<{ default: string | null; models: string[] }>();
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    api.listModels().then(result => { if (active) setCatalog(result); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, []);
  return (
    <label className="flex flex-col gap-2 text-xs text-gray-500">
      Claude Code 模型
      <select aria-label="Claude Code 模型" value={value} onChange={e => onChange(e.target.value)}
        className="max-w-full rounded-lg border border-gray-200 bg-white p-2 text-sm text-gray-800">
        <option value="">服务端默认{catalog?.default ? ` (${catalog.default})` : ''}</option>
        {value && !catalog?.models.includes(value) && <option value={value}>{value}（未配置）</option>}
        {catalog?.models.map(model => <option key={model} value={model}>{model}</option>)}
      </select>
      {error && <span role="status">模型列表加载失败，请刷新后重试。</span>}
    </label>
  );
}
