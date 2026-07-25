
import React, { useState, useEffect, useRef } from 'react';
import { ViewType, ChatSession, Project } from '../types';
import { getAssetUrl } from '../config';

const SIDEBAR_COLLAPSE_STORAGE_KEY = 'eido_sidebar_collapse_v1';

interface SidebarCollapsePreferences {
  projectsCollapsed: boolean;
  unassignedCollapsed: boolean;
  expandedProjectIds: string[];
  collapsedProjectIds: string[];
}

const DEFAULT_COLLAPSE_PREFERENCES: SidebarCollapsePreferences = {
  projectsCollapsed: false,
  unassignedCollapsed: false,
  expandedProjectIds: [],
  collapsedProjectIds: [],
};

function loadCollapsePreferences(): SidebarCollapsePreferences {
  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY);
    if (!stored) return DEFAULT_COLLAPSE_PREFERENCES;
    const parsed = JSON.parse(stored) as Partial<SidebarCollapsePreferences>;
    return {
      projectsCollapsed: parsed.projectsCollapsed === true,
      unassignedCollapsed: parsed.unassignedCollapsed === true,
      expandedProjectIds: Array.isArray(parsed.expandedProjectIds)
        ? parsed.expandedProjectIds.filter((id): id is string => typeof id === 'string')
        : [],
      collapsedProjectIds: Array.isArray(parsed.collapsedProjectIds)
        ? parsed.collapsedProjectIds.filter((id): id is string => typeof id === 'string')
        : [],
    };
  } catch {
    return DEFAULT_COLLAPSE_PREFERENCES;
  }
}

function setProjectSessionsExpanded(
  preferences: SidebarCollapsePreferences,
  projectId: string,
  expanded: boolean,
): SidebarCollapsePreferences {
  return {
    ...preferences,
    expandedProjectIds: expanded
      ? [...preferences.expandedProjectIds.filter(id => id !== projectId), projectId]
      : preferences.expandedProjectIds.filter(id => id !== projectId),
    collapsedProjectIds: expanded
      ? preferences.collapsedProjectIds.filter(id => id !== projectId)
      : [...preferences.collapsedProjectIds.filter(id => id !== projectId), projectId],
  };
}

function CollapseChevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

interface SidebarProps {
  activeView: ViewType;
  onNavigate: (view: ViewType) => void;
  sessions: ChatSession[];
  projects: Project[];
  activeProjectId: string | null;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onNewProject: () => void;
  onSelectProject: (id: string) => void;
  onDeleteSession: (id: string) => void;
  /** 当前登录用户（来自 /api/v1/auth/me） */
  currentUser: { user_id: string; username: string };
  /** 登出：清本地会话并跳转后端 /auth/logout（CAS 会再跳回前端） */
  onLogout: () => void;
  /** AI 后端切换 */
  harness: string;
  onHarnessChange: (h: string) => void;
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
  projects,
  activeProjectId,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onNewProject,
  onSelectProject,
  onDeleteSession,
  currentUser,
  onLogout,
  harness,
  onHarnessChange,
}) => {
  const displayName = currentUser.username?.trim() || currentUser.user_id || '用户';
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [collapsePreferences, setCollapsePreferences] = useState<SidebarCollapsePreferences>(loadCollapsePreferences);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSE_STORAGE_KEY, JSON.stringify(collapsePreferences));
    } catch {
      // localStorage may be unavailable in private/restricted browser contexts.
    }
  }, [collapsePreferences]);

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

  const NavItem = ({
    view,
    label,
    iconPath,
    icon,
  }: {
    view: ViewType;
    label: string;
    iconPath?: string;
    icon?: React.ReactNode;
  }) => (
    <button
      type="button"
      onClick={() => onNavigate(view)}
      className={`flex items-center space-x-3 px-4 py-2 rounded-lg transition-all w-full text-left ${activeView === view ? 'bg-gray-200 text-gray-900' : 'hover:bg-gray-100 text-gray-600'
        }`}
    >
      <span className="w-5 h-5 shrink-0 flex items-center justify-center text-current">
        {iconPath ? <img src={iconPath} alt="" className="w-5 h-5 object-contain" /> : icon}
      </span>
      <span className="font-semibold">{label}</span>
    </button>
  );

  const harnessOptions = [
    { value: 'claude_code', short: 'CC', label: 'Claude Code' },
    // { value: 'open_harness', short: 'OH', label: 'OpenHarness' },
    { value: 'opencode', short: 'OC', label: 'OpenCode' },
  ];

  const unassignedSessions = sessions.filter(session => !session.projectId);
  const knownProjectIds = new Set(projects.map(project => project.id));
  const unavailableProjectSessions = sessions.filter(
    session => Boolean(session.projectId) && !knownProjectIds.has(session.projectId as string)
  );
  const projectsExpanded = !collapsePreferences.projectsCollapsed;
  const unassignedExpanded = !collapsePreferences.unassignedCollapsed;

  const toggleProjects = () => {
    setCollapsePreferences(previous => ({
      ...previous,
      projectsCollapsed: !previous.projectsCollapsed,
    }));
  };

  const toggleUnassigned = () => {
    setCollapsePreferences(previous => ({
      ...previous,
      unassignedCollapsed: !previous.unassignedCollapsed,
    }));
  };

  const toggleProjectSessions = (projectId: string, expanded: boolean) => {
    setCollapsePreferences(previous => setProjectSessionsExpanded(previous, projectId, !expanded));
  };

  const selectProject = (projectId: string) => {
    setCollapsePreferences(previous => setProjectSessionsExpanded(previous, projectId, true));
    onSelectProject(projectId);
  };

  return (
    <aside className="w-64 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col h-full">
      {/* ---- Top: logo + new chat + nav (shrink-0) ---- */}
      <div className="p-6 pb-2 shrink-0">
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

        <nav className="space-y-1 mb-4">
          <NavItem view={ViewType.HOME} label="探索发现" iconPath={getAssetUrl('/images/side/探索发现.png')} />
          <NavItem view={ViewType.SKILLS} label="我的技能" iconPath={getAssetUrl('/images/side/我的技能.png')} />
          <NavItem
            view={ViewType.SCHEDULED_TASKS}
            label="自动任务"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            }
          />
        </nav>

        <div className="flex items-center justify-between gap-1 px-2">
          <button
            type="button"
            onClick={toggleProjects}
            aria-expanded={projectsExpanded}
            aria-controls="sidebar-projects-section"
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md py-1 text-left text-xs font-bold uppercase tracking-wider text-gray-500 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-300"
            title={projectsExpanded ? '折叠项目' : '展开项目'}
          >
            <CollapseChevron expanded={projectsExpanded} />
            <span>项目</span>
            <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] leading-none text-gray-500" aria-label={`${projects.length} 个项目`}>
              {projects.length}
            </span>
          </button>
          <button
            type="button"
            onClick={onNewProject}
            className="flex h-6 w-6 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            title="新建项目"
            aria-label="新建项目"
          >
            +
          </button>
        </div>
      </div>

      {/* ---- Middle: projects + grouped sessions ---- */}
      <div className="custom-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto px-6 pb-3">
        {projectsExpanded ? (
          <div id="sidebar-projects-section">
            {projects.length === 0 ? (
              <button type="button" onClick={onNewProject} className="w-full rounded-lg px-3 py-3 text-left text-xs text-gray-400 hover:bg-gray-50 hover:text-gray-600">
                暂无项目，点击创建
              </button>
            ) : projects.map(project => {
              const projectSessions = sessions.filter(session => session.projectId === project.id);
              const projectSessionsExpanded = collapsePreferences.collapsedProjectIds.includes(project.id)
                ? false
                : collapsePreferences.expandedProjectIds.includes(project.id) || activeProjectId === project.id;
              const projectActive = activeProjectId === project.id && activeView === ViewType.PROJECT;
              const projectSessionsId = `sidebar-project-sessions-${project.id}`;
              return (
                <div key={project.id} className="mb-1">
                  <div className={`flex w-full items-center rounded-lg transition-colors ${projectActive ? 'bg-gray-200 text-gray-900' : 'text-gray-600 hover:bg-gray-100'}`}>
                    <button
                      type="button"
                      onClick={() => toggleProjectSessions(project.id, projectSessionsExpanded)}
                      aria-expanded={projectSessionsExpanded}
                      aria-controls={projectSessionsId}
                      aria-label={`${projectSessionsExpanded ? '折叠' : '展开'}“${project.name}”中的 ${projectSessions.length} 个会话`}
                      className="ml-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-gray-400 hover:bg-gray-200/70 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-300"
                    >
                      <CollapseChevron expanded={projectSessionsExpanded} />
                    </button>
                    <button
                      type="button"
                      onClick={() => selectProject(project.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 py-2 pl-0.5 pr-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gray-300"
                    >
                      <span className="text-sm">{project.archived_at ? '📦' : (projectSessionsExpanded ? '📂' : '📁')}</span>
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                        {project.name}{project.archived_at ? '（已归档）' : ''}
                      </span>
                      <span className="text-[10px] font-bold text-gray-400" aria-label={`${projectSessions.length} 个会话`}>
                        {projectSessions.length}
                      </span>
                    </button>
                  </div>
                  {projectSessionsExpanded ? (
                    <div id={projectSessionsId} className="ml-4 mt-1 space-y-0.5 border-l border-gray-200 pl-2">
                      {projectSessions.length === 0 ? (
                        <div className="px-2 py-2 text-[11px] text-gray-400">暂无会话</div>
                      ) : projectSessions.map(session => (
                        <div
                          key={session.id}
                          onClick={() => onSelectSession(session.id)}
                          className={`group flex cursor-pointer items-center rounded-lg px-2 py-1.5 ${activeSessionId === session.id ? 'bg-gray-200 text-gray-900' : 'text-gray-500 hover:bg-gray-100'}`}
                        >
                          <span className="min-w-0 flex-1 truncate text-xs font-medium">{session.title}</span>
                          <button
                            type="button"
                            onClick={(event) => { event.stopPropagation(); onDeleteSession(session.id); }}
                            className="p-1 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                            title="删除会话"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}

            {unavailableProjectSessions.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50/70 py-1">
                <div className="px-3 py-2 text-[10px] font-bold text-amber-700">项目列表暂不可用</div>
                {unavailableProjectSessions.map(session => (
                  <div
                    key={session.id}
                    onClick={() => onSelectSession(session.id)}
                    className={`group flex cursor-pointer items-center rounded-lg px-3 py-2 ${activeSessionId === session.id ? 'bg-amber-100 text-gray-900' : 'text-gray-600 hover:bg-amber-100/70'}`}
                  >
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">{session.title}</span>
                    <button
                      type="button"
                      onClick={(event) => { event.stopPropagation(); onDeleteSession(session.id); }}
                      className="p-1 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                      title="删除会话"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <button
          type="button"
          onClick={toggleUnassigned}
          aria-expanded={unassignedExpanded}
          aria-controls="sidebar-unassigned-sessions"
          className="flex w-full items-center gap-1.5 rounded-md px-2 pb-1 pt-4 text-left text-xs font-bold uppercase tracking-wider text-gray-500 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-300"
          title={unassignedExpanded ? '折叠对话' : '展开对话'}
        >
          <CollapseChevron expanded={unassignedExpanded} />
          <span>对话</span>
          <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] leading-none text-gray-500" aria-label={`${unassignedSessions.length} 个会话`}>
            {unassignedSessions.length}
          </span>
        </button>
        {unassignedExpanded ? (
          <div id="sidebar-unassigned-sessions">
            {unassignedSessions.length === 0 ? (
              <div className="px-3 py-3 text-xs italic text-gray-400">暂无会话</div>
            ) : unassignedSessions.map(session => (
              <div
                key={session.id}
                className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition-all ${activeSessionId === session.id ? 'bg-gray-200 text-gray-900' : 'text-gray-600 hover:bg-gray-100'}`}
                onClick={() => onSelectSession(session.id)}
              >
                <div className="min-w-0 flex-1 truncate text-sm font-medium">{session.title}</div>
                <button
                  type="button"
                  onClick={(event) => { event.stopPropagation(); onDeleteSession(session.id); }}
                  className="p-1 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                  title="删除会话"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {/* ---- Harness toggle (shrink-0) ---- */}
      <div className="px-6 py-2 shrink-0">
        <div className="w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold text-gray-500">
          <span>AI 后端</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-gray-50 p-0.5">
            {harnessOptions.map(option => (
              <button
                key={option.value}
                type="button"
                onClick={() => onHarnessChange(option.value)}
                title={option.label}
                aria-pressed={harness === option.value}
                className={`px-1.5 py-0.5 rounded text-[10px] font-bold transition-colors ${harness === option.value ? 'bg-blue-50 text-blue-700' : 'text-gray-400 hover:text-gray-600'}`}
              >
                {option.short}
              </button>
            ))}
          </span>
        </div>
      </div>

      {/* ---- Bottom: user section (shrink-0) ---- */}
      <div className="p-4 border-t border-gray-100 shrink-0">
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
