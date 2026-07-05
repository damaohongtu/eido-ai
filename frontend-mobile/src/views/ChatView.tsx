import React, { useEffect, useMemo, useRef, useState } from 'react';
import { NavBar } from 'antd-mobile';
import type { EidoStore } from '../hooks/useEidoStore';
import { useChatSend } from '../hooks/useChatSend';
import MessageItem from '../components/MessageItem';
import Composer from '../components/Composer';
import MenuIcon from '../components/MenuIcon';
import FilesPanel from '../components/FilesPanel';

const FolderIcon: React.FC = () => (
  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
    />
  </svg>
);

const ChatView: React.FC<{
  store: EidoStore;
  onOpenMenu: () => void;
  browserContext?: string;
  browserContextControl?: React.ReactNode;
}> = ({
  store,
  onOpenMenu,
  browserContext,
  browserContextControl,
}) => {
  const { activeSession, allSkills, harness, addMessage, updateMessage, createNewSession, currentUser } = store;
  const userName = currentUser?.username?.trim() || currentUser?.user_id;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [filesOpen, setFilesOpen] = useState(false);

  const { isTyping, send, stop } = useChatSend({
    session: activeSession,
    skills: allSkills,
    harness,
    addMessage,
    updateMessage,
    browserContext,
  });

  const activeSkill = useMemo(
    () => (activeSession?.skillId ? allSkills.find((s) => s.id === activeSession.skillId) : null),
    [activeSession?.skillId, allSkills]
  );

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [activeSession?.messages, isTyping]);

  if (!activeSession) {
    return (
      <div className="eido-mobile-chat-view flex h-full flex-col">
        <NavBar backArrow={<MenuIcon />} onBack={onOpenMenu} className="eido-mobile-nav border-b border-gray-100 bg-white">
          Eido
        </NavBar>
        <div className="eido-mobile-empty flex flex-1 flex-col items-center justify-center gap-4 px-8 text-center">
          <p className="text-gray-500">还没有进行中的会话</p>
          <button
            onClick={() => createNewSession()}
            className="rounded-full bg-gray-700 px-6 py-2.5 text-sm font-bold text-white"
          >
            新建对话
          </button>
          <button onClick={onOpenMenu} className="text-sm font-semibold text-gray-500">
            打开菜单
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="eido-mobile-chat-view flex h-full flex-col">
      <NavBar
        className="eido-mobile-nav border-b border-gray-100 bg-white"
        backArrow={<MenuIcon />}
        onBack={onOpenMenu}
        right={
          <div className="flex items-center justify-end gap-3">
            <button
              onClick={() => setFilesOpen(true)}
              className="text-gray-600 active:text-gray-900"
              title="会话文件"
            >
              <FolderIcon />
            </button>
            {/* <button onClick={() => createNewSession()} className="text-sm font-semibold text-gray-600">
              新对话
            </button> */}
          </div>
        }
      >
        <span className="block max-w-[60vw] truncate text-base font-bold">{activeSession.title}</span>
        {activeSkill && (
          <span className="block text-[11px] font-medium text-gray-400">
            {activeSkill.icon} {activeSkill.name}
          </span>
        )}
      </NavBar>

      <div ref={scrollRef} className="eido-mobile-message-list thin-scrollbar flex-1 space-y-5 overflow-y-auto bg-[#f5f5f5] px-3 py-4">
        {activeSession.messages.map((m, idx) => (
          <MessageItem
            key={m.id}
            message={m}
            sessionId={activeSession.id}
            isLast={idx === activeSession.messages.length - 1}
            isTyping={isTyping}
            userName={userName}
          />
        ))}
      </div>

      <Composer
        sessionId={activeSession.id}
        skills={allSkills}
        isTyping={isTyping}
        onSend={send}
        onStop={stop}
        browserContextControl={browserContextControl}
      />

      <FilesPanel sessionId={activeSession.id} visible={filesOpen} onClose={() => setFilesOpen(false)} />
    </div>
  );
};

export default ChatView;
