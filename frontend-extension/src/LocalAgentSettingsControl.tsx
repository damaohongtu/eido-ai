import React, { useEffect, useState } from 'react';
import { Toast } from 'antd-mobile';
import { DownlandOutline, FolderOutline, LinkOutline, PlayOutline } from 'antd-mobile-icons';
import type { LocalAgentSettings } from './localAgentRuntime';
import { saveLocalAgentSettings, testLocalOpenCode } from './localAgentRuntime';
import { requestNativeMessagingPermission } from './local-agent/nativeLauncherClient';
import {
  chooseOpenCodeWorkspace,
  ensureOpenCodeRunning,
} from './local-agent/openCodeLaunchCoordinator';

const NATIVE_LAUNCHER_RELEASE_BASE_URL =
  'https://github.com/damaohongtu/eido-ai/releases/latest/download';

async function nativeLauncherDownloadUrl(): Promise<string> {
  if (/Windows/i.test(navigator.userAgent)) {
    try {
      const userAgentData = (navigator as Navigator & {
        userAgentData?: {
          getHighEntropyValues(hints: string[]): Promise<{ architecture?: string }>;
        };
      }).userAgentData;
      const architecture = userAgentData
        ? (await userAgentData.getHighEntropyValues(['architecture'])).architecture
        : '';
      if (architecture && /arm/i.test(architecture)) {
        return `${NATIVE_LAUNCHER_RELEASE_BASE_URL}/Eido-OpenCode-Launcher-Windows-arm64.exe`;
      }
    } catch (error) {
      console.debug('无法识别 Windows CPU 架构，将使用兼容的 x64 Launcher', error);
    }
    return `${NATIVE_LAUNCHER_RELEASE_BASE_URL}/Eido-OpenCode-Launcher-Windows.exe`;
  }
  if (/Macintosh|Mac OS X/i.test(navigator.userAgent)) {
    return `${NATIVE_LAUNCHER_RELEASE_BASE_URL}/Eido-OpenCode-Launcher-macOS.pkg`;
  }
  return 'https://github.com/damaohongtu/eido-ai/releases/latest';
}

function readableError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const value = error as { message?: unknown; code?: unknown };
    if (typeof value.message === 'string') return value.message;
    if (typeof value.code === 'string') return value.code;
    try {
      return JSON.stringify(error);
    } catch {
      return '未知错误';
    }
  }
  return String(error || '未知错误');
}

const LocalAgentSettingsControl: React.FC<{ settings: LocalAgentSettings }> = ({ settings }) => {
  const [draft, setDraft] = useState(settings);
  const [testing, setTesting] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [connectionHealthy, setConnectionHealthy] = useState<boolean | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => setDraft(settings), [settings]);

  const save = async () => {
    try {
      await saveLocalAgentSettings({
        ...draft,
        opencodeUrl: draft.opencodeUrl.trim().replace(/\/+$/, ''),
        username: draft.username.trim(),
      });
      Toast.show({ content: '执行模式已保存' });
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      const message = readableError(error);
      console.error('保存本机 Agent 设置失败', error);
      setStatus(message);
      Toast.show({ content: message });
    }
  };

  const test = async () => {
    setTesting(true);
    setStatus(null);
    try {
      const health = await testLocalOpenCode(draft);
      if (!health.healthy) throw new Error('OpenCode 服务未就绪');
      setConnectionHealthy(true);
      setStatus(`已连接 OpenCode ${health.version || ''}`.trim());
    } catch (error) {
      setConnectionHealthy(false);
      console.error('测试本机 OpenCode 连接失败', error);
      setStatus(readableError(error));
    } finally {
      setTesting(false);
    }
  };

  const requireNativePermission = async () => {
    const granted = await requestNativeMessagingPermission();
    if (!granted) throw new Error('未授予本机启动权限，仍可连接手工启动的 OpenCode');
    return true;
  };

  const chooseWorkspace = async () => {
    setLaunching(true);
    setStatus('正在打开项目文件夹选择器...');
    try {
      await requireNativePermission();
      const workspace = await chooseOpenCodeWorkspace(draft.workspace);
      if (workspace) {
        setDraft((value) => ({ ...value, workspace }));
        setStatus('已选择项目文件夹');
      } else {
        setStatus('未更改项目文件夹');
      }
    } catch (error) {
      console.error('选择 OpenCode 项目文件夹失败', error);
      setStatus(readableError(error));
    } finally {
      setLaunching(false);
    }
  };

  const launch = async () => {
    setLaunching(true);
    setStatus('正在检测本机启动组件...');
    try {
      await requireNativePermission();
      const result = await ensureOpenCodeRunning({
        trigger: 'user_click',
        settings: draft,
        workspace: draft.workspace,
      });
      setConnectionHealthy(true);
      setStatus(`${result.status === 'started' ? '已启动并连接' : '已连接'} OpenCode ${result.version || ''}`.trim());
      Toast.show({ content: '本机 OpenCode 已就绪' });
      window.setTimeout(() => window.location.reload(), 350);
    } catch (error) {
      setConnectionHealthy(false);
      console.error('尝试唤起 OpenCode 失败', error);
      setStatus(readableError(error));
    } finally {
      setLaunching(false);
    }
  };

  const downloadLauncher = async () => {
    try {
      await chrome.tabs.create({ url: await nativeLauncherDownloadUrl() });
      setStatus('安装完成后请重新打开 Chrome，再次尝试唤起 OpenCode');
    } catch (error) {
      console.error('打开 Launcher 下载地址失败', error);
      setStatus(readableError(error));
    }
  };

  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[15px] font-semibold text-gray-800">执行位置</div>
          <div className="text-xs text-gray-400">
            {draft.mode === 'local' ? '认证外的数据仅在插件与 OpenCode 间流转' : '使用现有 Eido 服务'}
          </div>
        </div>
        <div className="inline-flex shrink-0 rounded-full bg-gray-100 p-1">
          <button
            type="button"
            onClick={() => setDraft((value) => ({ ...value, mode: 'cloud' }))}
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              draft.mode === 'cloud' ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
            }`}
          >
            云端
          </button>
          <button
            type="button"
            onClick={() => setDraft((value) => ({ ...value, mode: 'local' }))}
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              draft.mode === 'local' ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
            }`}
          >
            本机
          </button>
        </div>
      </div>

      {draft.mode === 'local' ? (
        <div className="mt-4 space-y-3 border-t border-gray-100 pt-4">
          <div className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-gray-700">OpenCode 连接</div>
              <div className="mt-0.5 truncate text-[11px] text-gray-400">{draft.opencodeUrl}</div>
            </div>
            <span className={`shrink-0 text-xs font-semibold ${
              connectionHealthy === true ? 'text-emerald-600' : connectionHealthy === false ? 'text-amber-600' : 'text-gray-400'
            }`}>
              {connectionHealthy === true ? '已连接' : connectionHealthy === false ? '未连接' : '待检测'}
            </span>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-gray-600">OpenCode 地址</span>
            <input
              value={draft.opencodeUrl}
              onChange={(event) => setDraft((value) => ({ ...value, opencodeUrl: event.target.value }))}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
              spellCheck={false}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block min-w-0">
              <span className="mb-1 block text-xs font-semibold text-gray-600">用户名</span>
              <input
                value={draft.username}
                onChange={(event) => setDraft((value) => ({ ...value, username: event.target.value }))}
                className="w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
                autoComplete="username"
              />
            </label>
            <label className="block min-w-0">
              <span className="mb-1 block text-xs font-semibold text-gray-600">密码（可选）</span>
              <input
                type="password"
                value={draft.password}
                onChange={(event) => setDraft((value) => ({ ...value, password: event.target.value }))}
                className="w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-400"
                autoComplete="current-password"
              />
            </label>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-gray-600">项目文件夹</div>
            <button
              type="button"
              onClick={chooseWorkspace}
              disabled={launching}
              className="flex w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-left disabled:opacity-50"
              title="选择 OpenCode 项目文件夹"
            >
              <FolderOutline className="shrink-0 text-base text-gray-500" />
              <span className={`min-w-0 flex-1 truncate text-xs ${draft.workspace ? 'text-gray-700' : 'text-gray-400'}`}>
                {draft.workspace || '选择 OpenCode 项目文件夹'}
              </span>
            </button>
          </div>
          {status ? <div className="break-words text-xs leading-relaxed text-gray-500">{status}</div> : null}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={test}
              disabled={testing}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-gray-300 bg-white py-2 text-xs font-bold text-gray-700 disabled:opacity-50"
            >
              <LinkOutline />
              {testing ? '检测中...' : '测试连接'}
            </button>
            <button
              type="button"
              onClick={save}
              className="flex-1 rounded-lg bg-gray-700 py-2 text-xs font-bold text-white"
            >
              保存并切换
            </button>
          </div>
          {connectionHealthy !== true ? (
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={downloadLauncher}
                className="flex items-center justify-center gap-1.5 rounded-lg border border-gray-300 bg-white py-2.5 text-xs font-bold text-gray-700"
              >
                <DownlandOutline />
                安装启动组件
              </button>
              <button
                type="button"
                onClick={launch}
                disabled={launching || !draft.workspace}
                className="flex items-center justify-center gap-1.5 rounded-lg bg-gray-800 py-2.5 text-xs font-bold text-white disabled:opacity-40"
              >
                <PlayOutline />
                {launching ? '正在唤起...' : '尝试唤起'}
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <button
          type="button"
          onClick={save}
          className="mt-4 w-full rounded-lg bg-gray-700 py-2 text-xs font-bold text-white"
        >
          保存并切换
        </button>
      )}
    </div>
  );
};

export default LocalAgentSettingsControl;
