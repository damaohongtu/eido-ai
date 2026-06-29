import React, { useEffect } from 'react';
import { Popup, SwipeAction, Dialog, Empty } from 'antd-mobile';
import { UnorderedListOutline, UserOutline, AddOutline, MessageOutline, DeleteOutline } from 'antd-mobile-icons';
import type { EidoStore, MobileTab } from '../hooks/useEidoStore';

function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const pad = (n: number) => String(n).padStart(2, '0');
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

interface AppDrawerProps {
  visible: boolean;
  onClose: () => void;
  store: EidoStore;
}

const AppDrawer: React.FC<AppDrawerProps> = ({ visible, onClose, store }) => {
  const {
    currentUser,
    sessions,
    activeSessionId,
    tab,
    setTab,
    refreshSessions,
    openChat,
    createNewSession,
    deleteSession,
  } = store;

  const displayName = currentUser?.username?.trim() || currentUser?.user_id || '用户';

  // 打开抽屉时刷新会话列表
  useEffect(() => {
    if (visible) refreshSessions();
  }, [visible, refreshSessions]);

  const navigate = (t: MobileTab) => {
    setTab(t);
    onClose();
  };

  const handleNewChat = () => {
    createNewSession();
    onClose();
  };

  const handleOpenChat = (id: string) => {
    openChat(id);
    onClose();
  };

  const confirmDelete = async (id: string, title: string) => {
    const ok = await Dialog.confirm({
      content: `删除会话「${title}」？`,
      confirmText: '删除',
      cancelText: '取消',
    });
    if (ok) deleteSession(id);
  };

  const navItems: { key: MobileTab; label: string; icon: React.ReactNode }[] = [
    { key: 'chat', label: '当前对话', icon: <MessageOutline /> },
    { key: 'skills', label: '技能广场', icon: <UnorderedListOutline /> },
    { key: 'me', label: '我的设置', icon: <UserOutline /> },
  ];

  return (
    <Popup
      visible={visible}
      onMaskClick={onClose}
      position="left"
      bodyStyle={{ width: '80vw', maxWidth: 360, height: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      <div className="flex h-full flex-col bg-white" style={{ paddingTop: 'var(--eido-safe-top)' }}>
        {/* 用户信息 */}
        <button
          onClick={() => navigate('me')}
          className="flex items-center gap-3 border-b border-gray-100 px-4 py-4 text-left active:bg-gray-50"
        >
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-gray-200 text-xl font-black text-gray-600">
            {[...displayName][0]?.toUpperCase() || '?'}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-bold text-gray-800">{displayName}</div>
            <div className="truncate text-xs text-gray-400">{currentUser?.user_id}</div>
          </div>
        </button>

        {/* 新建对话 */}
        <div className="px-3 pt-3">
          <button
            onClick={handleNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gray-700 py-2.5 text-sm font-bold text-white active:bg-gray-800"
          >
            <AddOutline />
            <span>新建对话</span>
          </button>
        </div>

        {/* 导航入口 */}
        <nav className="grid grid-cols-3 gap-1 px-3 py-3">
          {navItems.map((item) => (
            <button
              key={item.key}
              onClick={() => navigate(item.key)}
              className={`flex flex-col items-center gap-1 rounded-xl py-2 text-[11px] font-semibold transition-colors ${
                tab === item.key ? 'bg-gray-100 text-gray-900' : 'text-gray-500 active:bg-gray-50'
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* 历史会话 */}
        <div className="px-4 pb-1 pt-2 text-[10px] font-black uppercase tracking-widest text-gray-400">
          历史对话
        </div>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <div className="pt-16">
              <Empty description="暂无会话" />
            </div>
          ) : (
            <div className="divide-y divide-gray-50">
              {sessions.map((s) => (
                <SwipeAction
                  key={s.id}
                  rightActions={[
                    {
                      key: 'delete',
                      text: '删除',
                      color: 'danger',
                      onClick: () => confirmDelete(s.id, s.title),
                    },
                  ]}
                >
                  <div
                    className={`group flex w-full items-center gap-2 px-4 py-3 ${
                      activeSessionId === s.id ? 'bg-gray-100' : 'bg-white'
                    }`}
                  >
                    <button
                      onClick={() => handleOpenChat(s.id)}
                      className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left active:opacity-70"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800">{s.title}</span>
                      <span className="shrink-0 text-xs text-gray-400">{formatTime(s.updatedAt)}</span>
                    </button>
                    <button
                      onClick={() => confirmDelete(s.id, s.title)}
                      className="shrink-0 rounded-lg p-1.5 text-gray-300 active:bg-red-50 active:text-red-500"
                      title="删除会话"
                    >
                      <DeleteOutline fontSize={16} />
                    </button>
                  </div>
                </SwipeAction>
              ))}
            </div>
          )}
        </div>

        <div style={{ height: 'var(--eido-safe-bottom)' }} />
      </div>
    </Popup>
  );
};

export default AppDrawer;
