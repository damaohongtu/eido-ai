import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

export interface ModelOption {
  id: string;
  label: string;
  model: string;
  description: string;
}

/** Shared by desktop, mobile and the browser extension. */
export default function ModelSelector({ value, onChange, disabled }: {
  value: string;
  onChange: (model: string) => void;
  disabled?: boolean;
}) {
  const [catalog, setCatalog] = useState<{ default: string; models: ModelOption[] }>();
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    api.listModels().then(result => { if (active) setCatalog(result); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, []);
  return (
    <label className="flex min-w-0 items-center gap-2 text-xs font-semibold text-gray-500">
      <span className="shrink-0">模型</span>
      <select aria-label="Claude Code 模型" value={value} onChange={e => onChange(e.target.value)}
        disabled={disabled}
        className="min-w-0 max-w-52 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-semibold text-gray-700 outline-none disabled:cursor-not-allowed disabled:opacity-50">
        <option value="">默认{catalog?.default ? ` (${catalog.models.find(item => item.id === catalog.default)?.label || catalog.default})` : ''}</option>
        {value && !catalog?.models.some(item => item.id === value) && <option value={value}>{value}（未配置）</option>}
        {catalog?.models.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      {error && <span role="status" className="text-red-500">加载失败</span>}
    </label>
  );
}
