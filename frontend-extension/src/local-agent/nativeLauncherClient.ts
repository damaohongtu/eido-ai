import type {
  NativeDirectorySelection,
  NativeLauncherPing,
  NativeLauncherResponse,
  NativeLaunchSuccess,
} from './launcherTypes';

const CLIENT_TIMEOUTS = {
  default: 20000,
  launch: 60000,
  selectDirectory: 5 * 60 * 1000 + 10000,
};

function timeoutError(message: string): Error & { code?: string } {
  const error = new Error(message) as Error & { code?: string };
  error.code = 'NATIVE_REQUEST_TIMEOUT';
  return error;
}

function sendMessage<T>(
  message: Record<string, unknown>,
  timeoutMilliseconds = CLIENT_TIMEOUTS.default
): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(timeoutError('本机启动组件响应超时，请重新打开 Chrome 后重试'));
    }, timeoutMilliseconds);

    chrome.runtime.sendMessage(message, (response) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      resolve(response as T);
    });
  });
}

function permissionResult(
  operation: (callback: (granted: boolean) => void) => void
): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(false);
    }, 15000);
    operation((granted) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      resolve(granted);
    });
  });
}

function unwrap<T extends { ok: true }>(response: NativeLauncherResponse<T>): T {
  if (!response || response.ok !== true) {
    const failure = response as { code?: string; message?: string } | undefined;
    const friendlyMessages: Record<string, string> = {
      NATIVE_HOST_NOT_FOUND: '未检测到本机启动组件，请先安装 Eido OpenCode Launcher',
      NATIVE_HOST_FORBIDDEN: '本机启动组件未授权当前插件，请重新安装或修复组件',
      OPENCODE_NOT_FOUND: '未找到已安装的 OpenCode',
      WORKSPACE_INVALID: '项目文件夹不存在或不可访问',
      PORT_IN_USE: 'OpenCode 可用端口已被占用',
      AUTH_MISMATCH: 'OpenCode 已在运行，但插件中的连接密码不正确',
      SPAWN_FAILED: '系统未能启动 OpenCode，请查看启动日志',
      NATIVE_REQUEST_TIMEOUT: '本机启动组件响应超时，请重新打开 Chrome 后重试',
      DIRECTORY_SELECTOR_FAILED: '无法打开系统文件夹选择器，请完全退出并重新打开 Chrome 后重试',
    };
    const message = friendlyMessages[failure?.code || ''] || failure?.message || '本机启动组件调用失败';
    const error = new Error(message) as Error & { code?: string };
    error.code = failure?.code || 'NATIVE_HOST_ERROR';
    throw error;
  }
  return response;
}

export function hasNativeMessagingPermission(): Promise<boolean> {
  return permissionResult((resolve) => {
    chrome.permissions.contains({ permissions: ['nativeMessaging'] }, resolve);
  });
}

export function requestNativeMessagingPermission(): Promise<boolean> {
  return permissionResult((resolve) => {
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
  }, CLIENT_TIMEOUTS.selectDirectory));
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
  }, CLIENT_TIMEOUTS.launch));
}
