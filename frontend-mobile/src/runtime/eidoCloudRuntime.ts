import { api, getWorkspaceFileUrl } from '../shared';
import type { AgentRuntime } from './types';

export const eidoCloudRuntime: AgentRuntime = {
  id: 'eido-cloud',
  label: 'Eido 服务',
  isLocal: false,
  canDeleteWorkspaceFiles: true,
  streamChat: api.streamChat.bind(api),
  uploadChatFile: api.uploadChatFile.bind(api),
  listWorkspaceFiles: api.listWorkspaceFiles.bind(api),
  deleteWorkspaceFile: api.deleteWorkspaceFile.bind(api),
  getWorkspaceFileUrl,
};
