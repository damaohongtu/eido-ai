
export enum ViewType {
  HOME = 'home',
  CHAT = 'chat',
  SKILLS = 'skills',
  SKILL_DETAIL = 'skill_detail',
  /** 定时自动任务 */
  SCHEDULED_TASKS = 'scheduled_tasks',
}

/** 后端 /api/v1/tasks 定时任务 */
export interface ScheduledTask {
  id: string;
  user_id: string;
  name: string;
  schedule: string;
  type: string;
  params: {
    messages?: { role: string; content: string }[];
    [key: string]: unknown;
  };
  enabled: boolean;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  category: string | null;
  parameters_schema?: Record<string, any>;
  config?: Record<string, any>;
  is_system: boolean;
  is_public: boolean;
  is_active: boolean;
  usage_count: number;
  user_id?: string | null;
  created_at: string;
  updated_at: string;
  detail?: string; // markdown格式的详细定义（前端补充）
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  category: string | null;
  parameters_schema?: Record<string, any>;
  config?: Record<string, any>;  // 包含system_prompt、mcp_server_url等
  is_system: boolean;
  is_public: boolean;
  is_active: boolean;
  usage_count: number;
  user_id?: string | null;
  created_at: string;
  updated_at: string;
  detail?: string; // markdown格式的详细定义（前端补充）
}

export interface ExecutionStep {
  id: string;
  label: string;
  type: 'agent' | 'tool';
  status: 'pending' | 'running' | 'completed' | 'waiting';
  description?: string;
}

export interface SkillAction {
  id: string;
  label: string;
  icon: string;
  description: string;
  toolId?: string;
  type: 'ui_interaction' | 'api_call';
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  output_schema?: Record<string, any>;
  is_system: boolean;
  is_public: boolean;
  is_active: boolean;
  version: number;
  usage_count: number;
  user_id?: string | null;
  /** 当前登录用户是否可编辑/删除/管理该技能（后端 /skills 已计算） */
  is_owner?: boolean;
  owner_type?: string;
  owner_user_id?: string | null;
  created_at: string;
  updated_at: string;
  // 关联信息（SkillDetail 返回）
  tools?: SkillToolRef[];
  agents?: SkillAgentRef[];
  // 前端兼容字段
  actions?: SkillAction[];
  detail?: string; // markdown 格式的详细说明
}

/** 是否可管理该技能：优先 is_owner；未返回时兼容旧逻辑（!is_system 视为用户上传可改） */
export function skillCanManage(skill: Pick<Skill, 'is_system' | 'is_owner'>): boolean {
  if (typeof skill.is_owner === 'boolean') {
    return skill.is_owner;
  }
  return !skill.is_system;
}

export interface SkillToolRef {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  category: string | null;
  order: number;
  default_params?: Record<string, any>;
}

export interface SkillAgentRef {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  category: string | null;
  order: number;
  context_config?: Record<string, any>;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  thinking?: string;
  thinkingLog?: string[];   // 执行过程中每条 thinking 事件的有序记录
  executionSteps?: ExecutionStep[];
  workflowMermaid?: string;
  pendingConfirmation?: {
    toolId: string;
    label: string;
    description: string;
  };
  references?: Reference[];
  timestamp: number;
}

export interface Reference {
  title: string;
  url: string;
  snippet?: string;
  source: 'web' | 'knowledge' | 'tool';
}

export interface ChatSession {
  id: string;
  title: string;
  skillId?: string;
  messages: Message[];
  updatedAt: number;
}
