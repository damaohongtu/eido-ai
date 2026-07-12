import type { LocalAgentSettings, OpenCodeHealth } from '../localAgentRuntime';
import { saveLocalAgentSettings, testLocalOpenCode } from '../localAgentRuntime';
import { launchOpenCode, pingNativeLauncher, selectNativeWorkspace } from './nativeLauncherClient';
import { NATIVE_LAUNCHER_PROTOCOL } from './launcherTypes';
import type { OpenCodeLaunchResult, OpenCodeLaunchTrigger } from './launcherTypes';

const launchTasks = new Map<string, Promise<OpenCodeLaunchResult>>();
const HEALTH_DELAYS = [200, 300, 500, 800, 1200, 1800, 2500, 3000, 3000];

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function preferredPort(endpoint: string): number {
  try {
    const parsed = new URL(endpoint);
    return Number(parsed.port || 4096);
  } catch {
    return 4096;
  }
}

async function waitForHealth(settings: LocalAgentSettings): Promise<OpenCodeHealth> {
  let lastError: unknown;
  for (const milliseconds of HEALTH_DELAYS) {
    try {
      const health = await testLocalOpenCode(settings);
      if (health.healthy) return health;
    } catch (error) {
      lastError = error;
    }
    await delay(milliseconds);
  }
  const error = new Error(
    lastError instanceof Error ? `OpenCode 启动后仍无法连接：${lastError.message}` : 'OpenCode 启动超时'
  ) as Error & { code?: string };
  error.code = 'START_TIMEOUT';
  throw error;
}

export async function chooseOpenCodeWorkspace(initialDirectory?: string): Promise<string | null> {
  const ping = await pingNativeLauncher();
  if (ping.protocol !== NATIVE_LAUNCHER_PROTOCOL) {
    throw new Error(`本机启动组件协议不兼容（当前 ${ping.protocol}，需要 ${NATIVE_LAUNCHER_PROTOCOL}）`);
  }
  const selection = await selectNativeWorkspace(initialDirectory);
  return selection.selected && selection.workspace ? selection.workspace : null;
}

export function ensureOpenCodeRunning(input: {
  trigger: OpenCodeLaunchTrigger;
  settings: LocalAgentSettings;
  workspace?: string;
}): Promise<OpenCodeLaunchResult> {
  const key = input.settings.opencodeUrl;
  const existing = launchTasks.get(key);
  if (existing) return existing;

  const task = (async () => {
    try {
      const health = await testLocalOpenCode(input.settings);
      if (health.healthy) {
        return {
          status: 'connected' as const,
          endpoint: input.settings.opencodeUrl,
          workspace: input.workspace || input.settings.workspace,
          version: health.version,
        };
      }
    } catch {
      // A failed direct health check is the reason to invoke the one-shot launcher.
    }

    const ping = await pingNativeLauncher();
    if (ping.protocol !== NATIVE_LAUNCHER_PROTOCOL) {
      const error = new Error(`本机启动组件版本不兼容，请更新本机组件`) as Error & { code?: string };
      error.code = 'PROTOCOL_MISMATCH';
      throw error;
    }

    const workspace = input.workspace || input.settings.workspace;
    if (!workspace) {
      const error = new Error('请先选择 OpenCode 项目文件夹') as Error & { code?: string };
      error.code = 'WORKSPACE_INVALID';
      throw error;
    }

    const launched = await launchOpenCode({
      workspace,
      preferredPort: preferredPort(input.settings.opencodeUrl),
      username: input.settings.username || 'opencode',
      password: input.settings.password,
    });
    const nextSettings: LocalAgentSettings = {
      ...input.settings,
      mode: 'local',
      opencodeUrl: launched.endpoint,
      username: launched.username || input.settings.username || 'opencode',
      password: launched.password ?? input.settings.password,
      workspace: launched.workspace || workspace,
    };
    const health = await waitForHealth(nextSettings);
    await saveLocalAgentSettings(nextSettings);
    return {
      status: launched.status === 'started' ? 'started' as const : 'connected' as const,
      endpoint: nextSettings.opencodeUrl,
      workspace: nextSettings.workspace,
      version: health.version || launched.version,
    };
  })().finally(() => launchTasks.delete(key));

  launchTasks.set(key, task);
  return task;
}
