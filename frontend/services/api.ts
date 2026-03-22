import { Message, Skill, ExecutionStep, Tool, Agent, Reference } from "../types";
import { BACKEND_URL } from "../constants";

/** 工作区文件（如图片）的预览 URL，供聊天中生成的 K 线图等直接展示 */
export function getWorkspaceFileUrl(path: string): string {
  return `${BACKEND_URL}/api/v1/workspace/file?path=${encodeURIComponent(path)}`;
}

export class ApiService {
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
      const response = await fetch(url, {
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
      const response = await fetch(`${BACKEND_URL}/api/v1/tools/${toolId}`, {
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
      const response = await fetch(url, {
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
      const response = await fetch(`${BACKEND_URL}/api/v1/agents/${agentId}`, {
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
      const response = await fetch(url, {
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
      const response = await fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
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

    const response = await fetch(`${BACKEND_URL}/api/v1/skills/upload`, {
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
    icon?: string;
    output_schema?: Record<string, any>;
    is_public?: boolean;
    tool_ids?: string[];
    agent_ids?: string[];
  }): Promise<Skill> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/skills/`, {
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
    icon: string;
    output_schema: Record<string, any>;
    is_public: boolean;
    is_active: boolean;
  }>): Promise<Skill> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
        method: 'PATCH',
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
   * 删除Skill
   */
  async deleteSkill(skillId: string): Promise<void> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/skills/${skillId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error(`删除Skill失败: ${response.status}`);
      }
    } catch (error) {
      console.error('删除Skill失败:', error);
      throw error;
    }
  }

  /**
   * 上传聊天附件（.md / .pdf），返回工作区内的绝对路径
   */
  async uploadChatFile(file: File): Promise<{ path: string; name: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${BACKEND_URL}/api/v1/chat/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `上传失败: ${response.status}`);
    }
    return response.json();
  }

  /**
   * 统一聊天执行入口：由后端 claude_agent_sdk 自动识别并执行技能，流式返回。
   *
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
    context?: string,
    skillHint?: string,
    signal?: AbortSignal
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
      const response = await fetch(`${BACKEND_URL}/api/v1/chat/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: messages.map(m => ({ role: m.role, content: m.content })),
          context: effectiveContext,
        }),
        signal,
      });

      if (!response.ok) throw new Error('请求失败');

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

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
}

export const api = new ApiService();
