import React, { useEffect } from 'react';
import { Popup, SwipeAction, Dialog, Empty } from 'antd-mobile';
import { UnorderedListOutline, UserOutline, AddOutline, MessageOutline, DeleteOutline } from 'antd-mobile-icons';
import type { EidoStore, MobileTab } from '../hooks/useEidoStore';
import type { ChatSession } from '../shared';

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
    projects,
    projectsEnabled,
    activeSessionId,
    tab,
    setTab,
    refreshSessions,
    refreshProjects,
    openChat,
    createNewSession,
    deleteSession,
  } = store;

  const displayName = currentUser?.username?.trim() || currentUser?.user_id || '用户';
  const knownProjectIds = new Set(projects.map((project) => project.id));
  const unavailableProjectSessions = projectsEnabled
    ? sessions.filter((session) => Boolean(session.projectId) && !knownProjectIds.has(session.projectId as string))
    : [];

  // 打开抽屉时刷新会话列表
  useEffect(() => {
    if (visible) {
      refreshSessions();
      if (projectsEnabled) refreshProjects();
    }
  }, [visible, refreshSessions, refreshProjects, projectsEnabled]);

  const navigate = (t: MobileTab) => {
    setTab(t);
    onClose();
  };

  const handleNewChat = () => {
    createNewSession({ projectId: null });
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

  const renderSession = (session: ChatSession) => (
    <SwipeAction
      key={session.id}
      rightActions={[
        {
          key: 'delete',
          text: '删除',
          color: 'danger',
          onClick: () => confirmDelete(session.id, session.title),
        },
      ]}
    >
      <div
        className={`eido-mobile-session-item group flex w-full items-center gap-2 px-4 py-3 ${
          activeSessionId === session.id ? 'bg-gray-100' : 'bg-white'
        }`}
      >
        <button
          onClick={() => handleOpenChat(session.id)}
          className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left active:opacity-70"
        >
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800">{session.title}</span>
          <span className="shrink-0 text-xs text-gray-400">{formatTime(session.updatedAt)}</span>
        </button>
        <button
          onClick={() => confirmDelete(session.id, session.title)}
          className="shrink-0 rounded-lg p-1.5 text-gray-300 active:bg-red-50 active:text-red-500"
          title="删除会话"
        >
          <DeleteOutline fontSize={16} />
        </button>
      </div>
    </SwipeAction>
  );

  return (
    <Popup
      visible={visible}
      onMaskClick={onClose}
      position="left"
      bodyStyle={{ width: '80vw', maxWidth: 360, height: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      <div className="eido-mobile-drawer flex h-full flex-col bg-white" style={{ paddingTop: 'var(--eido-safe-top)' }}>
        {/* 用户信息 */}
        <button
          onClick={() => navigate('me')}
          className="eido-mobile-drawer-user flex items-center gap-3 border-b border-gray-100 px-4 py-4 text-left active:bg-gray-50"
        >
          <div className="eido-mobile-user-avatar flex h-11 w-11 items-center justify-center rounded-full bg-gray-200 text-xl font-black text-gray-600">
            {[...displayName][0]?.toUpperCase() || '?'}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-bold text-gray-800">{displayName}</div>
            <div className="truncate text-xs text-gray-400">{currentUser?.user_id}</div>
          </div>
        </button>

        {/* 新建对话 */}
        <div className="eido-mobile-drawer-new px-3 pt-3">
          <button
            onClick={handleNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gray-700 py-2.5 text-sm font-bold text-white active:bg-gray-800"
          >
            <AddOutline />
            <span>新建对话</span>
          </button>
        </div>

        {/* 导航入口 */}
        <nav className="eido-mobile-drawer-nav flex flex-col gap-1 px-3 py-3">
          {navItems.map((item) => (
            <button
              key={item.key}
              onClick={() => navigate(item.key)}
              className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-semibold transition-colors ${
                tab === item.key ? 'bg-gray-100 text-gray-900' : 'text-gray-500 active:bg-gray-50'
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* 项目与分组会话 */}
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto pb-3">
          {projectsEnabled ? (
            <>
              <div className="eido-mobile-drawer-label px-4 pb-1 pt-2 text-[10px] font-black uppercase tracking-widest text-gray-400">
                项目
              </div>
              {projects.length === 0 ? (
                <div className="px-4 py-3 text-xs text-gray-400">暂无项目，可在桌面端创建。</div>
              ) : projects.map((project) => {
                const projectSessions = sessions.filter((session) => session.projectId === project.id);
                return (
                  <section key={project.id} className="mb-2 border-b border-gray-100 pb-2">
                    <div className="flex items-center gap-2 px-4 py-2">
                      <span>{project.archived_at ? '📦' : '📁'}</span>
                      <span className="min-w-0 flex-1 truncate text-sm font-bold text-gray-800">
                        {project.name}{project.archived_at ? '（已归档）' : ''}
                      </span>
                      <button
                        onClick={() => {
                          createNewSession({ projectId: project.id });
                          onClose();
                        }}
                        disabled={Boolean(project.archived_at)}
                        className="rounded-lg bg-gray-100 px-2 py-1 text-[11px] font-bold text-gray-600 active:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {project.archived_at ? '已归档' : '+ 会话'}
                      </button>
                    </div>
                    {projectSessions.length === 0 ? (
                      <div className="px-10 py-2 text-xs text-gray-400">暂无会话</div>
                    ) : (
                      <div className="divide-y divide-gray-50">{projectSessions.map(renderSession)}</div>
                    )}
                  </section>
                );
              })}
              {unavailableProjectSessions.length > 0 ? (
                <section className="mx-3 mb-2 rounded-xl border border-amber-100 bg-amber-50/70 py-2">
                  <div className="px-3 pb-1 text-[10px] font-black uppercase tracking-widest text-amber-700">
                    项目列表暂不可用
                  </div>
                  <div className="divide-y divide-amber-100/60">
                    {unavailableProjectSessions.map(renderSession)}
                  </div>
                </section>
              ) : null}
            </>
          ) : (
            <div className="mx-3 mb-2 rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700">
              本机模式使用当前 OpenCode 项目目录，不读取或发送 Eido 云端项目资料。
            </div>
          )}

          <div className="eido-mobile-drawer-label px-4 pb-1 pt-3 text-[10px] font-black uppercase tracking-widest text-gray-400">
            {projectsEnabled ? '未归属对话' : '本机对话'}
          </div>
          {sessions.filter((session) => !session.projectId).length === 0 ? (
            <div className="pt-10"><Empty description="暂无会话" /></div>
          ) : (
            <div className="divide-y divide-gray-50">
              {sessions.filter((session) => !session.projectId).map(renderSession)}
            </div>
          )}
        </div>

        <div style={{ height: 'var(--eido-safe-bottom)' }} />
      </div>
    </Popup>
  );
};

export default AppDrawer;
