import React from 'react';
import { NavBar, Dialog } from 'antd-mobile';
import type { EidoStore } from '../hooks/useEidoStore';
import MenuIcon from '../components/MenuIcon';

const MeView: React.FC<{
  store: EidoStore;
  onOpenMenu: () => void;
  debugControl?: React.ReactNode;
  runtimeControl?: React.ReactNode;
  cloudRuntimeActive?: boolean;
}> = ({ store, onOpenMenu, debugControl, runtimeControl, cloudRuntimeActive = true }) => {
  const { currentUser, harness, setHarness, logout } = store;
  const displayName = currentUser?.username?.trim() || currentUser?.user_id || '用户';
  const harnessActive = harness === 'open_harness';

  const confirmLogout = async () => {
    const ok = await Dialog.confirm({ content: '确认登出？', confirmText: '登出', cancelText: '取消' });
    if (ok) logout();
  };

  return (
    <div className="flex h-full flex-col bg-[#f5f5f5]">
      <NavBar backArrow={<MenuIcon />} onBack={onOpenMenu} className="border-b border-gray-100 bg-white">
        我的
      </NavBar>

      <div className="thin-scrollbar flex-1 overflow-y-auto p-4">
        <div className="mb-4 flex items-center gap-4 rounded-2xl bg-white p-5 shadow-sm">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-gray-200 text-2xl font-black text-gray-600">
            {[...displayName][0]?.toUpperCase() || '?'}
          </div>
          <div className="min-w-0">
            <div className="truncate text-lg font-bold text-gray-800">{displayName}</div>
            <div className="truncate text-sm text-gray-400">{currentUser?.user_id}</div>
          </div>
        </div>

        {runtimeControl ? (
          <div className="mb-4 overflow-hidden rounded-2xl bg-white shadow-sm">
            {runtimeControl}
          </div>
        ) : null}

        <div className={`mb-4 overflow-hidden rounded-2xl bg-white shadow-sm ${cloudRuntimeActive ? '' : 'opacity-50'}`}>
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <div className="text-[15px] font-semibold text-gray-800">AI 后端</div>
              <div className="text-xs text-gray-400">
                {harnessActive ? 'OpenHarness' : 'Claude Code'}
              </div>
            </div>
            <button
              onClick={() => setHarness(harnessActive ? 'claude_code' : 'open_harness')}
              disabled={!cloudRuntimeActive}
              className="inline-flex items-center gap-1 rounded-full bg-gray-100 p-1"
            >
              <span
                className={`rounded-full px-3 py-1 text-xs font-bold transition-colors ${
                  !harnessActive ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
                }`}
              >
                CC
              </span>
              <span
                className={`rounded-full px-3 py-1 text-xs font-bold transition-colors ${
                  harnessActive ? 'bg-white text-gray-800 shadow' : 'text-gray-400'
                }`}
              >
                OH
              </span>
            </button>
          </div>
        </div>

        {debugControl ? (
          <div className="mb-4 overflow-hidden rounded-2xl bg-white shadow-sm">
            {debugControl}
          </div>
        ) : null}

        <button
          onClick={confirmLogout}
          className="w-full rounded-2xl bg-white py-4 text-center text-[15px] font-bold text-red-600 shadow-sm active:bg-gray-50"
        >
          登出
        </button>
      </div>
    </div>
  );
};

export default MeView;
