import React, { useState } from 'react';
import { SpinLoading, SafeArea } from 'antd-mobile';
import { useEidoStore } from './hooks/useEidoStore';
import { BACKEND_URL } from './shared';
import AppDrawer from './components/AppDrawer';
import ChatView from './views/ChatView';
import SkillsView from './views/SkillsView';
import MeView from './views/MeView';
import { eidoCloudRuntime } from './runtime/eidoCloudRuntime';
import type { AgentRuntime } from './runtime/types';

interface AppProps {
  browserContext?: string;
  browserContextControl?: React.ReactNode;
  debugControl?: React.ReactNode;
  runtimeControl?: React.ReactNode;
  agentRuntime?: AgentRuntime;
  extensionMode?: boolean;
  onAuthRequired?: (loginUrl: string) => void;
}

const App: React.FC<AppProps> = ({
  browserContext,
  browserContextControl,
  debugControl,
  runtimeControl,
  agentRuntime = eidoCloudRuntime,
  extensionMode = false,
  onAuthRequired,
}) => {
  const store = useEidoStore({
    extensionMode,
    onAuthRequired,
    localMode: agentRuntime.isLocal,
    agentRuntime,
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const openMenu = () => setDrawerOpen(true);

  if (!store.authChecked) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-white">
        <SpinLoading color="default" />
        <p className="text-sm text-gray-400">正在验证登录状态…</p>
      </div>
    );
  }

  if (store.authRequired) {
    const loginUrl = `${BACKEND_URL}/api/v1/auth/login`;
    return (
      <div className="flex h-full flex-col bg-white">
        <SafeArea position="top" />
        <div className="flex flex-1 items-center justify-center px-6">
          <div className="w-full rounded-2xl border border-gray-200 bg-white p-6 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-gray-100 text-xl font-black text-gray-700">
              E
            </div>
            <h1 className="text-lg font-black text-gray-900">需要登录 Eido</h1>
            <p className="mt-2 text-sm leading-relaxed text-gray-500">
              请在新标签页完成登录。登录后插件会自动检测，也可以手动刷新状态。
            </p>
            <button
              type="button"
              onClick={() => window.open(loginUrl, '_blank', 'noopener,noreferrer')}
              className="mt-5 w-full rounded-xl bg-gray-800 px-4 py-3 text-sm font-bold text-white active:bg-gray-900"
            >
              打开登录页
            </button>
            <button
              type="button"
              onClick={() => store.checkAuthState()}
              disabled={store.authChecking}
              className="mt-3 w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm font-bold text-gray-700 active:bg-gray-50 disabled:opacity-60"
            >
              {store.authChecking ? '正在检测...' : '我已完成登录，重新检测'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const renderView = () => {
    switch (store.tab) {
      case 'skills':
        return <SkillsView store={store} onOpenMenu={openMenu} />;
      case 'me':
        return (
          <MeView
            store={store}
            onOpenMenu={openMenu}
            debugControl={debugControl}
            runtimeControl={runtimeControl}
            cloudRuntimeActive={!agentRuntime.isLocal}
          />
        );
      case 'chat':
      default:
        return (
          <ChatView
            store={store}
            onOpenMenu={openMenu}
            browserContext={browserContext}
            browserContextControl={browserContextControl}
            agentRuntime={agentRuntime}
          />
        );
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-white">
      <SafeArea position="top" />
      <div className="min-h-0 flex-1">{renderView()}</div>
      <AppDrawer visible={drawerOpen} onClose={() => setDrawerOpen(false)} store={store} />
    </div>
  );
};

export default App;
