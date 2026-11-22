import React, { useEffect, useState } from 'react';
import {
  api,
  type McpServerConfig,
  type McpServerPayload,
  type McpServerStatus,
} from '../services/api';
import McpSettingsModal from '../components/McpSettingsModal';
import { Empty, ErrorMessage, Sheet, errorText } from './ui';

function payloadFor(server: McpServerConfig): McpServerPayload {
  return {
    ...server.config,
    name: server.name,
    transport: server.transport,
    enabled: server.enabled,
  };
}

function stringMap(value: string, label: string): Record<string, string> {
  const parsed = JSON.parse(value || '{}');
  if (
    !parsed ||
    typeof parsed !== 'object' ||
    Array.isArray(parsed) ||
    Object.values(parsed).some((v) => typeof v !== 'string')
  )
    throw new Error(`${label}必须是键和值均为字符串的 JSON 对象`);
  return parsed;
}

function McpEditor({
  server,
  onClose,
  onSaved,
}: {
  server: McpServerConfig | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(server?.name || '');
  const [transport, setTransport] = useState<McpServerPayload['transport']>(
    server?.transport || 'http',
  );
  const [enabled, setEnabled] = useState(server?.enabled ?? true);
  const [url, setUrl] = useState(server?.config.url || '');
  const [command, setCommand] = useState(server?.config.command || '');
  const [args, setArgs] = useState(
    JSON.stringify(server?.config.args || [], null, 2),
  );
  const [mapping, setMapping] = useState({
    env: JSON.stringify(server?.config.env || {}, null, 2),
    headers: JSON.stringify(server?.config.headers || {}, null, 2),
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  return (
    <Sheet title={server ? '编辑 MCP' : '新增 MCP'} onClose={onClose}>
      <form
        className="h5-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setError('');
          setSaving(true);
          try {
            let body: McpServerPayload = {
              name: name.trim(),
              transport,
              enabled,
            };
            if (transport === 'stdio') {
              const parsedArgs = JSON.parse(args);
              if (
                !Array.isArray(parsedArgs) ||
                parsedArgs.some((arg) => typeof arg !== 'string')
              )
                throw new Error('启动参数必须是字符串组成的 JSON 数组');
              body = {
                ...body,
                command: command.trim(),
                args: parsedArgs,
                env: stringMap(mapping.env, '环境变量'),
              };
            } else
              body = {
                ...body,
                url: url.trim(),
                headers: stringMap(mapping.headers, '请求头'),
              };
            if (server) await api.updateMcpServer(server.id, body);
            else await api.createMcpServer(body);
            await onSaved();
            onClose();
          } catch (err) {
            setError(errorText(err));
          } finally {
            setSaving(false);
          }
        }}
      >
        <ErrorMessage error={error} />
        <label>
          服务名称
          <input
            required
            maxLength={64}
            pattern="[A-Za-z0-9][A-Za-z0-9_\-]{0,63}"
            title="字母、数字、下划线和连字符"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：research-tools"
          />
        </label>
        <label>
          连接方式
          <select
            value={transport}
            onChange={(e) =>
              setTransport(e.target.value as McpServerPayload['transport'])
            }
          >
            <option value="http">HTTP</option>
            <option value="sse">SSE</option>
            <option value="stdio">Stdio</option>
          </select>
        </label>
        {transport === 'stdio' ? (
          <>
            <label>
              启动命令
              <input
                required
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="例如：uvx"
              />
            </label>
            <label>
              启动参数（JSON 数组）
              <textarea
                rows={3}
                value={args}
                onChange={(e) => setArgs(e.target.value)}
                spellCheck={false}
              />
            </label>
            <label>
              环境变量（JSON 对象）
              <textarea
                rows={4}
                value={mapping.env}
                onChange={(e) =>
                  setMapping((previous) => ({
                    ...previous,
                    env: e.target.value,
                  }))
                }
                spellCheck={false}
              />
            </label>
          </>
        ) : (
          <>
            <label>
              服务地址
              <input
                type="url"
                required
                pattern="https?://.+"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com/mcp"
              />
            </label>
            <label>
              请求头（JSON 对象）
              <textarea
                rows={4}
                value={mapping.headers}
                onChange={(e) =>
                  setMapping((previous) => ({
                    ...previous,
                    headers: e.target.value,
                  }))
                }
                spellCheck={false}
              />
            </label>
          </>
        )}
        <p className="h5-muted">
          已保存的密钥显示为 __EIDO_SECRET__，保留该值即可继续使用原密钥。
        </p>
        <label>
          服务状态
          <select
            value={enabled ? 'enabled' : 'disabled'}
            onChange={(e) => setEnabled(e.target.value === 'enabled')}
          >
            <option value="enabled">启用</option>
            <option value="disabled">停用</option>
          </select>
        </label>
        <button className="h5-primary" disabled={saving}>
          {saving ? '保存中…' : '保存 MCP'}
        </button>
      </form>
    </Sheet>
  );
}

export default function McpManager() {
  const [servers, setServers] = useState<McpServerConfig[]>([]);
  const [statuses, setStatuses] = useState<McpServerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<McpServerConfig | null | undefined>(
    undefined,
  );
  const [config, setConfig] = useState(false);
  const load = async (refresh = false) => {
    setLoading(true);
    setError('');
    try {
      const [configs, states] = await Promise.all([
        api.listMcpServers(),
        api.getMcpServerStatuses(refresh),
      ]);
      setServers(configs);
      setStatuses(states);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const mutate = async (id: string, action: () => Promise<unknown>) => {
    setBusy(id);
    setError('');
    try {
      await action();
      await load(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="h5-page">
      <div className="h5-eyebrow">MCP 管理</div>
      <h1>我的工具</h1>
      <p className="h5-intro">管理 MCP 服务、连接状态和可用工具。</p>
      <div className="h5-actions">
        <button className="h5-primary" onClick={() => setEditing(null)}>
          新增 MCP ＋
        </button>
        <button className="h5-secondary" onClick={() => setConfig(true)}>
          统一配置
        </button>
        <button disabled={loading} onClick={() => load(true)}>
          刷新状态
        </button>
      </div>
      <ErrorMessage error={error} />
      <input
        className="h5-search"
        type="search"
        placeholder="搜索服务或工具"
        aria-label="搜索工具"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {loading && <p role="status">正在检测连接…</p>}
      {servers
        .map((server) => ({
          server,
          status: statuses.find((s) => s.id === server.id),
        }))
        .filter(({ server, status }) =>
          `${server.name} ${(status?.tools || []).map((t) => t.name + t.description).join(' ')}`
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .map(({ server, status }) => (
          <article
            className="h5-card"
            key={server.id}
            aria-label={`MCP 服务 ${server.name}`}
          >
            <div className="h5-section-title">
              <h3>{server.name}</h3>
              <button
                role="switch"
                aria-label={`启用 MCP ${server.name}`}
                aria-checked={server.enabled}
                disabled={busy === server.id || loading}
                onClick={() =>
                  mutate(server.id, () =>
                    api.updateMcpServer(server.id, {
                      ...payloadFor(server),
                      enabled: !server.enabled,
                    }),
                  )
                }
              >
                {server.enabled ? '已启用 ●' : '已停用 ○'}
              </button>
            </div>
            <small>
              {server.transport.toUpperCase()} ·{' '}
              {server.enabled
                ? {
                    connected: '已连接',
                    error: '连接异常',
                    disabled: '已停用',
                  }[status?.status] || '状态未知'
                : '已停用'}{' '}
              · {status?.tool_count || 0} 个工具
            </small>
            {status?.error && <ErrorMessage error={status.error} />}
            <div className="h5-actions">
              <button
                disabled={busy === server.id || loading}
                onClick={() => setEditing(server)}
              >
                编辑
              </button>
              <button
                disabled={busy === server.id || loading}
                onClick={() => {
                  if (confirm(`删除 MCP「${server.name}」？`))
                    void mutate(server.id, () =>
                      api.deleteMcpServer(server.id),
                    );
                }}
              >
                删除
              </button>
            </div>
            {Boolean(status?.tools.length) && (
              <details>
                <summary>查看工具</summary>
                {status.tools.map((t) => (
                  <div className="h5-tool" key={t.name}>
                    <strong>{t.name}</strong>
                    <p>{t.description}</p>
                  </div>
                ))}
              </details>
            )}
          </article>
        ))}
      {!loading && !servers.length && (
        <Empty>还没有连接工具，添加第一个 MCP 服务。</Empty>
      )}
      {editing !== undefined && (
        <McpEditor
          server={editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => load(true)}
        />
      )}
      {config && (
        <McpSettingsModal
          open
          onClose={() => {
            setConfig(false);
            void load(true);
          }}
        />
      )}
    </div>
  );
}
