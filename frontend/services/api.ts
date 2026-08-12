import { Message, Skill, ExecutionStep, Tool, Agent, Reference, ScheduledTask, ChatSession, Project, ProjectFile } from "../types";
import { BACKEND_URL, INITIAL_CHAT_STATE } from "../constants";

/** 工作区文件 URL，支持预览或下载；传入 sessionId 时只允许访问该会话工作区。 */
export function getWorkspaceFileUrl(
  path: string,
  options?: { download?: boolean; preview?: boolean; filename?: string; sessionId?: string }
): string {
  const query = new URLSearchParams({ path });
  if (options?.download) {
    query.set('download', 'true');
  } else if (options?.preview) {
    query.set('preview', 'true');
  }
  if (options?.filename) {
    query.set('filename', options.filename);
  }
  if (options?.sessionId) {
    query.set('session_id', options.sessionId);
  }
  return `${BACKEND_URL}/api/v1/workspace/file?${query.toString()}`;
}

/** 项目共享资料 URL；主动内容只有显式 preview 时才以内联安全策略打开。 */
export function getProjectFileUrl(
  projectId: string,
  fileId: string,
  options?: { download?: boolean; preview?: boolean }
): string {
  const query = new URLSearchParams();
  if (options?.download) {
    query.set('download', 'true');
  } else if (options?.preview) {
    query.set('preview', 'true');
  }
  const queryString = query.toString();
  const suffix = queryString ? `?${queryString}` : '';
  return `${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}${suffix}`;
}

export interface WorkspaceFileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: WorkspaceFileNode[];
}

export interface PersistedSession {
  id: string;
  user_id: string;
  title: string;
  skill_id: string | null;
  /** 旧服务端响应可能没有该字段。 */
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersistedMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  extra: Record<string, any>;
  created_at: string;
}

export interface PersistedSessionDetail extends PersistedSession {
  messages: PersistedMessage[];
}

export interface NavigationSearchResult {
  projects: Project[];
  sessions: (PersistedSession & { match_snippet?: string })[];
}

export interface McpServerConfig {
  id: string;
  name: string;
  transport: 'stdio' | 'http' | 'sse';
  config: {
    command?: string;
    args?: string[];
    env?: Record<string, string>;
    url?: string;
    headers?: Record<string, string>;
  };
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface McpServerPayload {
  name: string;
  transport: 'stdio' | 'http' | 'sse';
  enabled: boolean;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
}

export interface McpConfigFile {
  mcpServers: Record<string, {
    type: 'stdio' | 'http' | 'sse';
    disabled?: boolean;
    command?: string;
    args?: string[];
    env?: Record<string, string>;
    url?: string;
    headers?: Record<string, string>;
  }>;
}

export interface McpServerStatus {
  id: string;
  name: string;
  transport: 'stdio' | 'http' | 'sse';
  enabled: boolean;
  target: string;
  updated_at: string;
  status: 'connected' | 'disabled' | 'error';
  tool_count: number;
  tools: { name: string; description: string }[];
  error?: string | null;
}

/** 后端 PersistedSession + messages → 前端 ChatSession */
export function hydrateSession(detail: PersistedSessionDetail): ChatSession {
  const messages: Message[] = detail.messages.length > 0 ? detail.messages.map(m => ({
    id: m.id,
    role: m.role,
    content: m.content,
    timestamp: Date.parse(m.created_at) || Date.now(),
    thinking: m.extra?.thinking,
    thinkingLog: m.extra?.thinkingLog,
    executionSteps: m.extra?.executionSteps,
    workflowMermaid: m.extra?.workflowMermaid,
    pendingConfirmation: m.extra?.pendingConfirmation,
    references: m.extra?.references,
    deliveryMode: m.extra?.deliveryMode,
    deliveryStatus: m.extra?.deliveryStatus,
    queuePosition: m.extra?.queuePosition,
    streaming: m.extra?.streaming === true,
  })) : INITIAL_CHAT_STATE.map((m, i) => ({
    ...m,
    id: `${detail.id}-init-${i}`,
    timestamp: Date.parse(detail.created_at) || Date.now(),
  }));
  return {
    id: detail.id,
    title: detail.title,
    projectId: detail.project_id ?? null,
    skillId: detail.skill_id || undefined,
    messages,
    updatedAt: Date.parse(detail.updated_at) || Date.now(),
  };
}

export function summaryToSession(s: PersistedSession): ChatSession {
  return {
    id: s.id,
    title: s.title,
    projectId: s.project_id ?? null,
    skillId: s.skill_id || undefined,
    messages: [],
    updatedAt: Date.parse(s.updated_at) || Date.now(),
  };
}

export class ApiService {
  private async _fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const response = await fetch(input, { ...init, credentials: 'include' });
    if (response.status === 401) {
      const loginUrl = `${BACKEND_URL}/api/v1/auth/login`;
      const isChromeExtension =
        typeof window !== 'undefined' &&
        window.location.protocol === 'chrome-extension:';
      if (isChromeExtension) {
        window.dispatchEvent(new CustomEvent('eido-auth-required', { detail: { loginUrl } }));
        throw new Error('未登录，请在浏览器标签页完成登录后重试');
      }
      window.location.href = loginUrl;
      throw new Error('未登录，正在跳转登录页');
    }
    return response;
  }

  async searchNavigation(query: string, limit = 20): Promise<NavigationSearchResult> {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    const response = await this._fetch(`${BACKEND_URL}/api/v1/search?${params.toString()}`);
    if (!response.ok) throw new Error(`搜索失败: ${response.status}`);
    return response.json();
  }

  async listMcpServers(): Promise<McpServerConfig[]> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/servers`);
    if (!response.ok) throw new Error(`获取 MCP 配置失败: ${response.status}`);
    return response.json();
  }

  async getMcpServerStatuses(refresh = false): Promise<McpServerStatus[]> {
    const params = refresh ? '?refresh=true' : '';
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/status${params}`);
    if (!response.ok) throw new Error(`获取 MCP 状态失败: ${response.status}`);
    return response.json();
  }

  async getMcpConfigFile(): Promise<McpConfigFile> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/config`);
    if (!response.ok) throw new Error(`获取 MCP 配置失败: ${response.status}`);
    return response.json();
  }

  async replaceMcpConfigFile(body: McpConfigFile): Promise<McpConfigFile> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      const detail = Array.isArray(error.detail)
        ? error.detail.map((item: any) => item.msg || String(item)).join('；')
        : error.detail;
      throw new Error(detail || `保存 MCP 配置失败: ${response.status}`);
    }
    return response.json();
  }

  async createMcpServer(body: McpServerPayload): Promise<McpServerConfig> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/servers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `创建 MCP 配置失败: ${response.status}`);
    }
    return response.json();
  }

  async updateMcpServer(id: string, body: McpServerPayload): Promise<McpServerConfig> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/servers/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `更新 MCP 配置失败: ${response.status}`);
    }
    return response.json();
  }

  async deleteMcpServer(id: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/mcp/servers/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    if (!response.ok && response.status !== 404) throw new Error(`删除 MCP 配置失败: ${response.status}`);
  }

  async checkAuth(): Promise<{ user_id: string; username: string } | null> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
        credentials: 'include',
      });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  }

  /**
   * 沙箱预热：登录成功后调用，提前拉起当前用户的 sandbox 容器，
   * 把首条消息的冷启动开销摊到登录后的等待期。
   *
   * - 单租户/local 模式：后端返回 ready=true，几乎瞬时完成；
   * - sandbox 模式：gateway 等待 user 容器 /health 就绪，可能耗时数秒。
   *
   * 该接口失败不应阻塞登录流；调用方静默吞错即可。
   */
  async warmupSandbox(): Promise<{ ready: boolean; container?: string } | null> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/sandbox/warmup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) return null;
      return await response.json();
    } catch (e) {
      console.warn('warmupSandbox failed (silently ignored)', e);
      return null;
    }
  }

  /**
   * 获取工具列表
   */
  async getTools(params?: {
    skip?: number;
    limit?: number;
    category?: string;
    search?: string;
    is_system?: boolean;
  }): Promise<{ items: Tool[]; total: number }> {
    const queryParams = new URLSearchParams();
    
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString());
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString());
    if (params?.category) queryParams.append('category', params.category);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.is_system !== undefined) queryParams.append('is_system', params.is_system.toString());

    const url = `${BACKEND_URL}/api/v1/tools/?${queryParams.toString()}`;
    
    try {
      const response = await this._fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取工具列表失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取工具列表失败:', error);
      throw error;
    }
  }

  /**
   * 获取单个工具详情
   */
  async getTool(toolId: string): Promise<Tool> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/tools/${toolId}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取工具详情失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取工具详情失败:', error);
      throw error;
    }
  }

  /**
   * 获取Agent列表
   */
  async getAgents(params?: {
    skip?: number;
    limit?: number;
    category?: string;
    search?: string;
    is_system?: boolean;
  }): Promise<{ items: Agent[]; total: number }> {
    const queryParams = new URLSearchParams();
    
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString());
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString());
    if (params?.category) queryParams.append('category', params.category);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.is_system !== undefined) queryParams.append('is_system', params.is_system.toString());

    const url = `${BACKEND_URL}/api/v1/agents/?${queryParams.toString()}`;
    
    try {
      const response = await this._fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取Agent列表失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取Agent列表失败:', error);
      throw error;
    }
  }

  /**
   * 获取单个Agent详情
   */
  async getAgent(agentId: string): Promise<Agent> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/agents/${agentId}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取Agent详情失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取Agent详情失败:', error);
      throw error;
    }
  }

  /**
   * 获取Skills列表
   */
  async getSkills(params?: {
    skip?: number;
    limit?: number;
    search?: string;
    is_system?: boolean;
  }): Promise<{ items: Skill[]; total: number }> {
    const queryParams = new URLSearchParams();
    
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString());
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString());
    if (params?.search) queryParams.append('search', params.search);
    if (params?.is_system !== undefined) queryParams.append('is_system', params.is_system.toString());

    const url = `${BACKEND_URL}/api/v1/skills/?${queryParams.toString()}`;
    
    try {
      const response = await this._fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取Skills列表失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取Skills列表失败:', error);
      throw error;
    }
  }

  /**
   * 获取单个Skill详情（包含关联的工具和Agent）
   */
  async getSkill(skillId: string): Promise<Skill> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`获取Skill详情失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('获取Skill详情失败:', error);
      throw error;
    }
  }

  /**
   * 上传技能文件（.zip、.md、.skill，最大 10 MB）
   */
  async uploadSkill(file: File): Promise<Skill> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `上传失败: ${response.status}`);
    }

    return await response.json();
  }

  /**
   * 创建新Skill
   */
  async createSkill(skillData: {
    name: string;
    description: string;
    content: string;
    icon?: string;
  }): Promise<Skill> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(skillData),
      });

      if (!response.ok) {
        throw new Error(`创建Skill失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('创建Skill失败:', error);
      throw error;
    }
  }

  /**
   * 更新Skill
   */
  async updateSkill(skillId: string, skillData: Partial<{
    name: string;
    description: string;
    content: string;
    icon: string;
  }>): Promise<Skill> {
    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(skillData),
      });

      if (!response.ok) {
        throw new Error(`更新Skill失败: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('更新Skill失败:', error);
      throw error;
    }
  }

  /**
   * 获取技能文件列表
   */
  async getSkillFiles(skillId: string): Promise<any[]> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}/files`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`获取文件列表失败: ${response.status}`);
    return response.json();
  }

  /**
   * 读取技能文件内容
   */
  async readSkillFile(skillId: string, path: string): Promise<string> {
    const encodedPath = encodeURIComponent(path);
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}/files/read?path=${encodedPath}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`读取文件失败: ${response.status}`);
    const data = await response.json();
    return data.content;
  }

  /**
   * 写入技能文件
   */
  async writeSkillFile(skillId: string, path: string, content: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}/files/write`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    if (!response.ok) throw new Error(`写入文件失败: ${response.status}`);
  }

  /**
   * 删除技能文件
   */
  async deleteSkillFile(skillId: string, path: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}/files/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    if (!response.ok) throw new Error(`删除文件失败: ${response.status}`);
  }

  /**
   * 在技能目录下创建子目录
   */
  async mkdirSkillFile(skillId: string, path: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}/files/mkdir`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    if (!response.ok) throw new Error(`创建目录失败: ${response.status}`);
  }

  /**
   * 删除Skill
   */
  async deleteSkill(skillId: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      const detail =
        typeof err.detail === 'string'
          ? err.detail
          : Array.isArray(err.detail)
            ? err.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ')
            : `删除失败: ${response.status}`;
      throw new Error(detail || `删除失败: ${response.status}`);
    }
  }

  /**
   * 上传聊天附件到指定会话工作区，返回工作区内的绝对路径
   */
  async uploadChatFile(file: File, sessionId: string): Promise<{ path: string; name: string }> {
    if (!sessionId) {
      throw new Error('uploadChatFile 需要 sessionId');
    }
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);
    const response = await this._fetch(`${BACKEND_URL}/api/v1/chat/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `上传失败: ${response.status}`);
    }
    return response.json();
  }

  // -------------------- 项目 -------------------- //

  async listProjects(options?: { include_archived?: boolean }): Promise<Project[]> {
    const query = new URLSearchParams();
    if (options?.include_archived) query.set('include_archived', 'true');
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/projects/${query.toString() ? `?${query.toString()}` : ''}`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' } },
    );
    if (!response.ok) throw new Error(`获取项目列表失败: ${response.status}`);
    const data = await response.json();
    // 兼容直接数组和通用 { items } 列表响应。
    return Array.isArray(data) ? data : (data.items || []);
  }

  async getProject(projectId: string): Promise<Project> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`获取项目失败: ${response.status}`);
    return response.json();
  }

  async createProject(body: { name: string; description?: string; instructions?: string }): Promise<Project> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/projects/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `创建项目失败: ${response.status}`);
    }
    return response.json();
  }

  async patchProject(
    projectId: string,
    body: Partial<Pick<Project, 'name' | 'description' | 'instructions'>> & { archived?: boolean },
  ): Promise<Project> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `更新项目失败: ${response.status}`);
    }
    return response.json();
  }

  async deleteProject(projectId: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}`, {
      method: 'DELETE',
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`删除项目失败: ${response.status}`);
    }
  }

  async listProjectFiles(projectId: string): Promise<ProjectFile[]> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}/files`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' } },
    );
    if (!response.ok) throw new Error(`获取项目资料失败: ${response.status}`);
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items || data.files || []);
  }

  async uploadProjectFile(projectId: string, file: File): Promise<ProjectFile> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}/files`,
      { method: 'POST', body: formData },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `上传项目资料失败: ${response.status}`);
    }
    return response.json();
  }

  async deleteProjectFile(projectId: string, fileId: string): Promise<void> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
      { method: 'DELETE' },
    );
    if (!response.ok && response.status !== 404) {
      throw new Error(`删除项目资料失败: ${response.status}`);
    }
  }

  async importProjectFile(
    projectId: string,
    body: { session_id: string; path: string; display_name?: string },
  ): Promise<ProjectFile> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/projects/${encodeURIComponent(projectId)}/files/import`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `保存到项目资料失败: ${response.status}`);
    }
    return response.json();
  }

  // -------------------- 会话持久化 -------------------- //

  async listSessions(options?: { project_id?: string; unassigned?: boolean }): Promise<PersistedSession[]> {
    const query = new URLSearchParams();
    if (options?.project_id) query.set('project_id', options.project_id);
    if (options?.unassigned) query.set('unassigned', 'true');
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/${query.toString() ? `?${query.toString()}` : ''}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`获取会话列表失败: ${response.status}`);
    return response.json();
  }

  async getSession(sessionId: string): Promise<PersistedSessionDetail> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`获取会话详情失败: ${response.status}`);
    return response.json();
  }

  async createSession(body: { title?: string; skill_id?: string | null; project_id?: string | null }): Promise<PersistedSession> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`创建会话失败: ${response.status}`);
    return response.json();
  }

  async patchSession(
    sessionId: string,
    body: { title?: string; skill_id?: string | null; project_id?: string | null }
  ): Promise<PersistedSession> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`更新会话失败: ${response.status}`);
    return response.json();
  }

  async deleteSession(sessionId: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`删除会话失败: ${response.status}`);
    }
  }

  async listWorkspaceFiles(sessionId: string): Promise<WorkspaceFileNode[]> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/workspace/files?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' } },
    );
    if (!response.ok) throw new Error(`获取文件列表失败: ${response.status}`);
    const data = await response.json();
    return data.files;
  }

  async deleteWorkspaceFile(sessionId: string, path: string): Promise<void> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/workspace/file?session_id=${encodeURIComponent(sessionId)}&path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    );
    if (!response.ok && response.status !== 404) {
      throw new Error(`删除文件失败: ${response.status}`);
    }
  }

  async appendMessage(
    sessionId: string,
    body: {
      id?: string;
      role: 'user' | 'assistant' | 'system';
      content: string;
      extra?: Record<string, any>;
    }
  ): Promise<PersistedMessage> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `追加消息失败: ${response.status}`);
    }
    return response.json();
  }

  /**
   * 统一聊天执行入口：由后端 claude_agent_sdk 自动识别并执行技能，流式返回。
   *
   * sessionId  必填，agent cwd 将切到该会话工作区
   * skillHint  流水线模式下指定本步骤聚焦的技能 ID，拼入 context 传给后端。
   * signal    用于中断请求，传入 AbortController.signal 可实现用户点击停止。
   */
  async streamChat(
    messages: Message[],
    onChunk: (
      text: string,
      thinking: string,
      steps?: ExecutionStep[],
      pendingConfirmation?: any,
      references?: Reference[],
      workflowMermaid?: string
    ) => void,
    sessionId: string,
    assistantMessageId: string,
    context?: string,
    skillHint?: string,
    signal?: AbortSignal,
    harness?: string
  ) {
    let fullText = "";
    let fullThinking = "正在分析请求，自动规划执行...";
    let steps: ExecutionStep[] = [];
    let currentReferences: Reference[] = [];
    let workflowMermaid: string | undefined;

    const effectiveContext = skillHint
      ? `[本步骤请聚焦使用技能: ${skillHint}]\n\n${context || ''}`.trim()
      : (context || undefined);

    try {
      const response = await this._fetch(`${BACKEND_URL}/api/v1/chat/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: messages.map(m => ({ id: m.id, role: m.role, content: m.content })),
          context: effectiveContext,
          session_id: sessionId,
          assistant_message_id: assistantMessageId,
          harness: harness || undefined,
        }),
        signal,
      });

      if (!response.ok) throw new Error('请求失败');

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (reader) {
        // 网络 chunk 不保证落在 SSE 行边界；保留最后一段，避免半条 JSON 被丢弃。
        let sseBuffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (value) sseBuffer += decoder.decode(value, { stream: !done });
          if (done) {
            sseBuffer += decoder.decode();
            // EOF 前即使服务端没有补换行，也把最后一条 data 事件交给解析器。
            if (sseBuffer.trim()) sseBuffer += '\n';
          }
          const lines = sseBuffer.split(/\r?\n/);
          sseBuffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.replace('data: ', '').trim();
              if (dataStr === '[DONE]') {
                fullThinking = "✓ 执行完成";
                onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                break;
              }

              try {
                const data = JSON.parse(dataStr);

                switch (data.type) {
                  case 'workflow_start':
                    fullThinking = `正在执行: ${data.skill_name}`;
                    onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    break;

                  case 'workflow_graph':
                    if (data.data?.format === 'mermaid' && data.data?.content) {
                      workflowMermaid = data.data.content;
                      onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    }
                    break;

                  case 'thinking':
                    fullThinking = data.content;
                    onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    break;

                  case 'steps':
                    steps = data.data.capabilities.map((cap: any, i: number) => ({
                      id: `step-${i}`,
                      label: cap.name,
                      type: cap.type as 'tool' | 'agent',
                      status: 'pending' as 'pending',
                      description: '等待执行...'
                    }));
                    onChunk(fullText, fullThinking, [...steps], undefined, currentReferences, workflowMermaid);
                    break;

                  case 'step_update': {
                    const currentStep = data.data.current_step - 1;
                    if (steps[currentStep]) {
                      steps[currentStep].status = 'running';
                      steps[currentStep].description = data.data.thinking || '执行中...';
                    }
                    fullThinking = data.data.thinking || fullThinking;
                    if (data.data.references?.length > 0) {
                      currentReferences = data.data.references;
                    }
                    onChunk(fullText, fullThinking, [...steps], undefined, currentReferences, workflowMermaid);
                    for (let i = 0; i < currentStep; i++) {
                      if (steps[i].status !== 'completed') steps[i].status = 'completed';
                    }
                    break;
                  }

                  case 'content':
                    fullText += data.content;
                    onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    break;

                  case 'workflow_complete':
                    steps.forEach(step => { step.status = 'completed'; });
                    if (data.data?.references?.length > 0) {
                      currentReferences = data.data.references;
                    }
                    fullThinking = "✓ 执行完成";
                    onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    break;

                  case 'error':
                    fullThinking = `✗ 错误: ${data.message}`;
                    fullText += `\n\n**错误**: ${data.message}`;
                    onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
                    break;
                }
              } catch (e) {
                console.error("Error parsing SSE data", e);
              }
            }
          }
          if (done) break;
        }
      }

    } catch (error) {
      const isAborted = error instanceof Error && error.name === 'AbortError';
      if (isAborted) {
        fullThinking = "已中断";
        fullText = fullText ? fullText + "\n\n*（用户已中断执行）*" : "*（用户已中断执行）*";
      } else {
        console.error("执行失败:", error);
        fullThinking = "✗ 执行失败";
        fullText = fullText ? fullText + `\n\n**错误**: ${error}` : `执行出错: ${error}`;
      }
      onChunk(fullText, fullThinking, steps, undefined, currentReferences, workflowMermaid);
      if (isAborted) throw error;
    }
  }

  async controlChat(body: {
    mode: 'queue' | 'steer';
    session_id: string;
    message: { id: string; role: 'user'; content: string };
    assistant_message_id: string;
    context?: string;
    harness?: string;
  }): Promise<{
    ok: boolean;
    mode: 'queue' | 'steer';
    status: 'queued' | 'applied';
    position?: number;
  }> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/chat/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `提交消息失败: ${response.status}`);
    }
    return response.json();
  }

  async getChatQueue(sessionId: string): Promise<{
    active: boolean;
    steer_available: boolean;
    count: number;
    items: {
      message_id: string;
      content: string;
      mode: 'queue' | 'steer';
      position: number;
    }[];
  }> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/chat/queue/${encodeURIComponent(sessionId)}`
    );
    if (!response.ok) throw new Error(`获取会话队列失败: ${response.status}`);
    return response.json();
  }

  async deleteQueuedChatMessage(sessionId: string, messageId: string): Promise<void> {
    const response = await this._fetch(
      `${BACKEND_URL}/api/v1/chat/queue/${encodeURIComponent(sessionId)}/${encodeURIComponent(messageId)}`,
      { method: 'DELETE' }
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `删除排队消息失败: ${response.status}`);
    }
  }

  /** 定时任务列表 */
  async listTasks(enabled?: boolean): Promise<ScheduledTask[]> {
    const q = new URLSearchParams();
    if (enabled !== undefined) q.set('enabled', String(enabled));
    const qs = q.toString();
    // 必须与路由一致带尾部 /，否则 FastAPI 307 到 uvicorn 绝对地址时浏览器直连 8000，session cookie（挂在 localhost:3000 代理域）不会带上 → 401 误跳转登录
    const url = `${BACKEND_URL}/api/v1/tasks/${qs ? `?${qs}` : ''}`;
    const response = await this._fetch(url, { method: 'GET', headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`获取任务列表失败: ${response.status}`);
    return response.json();
  }

  async createTask(body: {
    name: string;
    schedule: string;
    type: 'skill' | 'script' | 'chat';
    params: Record<string, unknown>;
  }): Promise<ScheduledTask> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/tasks/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const t = await response.text();
      throw new Error(t || `创建任务失败: ${response.status}`);
    }
    return response.json();
  }

  async updateTask(
    taskId: string,
    body: Partial<{
      name: string;
      schedule: string;
      type: string;
      params: Record<string, unknown>;
      enabled: boolean;
    }>
  ): Promise<ScheduledTask> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`更新任务失败: ${response.status}`);
    return response.json();
  }

  async deleteTask(taskId: string): Promise<void> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/tasks/${taskId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`删除任务失败: ${response.status}`);
  }

  async runTaskNow(taskId: string): Promise<{
    ok: boolean;
    message: string;
    session_id: string;
    session: PersistedSession;
  }> {
    const response = await this._fetch(`${BACKEND_URL}/api/v1/tasks/${taskId}/run`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(`触发任务失败: ${response.status}`);
    return response.json();
  }
}

export const api = new ApiService();
