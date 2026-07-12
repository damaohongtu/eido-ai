export const NATIVE_LAUNCHER_PROTOCOL = 1;

export type OpenCodeLaunchTrigger = 'user_click' | 'send_message' | 'auto_start';

export interface NativeLauncherFailure {
  ok: false;
  code: string;
  message: string;
}

export interface NativeLauncherPing {
  ok: true;
  protocol: number;
  launcherVersion: string;
  platform: string;
  capabilities: string[];
}

export interface NativeDirectorySelection {
  ok: true;
  selected: boolean;
  workspace?: string;
}

export interface NativeLaunchSuccess {
  ok: true;
  status: 'started' | 'already_running';
  pid?: number;
  endpoint: string;
  workspace?: string;
  username?: string;
  password?: string;
  version?: string;
  logPath?: string;
}

export type NativeLauncherResponse<T> = T | NativeLauncherFailure;

export interface OpenCodeLaunchResult {
  status: 'connected' | 'started';
  endpoint: string;
  workspace?: string;
  version?: string;
}
