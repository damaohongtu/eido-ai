import React, { useState } from 'react';
import { SpinLoading, SafeArea } from 'antd-mobile';
import { useEidoStore } from './hooks/useEidoStore';
import AppDrawer from './components/AppDrawer';
import ChatView from './views/ChatView';
import SkillsView from './views/SkillsView';
import MeView from './views/MeView';

const App: React.FC = () => {
  const store = useEidoStore();
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

  const renderView = () => {
    switch (store.tab) {
      case 'skills':
        return <SkillsView store={store} onOpenMenu={openMenu} />;
      case 'me':
        return <MeView store={store} onOpenMenu={openMenu} />;
      case 'chat':
      default:
        return <ChatView store={store} onOpenMenu={openMenu} />;
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
