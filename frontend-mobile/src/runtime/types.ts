import type { ExecutionStep, Message, Reference, Skill, WorkspaceFileNode } from '../shared';

export type ChatChunkHandler = (
  text: string,
  thinking: string,
  steps?: ExecutionStep[],
  pendingConfirmation?: Message['pendingConfirmation'],
  references?: Reference[],
  workflowMermaid?: string
) => void;

export interface AgentRuntime {
  id: string;
  label: string;
  isLocal: boolean;
  canDeleteWorkspaceFiles?: boolean;
  streamChat(
    messages: Message[],
    onChunk: ChatChunkHandler,
    sessionId: string,
    assistantMessageId: string,
    context?: string,
    skillHint?: string,
    signal?: AbortSignal,
    harness?: string
  ): Promise<void>;
  uploadChatFile(file: File, sessionId: string): Promise<{ path: string; name: string }>;
  listWorkspaceFiles(sessionId: string): Promise<WorkspaceFileNode[]>;
  deleteWorkspaceFile(sessionId: string, path: string): Promise<void>;
  getWorkspaceFileUrl(
    path: string,
    options?: { download?: boolean; filename?: string; sessionId?: string }
  ): string;
  openWorkspaceFile?(
    path: string,
    options?: { download?: boolean; filename?: string; sessionId?: string }
  ): Promise<void>;
  respondToConfirmation?(
    sessionId: string,
    confirmationId: string,
    approved: boolean
  ): Promise<void>;
  listSkills?(): Promise<Skill[]>;
  deleteSession?(sessionId: string): Promise<void>;
}
