export const NATIVE_LAUNCHER_HOST = 'ai.eido.opencode_launcher';
export const NATIVE_LAUNCHER_PROTOCOL = 1;

const NATIVE_TIMEOUTS = Object.freeze({
  ping: 10000,
  detect: 10000,
  status: 10000,
  launch: 45000,
  select_directory: 5 * 60 * 1000,
});

const MESSAGE_TYPES = Object.freeze({
  EIDO_NATIVE_LAUNCHER_PING: 'ping',
  EIDO_OPENCODE_DETECT: 'detect',
  EIDO_OPENCODE_SELECT_DIRECTORY: 'select_directory',
  EIDO_OPENCODE_LAUNCH: 'launch',
  EIDO_OPENCODE_STATUS: 'status',
});

function protocolError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

export function nativeLauncherTimeout(command) {
  return NATIVE_TIMEOUTS[command] || 15000;
}

function optionalString(value, name, maxLength) {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string' || value.length > maxLength) {
    throw protocolError('INVALID_NATIVE_REQUEST', `${name} 参数无效`);
  }
  return value;
}

export function buildNativeLauncherRequest(message) {
  const command = MESSAGE_TYPES[message?.type];
  if (!command) throw protocolError('INVALID_NATIVE_REQUEST', '不支持的本机启动请求');

  const request = { protocol: NATIVE_LAUNCHER_PROTOCOL, command };
  if (command === 'select_directory') {
    const initialDirectory = optionalString(message.initialDirectory, 'initialDirectory', 4096);
    if (initialDirectory) request.initialDirectory = initialDirectory;
  }
  if (command === 'launch') {
    const workspace = optionalString(message.workspace, 'workspace', 4096);
    if (!workspace) throw protocolError('WORKSPACE_INVALID', '请先选择项目文件夹');
    const preferredPort = Number(message.preferredPort || 4096);
    if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535) {
      throw protocolError('INVALID_NATIVE_REQUEST', 'preferredPort 参数无效');
    }
    request.workspace = workspace;
    request.hostname = '127.0.0.1';
    request.preferredPort = preferredPort;
    request.username = optionalString(message.username, 'username', 128) || 'opencode';
    request.password = optionalString(message.password, 'password', 1024) || '';
    request.allowPortFallback = message.allowPortFallback !== false;
  }
  if (command === 'status') {
    const endpoint = optionalString(message.endpoint, 'endpoint', 256);
    if (!endpoint || !/^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d+$/i.test(endpoint)) {
      throw protocolError('INVALID_NATIVE_REQUEST', 'endpoint 必须是本机回环地址');
    }
    request.endpoint = endpoint;
  }
  return request;
}

export function normalizeNativeLauncherError(error) {
  let message = '本机启动组件调用失败';
  if (error instanceof Error || typeof error?.message === 'string') {
    message = error.message;
  } else if (typeof error === 'string') {
    message = error;
  } else if (error) {
    try {
      message = JSON.stringify(error);
    } catch {
      message = String(error);
    }
  }
  let code = error?.code || 'NATIVE_HOST_ERROR';
  if (/native messaging host.*not found|specified native messaging host/i.test(message)) {
    code = 'NATIVE_HOST_NOT_FOUND';
  } else if (/access.*host|not allowed|forbidden/i.test(message)) {
    code = 'NATIVE_HOST_FORBIDDEN';
  }
  return { ok: false, code, message };
}
