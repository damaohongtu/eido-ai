import React from 'react';
import type { RuntimeMode } from '../types';

/** Shared by desktop, mobile and the browser extension. */
export default function RuntimeModeSelector({ value, onChange, disabled }: {
  value: RuntimeMode;
  onChange: (mode: RuntimeMode) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-w-0 items-center gap-2 text-xs font-semibold text-gray-500">
      <span className="shrink-0">模式</span>
      <select
        aria-label="Claude Code 执行模式"
        value={value}
        onChange={event => onChange(event.target.value as RuntimeMode)}
        disabled={disabled}
        title={value === 'qa' ? '单轮文本回答，不加载工具、技能或项目上下文' : '完整 Claude Code，支持工具、技能、项目与原生记忆'}
        className="min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-semibold text-gray-700 outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="qa">问答</option>
        <option value="agent">Agent</option>
      </select>
    </label>
  );
}
