import type {
  NativeDirectorySelection,
  NativeLauncherPing,
  NativeLauncherResponse,
  NativeLaunchSuccess,
} from './launcherTypes';

function sendMessage<T>(message: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      resolve(response as T);
    });
  });
}

function unwrap<T extends { ok: true }>(response: NativeLauncherResponse<T>): T {
  if (!response || response.ok === false) {
    const failure = response as { code?: string; message?: string } | undefined;
    const friendlyMessages: Record<string, string> = {
      NATIVE_HOST_NOT_FOUND: '未检测到本机启动组件，请先安装 Eido OpenCode Launcher',
      NATIVE_HOST_FORBIDDEN: '本机启动组件未授权当前插件，请重新安装或修复组件',
      OPENCODE_NOT_FOUND: '未找到已安装的 OpenCode',
      WORKSPACE_INVALID: '项目文件夹不存在或不可访问',
      PORT_IN_USE: 'OpenCode 可用端口已被占用',
      AUTH_MISMATCH: 'OpenCode 已在运行，但插件中的连接密码不正确',
      SPAWN_FAILED: '系统未能启动 OpenCode，请查看启动日志',
    };
    const message = friendlyMessages[failure?.code || ''] || failure?.message || '本机启动组件调用失败';
    const error = new Error(message) as Error & { code?: string };
    error.code = failure?.code || 'NATIVE_HOST_ERROR';
    throw error;
  }
  return response;
}

export function hasNativeMessagingPermission(): Promise<boolean> {
  return new Promise((resolve) => {
    chrome.permissions.contains({ permissions: ['nativeMessaging'] }, resolve);
  });
}

export function requestNativeMessagingPermission(): Promise<boolean> {
  return new Promise((resolve) => {
    chrome.permissions.request({ permissions: ['nativeMessaging'] }, resolve);
  });
}

export async function pingNativeLauncher(): Promise<NativeLauncherPing> {
  return unwrap(await sendMessage<NativeLauncherResponse<NativeLauncherPing>>({
    type: 'EIDO_NATIVE_LAUNCHER_PING',
  }));
}

export async function selectNativeWorkspace(initialDirectory?: string): Promise<NativeDirectorySelection> {
  return unwrap(await sendMessage<NativeLauncherResponse<NativeDirectorySelection>>({
    type: 'EIDO_OPENCODE_SELECT_DIRECTORY',
    initialDirectory,
  }));
}

export async function launchOpenCode(input: {
  workspace: string;
  preferredPort: number;
  username: string;
  password: string;
}): Promise<NativeLaunchSuccess> {
  return unwrap(await sendMessage<NativeLauncherResponse<NativeLaunchSuccess>>({
    type: 'EIDO_OPENCODE_LAUNCH',
    ...input,
    allowPortFallback: true,
  }));
}
