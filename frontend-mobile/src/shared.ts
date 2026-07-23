/**
 * 复用 PC 端逻辑层的统一出口。
 *
 * 移动端不重写任何 API / 类型，全部从 ../frontend 复用，保证与 PC 端单一数据源、
 * 行为一致（含 SSE 流式协议、同源 cookie、尾部斜杠等约定）。
 */
export {
  api,
  hydrateSession,
  summaryToSession,
  getWorkspaceFileUrl,
  getProjectFileUrl,
} from '@shared/services/api';
export type {
  PersistedSession,
  PersistedSessionDetail,
  PersistedMessage,
  WorkspaceFileNode,
} from '@shared/services/api';

export { BACKEND_URL, INITIAL_CHAT_STATE } from '@shared/constants';

export type {
  ViewType,
  Skill,
  SkillAction,
  Message,
  ChatSession,
  Project,
  ProjectFile,
  CreateSessionOptions,
  Reference,
  ExecutionStep,
  Tool,
  Agent,
  ScheduledTask,
} from '@shared/types';
export { skillCanManage } from '@shared/types';
export {
  isProjectOutputPath,
  isSupportedProjectMaterial,
  canPreviewInBrowser,
  canRenderAsBrowserImage,
  shouldForceWorkspaceDownload,
} from '@shared/utils/projectFiles';
