import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, McpServerStatus } from '../services/api';
import McpSettingsModal from './McpSettingsModal';

const statusMeta = {
  connected: { label: '已连接', dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
  disabled: { label: '已停用', dot: 'bg-gray-300', badge: 'bg-gray-100 text-gray-500' },
  error: { label: '连接异常', dot: 'bg-red-500', badge: 'bg-red-50 text-red-600' },
} as const;

export default function McpToolsView() {
  const [servers, setServers] = useState<McpServerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async (refresh = false) => {
    refresh ? setRefreshing(true) : setLoading(true);
    setError('');
    try {
      setServers(await api.getMcpServerStatuses(refresh));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载 MCP 状态失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      event.preventDefault();
      searchInputRef.current?.focus();
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, []);

  const summary = useMemo(() => ({
    connected: servers.filter(item => item.status === 'connected').length,
    tools: servers.reduce((total, item) => total + item.tool_count, 0),
  }), [servers]);

  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const filteredServers = useMemo(() => servers.flatMap(server => {
    if (!normalizedQuery) return [{ server, visibleTools: server.tools }];
    const serverMatches = [
      server.name,
      server.target,
      server.transport,
      statusMeta[server.status].label,
      server.error,
    ].some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery));
    const matchingTools = server.tools.filter(tool => [tool.name, tool.description]
      .some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery)));
    if (!serverMatches && matchingTools.length === 0) return [];
    return [{ server, visibleTools: serverMatches ? server.tools : matchingTools }];
  }), [normalizedQuery, servers]);

  const visibleToolCount = useMemo(
    () => filteredServers.reduce((total, item) => total + item.visibleTools.length, 0),
    [filteredServers]
  );

  const toggle = (id: string) => setExpanded(previous => {
    const next = new Set(previous);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50/50 p-6 lg:p-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-black tracking-tight text-gray-900">我的工具</h1>
            <p className="mt-1 text-sm font-medium text-gray-500">查看 MCP Server 的连接状态和可用工具</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => load(true)} disabled={refreshing} className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-bold text-gray-600 hover:bg-gray-50 disabled:opacity-50">{refreshing ? '检测中…' : '刷新状态'}</button>
            <button type="button" onClick={() => setSettingsOpen(true)} className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-bold text-white hover:bg-gray-900">统一配置</button>
          </div>
        </header>

        <div className="relative mb-6">
          <svg className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-4.35-4.35m1.35-5.65a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={searchInputRef}
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setSearchQuery('');
                event.currentTarget.blur();
              }
            }}
            placeholder="搜索 MCP、工具名称或描述"
            aria-label="搜索我的工具"
            className="h-10 w-full rounded-lg border border-gray-300 bg-white pl-10 pr-14 text-sm text-gray-800 outline-none transition focus:border-gray-500 focus:ring-2 focus:ring-gray-200"
          />
          {!searchQuery && <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 rounded border border-gray-200 px-1.5 py-0.5 text-[10px] font-bold text-gray-400">/</span>}
          {searchQuery && <button type="button" onClick={() => { setSearchQuery(''); searchInputRef.current?.focus(); }} className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" aria-label="清空工具搜索">×</button>}
        </div>

        {normalizedQuery && (
          <div className="mb-3 px-1 text-xs font-medium text-gray-400">
            找到 {filteredServers.length} 个 MCP Server、{visibleToolCount} 个工具
          </div>
        )}

        <div className="mb-6 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-4"><div className="text-xs font-bold text-gray-400">MCP SERVER</div><div className="mt-2 text-2xl font-black text-gray-900">{servers.length}</div></div>
          <div className="rounded-xl border border-gray-200 bg-white p-4"><div className="text-xs font-bold text-gray-400">已连接</div><div className="mt-2 text-2xl font-black text-emerald-600">{summary.connected}</div></div>
          <div className="rounded-xl border border-gray-200 bg-white p-4"><div className="text-xs font-bold text-gray-400">可用工具</div><div className="mt-2 text-2xl font-black text-gray-900">{summary.tools}</div></div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center rounded-xl border border-gray-200 bg-white py-24"><div className="text-center"><div className="mx-auto mb-3 h-9 w-9 animate-spin rounded-full border-2 border-gray-200 border-t-gray-700" /><p className="text-sm text-gray-500">正在检测 MCP 状态…</p></div></div>
        ) : error ? (
          <div className="rounded-xl border border-red-100 bg-red-50 p-8 text-center"><p className="text-sm text-red-600">{error}</p><button type="button" onClick={() => load(true)} className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-sm font-bold text-white">重试</button></div>
        ) : servers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white py-24 text-center"><div className="mb-3 text-4xl">🔌</div><h2 className="font-bold text-gray-800">尚未配置 MCP</h2><p className="mt-1 text-sm text-gray-500">通过右上角统一配置添加 MCP Server</p><button type="button" onClick={() => setSettingsOpen(true)} className="mt-5 rounded-lg bg-gray-800 px-4 py-2 text-sm font-bold text-white">打开配置</button></div>
        ) : filteredServers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white py-20 text-center"><div className="mb-3 text-3xl opacity-40">🔎</div><h2 className="font-bold text-gray-800">没有匹配的工具</h2><p className="mt-1 text-sm text-gray-500">尝试搜索 MCP 名称、工具名称或描述</p><button type="button" onClick={() => setSearchQuery('')} className="mt-4 text-sm font-bold text-gray-700 hover:underline">清空搜索</button></div>
        ) : (
          <div className="space-y-3">{filteredServers.map(({ server, visibleTools }) => {
            const meta = statusMeta[server.status];
            const isExpanded = normalizedQuery ? visibleTools.length > 0 : expanded.has(server.id);
            return <article key={server.id} className="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-lg">🔌</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><h2 className="font-black text-gray-900">{server.name}</h2><span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-bold ${meta.badge}`}><span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />{meta.label}</span><span className="rounded bg-gray-100 px-2 py-0.5 text-[10px] font-bold uppercase text-gray-500">{server.transport}</span></div>
                  <div className="mt-1 truncate font-mono text-xs text-gray-400" title={server.target}>{server.target}</div>
                  {server.error ? <p className="mt-1 text-xs text-red-500">{server.error}</p> : null}
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <div className="text-right"><div className="text-2xl font-black text-gray-900">{normalizedQuery && visibleTools.length !== server.tool_count ? `${visibleTools.length}/${server.tool_count}` : server.tool_count}</div><div className="text-[10px] font-bold text-gray-400">工具</div></div>
                  <button type="button" onClick={() => toggle(server.id)} disabled={server.tool_count === 0 || Boolean(normalizedQuery)} aria-expanded={isExpanded} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-bold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40">{normalizedQuery ? '已定位' : isExpanded ? '收起' : '查看工具'}</button>
                </div>
              </div>
              {isExpanded && visibleTools.length > 0 ? <div className="grid gap-2 border-t border-gray-100 bg-gray-50/70 p-4 sm:grid-cols-2 lg:grid-cols-3">{visibleTools.map(tool => <div key={tool.name} className="rounded-lg border border-gray-200 bg-white p-3"><div className="truncate font-mono text-xs font-bold text-gray-800" title={tool.name}>{tool.name}</div><p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{tool.description || '暂无描述'}</p></div>)}</div> : null}
            </article>;
          })}</div>
        )}
      </div>
      <McpSettingsModal open={settingsOpen} onClose={() => { setSettingsOpen(false); load(true); }} />
    </div>
  );
}
