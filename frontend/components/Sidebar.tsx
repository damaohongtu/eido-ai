
import React, { useState, useEffect, useRef } from 'react';
import { ViewType, ChatSession } from '../types';
import { getAssetUrl } from '../config';

interface SidebarProps {
  activeView: ViewType;
  onNavigate: (view: ViewType) => void;
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  /** 当前登录用户（来自 /api/v1/auth/me） */
  currentUser: { user_id: string; username: string };
  /** 登出：清本地会话并跳转后端 /auth/logout（CAS 会再跳回前端） */
  onLogout: () => void;
}

function avatarInitial(name: string): string {
  const t = name.trim();
  if (!t) return '?';
  const first = [...t][0];
  return first.toUpperCase();
}

const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onNavigate,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  currentUser,
  onLogout,
}) => {
  const displayName = currentUser.username?.trim() || currentUser.user_id || '用户';
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!userMenuOpen) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [userMenuOpen]);

  const NavItem = ({ view, label, iconPath }: { view: ViewType, label: string, iconPath: string }) => (
    <button
      onClick={() => onNavigate(view)}
      className={`flex items-center space-x-3 px-4 py-2 rounded-lg transition-all w-full text-left ${activeView === view ? 'bg-gray-200 text-gray-900' : 'hover:bg-gray-100 text-gray-600'
        }`}
    >
      <img src={iconPath} alt={label} className="w-5 h-5 object-contain" />
      <span className="font-semibold">{label}</span>
    </button>
  );

  return (
    <aside className="w-64 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col h-full">
      <div className="p-6">
        <div className="flex items-center space-x-2 mb-8">
          <div className="w-8 h-8 bg-gray-600 rounded-lg flex items-center justify-center text-white font-bold text-lg">E</div>
          <h1 className="text-xl font-bold tracking-tight text-gray-900">ido</h1>
        </div>

        <button
          type="button"
          onClick={onNewChat}
          className="w-full font-semibold py-2.5 px-4 rounded-xl transition-all flex items-center justify-center space-x-2 mb-6 bg-white border border-gray-200 text-gray-800 hover:!bg-gray-50 hover:!border-gray-300"
        >
          <span>+</span>
          <span>新建会话</span>
        </button>

        <nav className="space-y-1 mb-8">
          <NavItem view={ViewType.HOME} label="探索发现" iconPath={getAssetUrl('/images/side/探索发现.png')} />
          <NavItem view={ViewType.SKILLS} label="我的技能" iconPath={getAssetUrl('/images/side/我的技能.png')} />
        </nav>

        <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3 px-2">历史记录</div>
        <div className="flex-1 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
          {sessions.length === 0 ? (
            <div className="px-3 py-4 text-sm text-gray-500 italic">暂无会话</div>
          ) : (
            sessions.map(s => (
              <div
                key={s.id}
                className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-all ${activeSessionId === s.id ? 'bg-gray-200 text-gray-900' : 'hover:bg-gray-100 text-gray-600'
                  }`}
                onClick={() => onSelectSession(s.id)}
              >
                <div className="truncate text-sm flex-1 font-medium">{s.title}</div>
                <button
                  onClick={(e) => { e.stopPropagation(); onDeleteSession(s.id); }}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500 transition-opacity"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="mt-auto p-4 border-t border-gray-100">
        <div className="flex items-center gap-2 px-2 py-1">
          <div ref={userMenuRef} className="relative shrink-0">
            <button
              type="button"
              onClick={() => setUserMenuOpen((v) => !v)}
              aria-expanded={userMenuOpen}
              aria-haspopup="menu"
              title="账户"
              className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-600 font-bold text-sm outline-none ring-offset-2 hover:bg-gray-300 focus-visible:ring-2 focus-visible:ring-gray-400 transition-colors"
            >
              {avatarInitial(displayName)}
            </button>
            {userMenuOpen ? (
              <div
                role="menu"
                className="absolute bottom-full left-0 mb-1 z-50 min-w-[7.5rem] rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="w-full px-3 py-2 text-left text-sm font-semibold text-red-600 hover:bg-red-50"
                  onClick={() => {
                    setUserMenuOpen(false);
                    onLogout();
                  }}
                >
                  登出
                </button>
              </div>
            ) : null}
          </div>
          <div className="flex-1 min-w-0 truncate">
            <div className="text-sm font-semibold text-gray-800 truncate" title={displayName}>
              {displayName}
            </div>
            <div className="text-xs text-gray-500 truncate" title={currentUser.user_id}>
              {currentUser.user_id !== displayName ? currentUser.user_id : '已登录'}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
