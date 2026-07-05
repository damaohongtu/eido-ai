import React, { useMemo, useState } from 'react';
import { NavBar, SearchBar, Tabs, Dialog } from 'antd-mobile';
import type { EidoStore } from '../hooks/useEidoStore';
import type { Skill } from '../shared';
import MenuIcon from '../components/MenuIcon';

const SkillCard: React.FC<{
  skill: Skill;
  onUse: () => void;
  onDetail: () => void;
}> = ({ skill, onUse, onDetail }) => (
  <div className="eido-mobile-skill-card flex items-center gap-3 rounded-2xl border border-gray-200 bg-white p-3.5 shadow-sm">
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-2xl">
      {skill.icon || '🧩'}
    </span>
    <button onClick={onDetail} className="min-w-0 flex-1 text-left">
      <div className="truncate text-[15px] font-bold text-gray-800">{skill.name}</div>
      <div className="line-clamp-1 text-xs text-gray-400">
        {(skill.description || '').replace(/[#*`>\-]/g, '').slice(0, 50)}
      </div>
    </button>
    <button
      onClick={onUse}
      className="shrink-0 rounded-full bg-gray-700 px-4 py-1.5 text-xs font-bold text-white active:bg-gray-800"
    >
      使用
    </button>
  </div>
);

const SkillsView: React.FC<{ store: EidoStore; onOpenMenu: () => void }> = ({ store, onOpenMenu }) => {
  const { systemSkills, userSkills, createNewSession } = store;
  const [keyword, setKeyword] = useState('');
  const [tab, setTab] = useState('system');

  const list = tab === 'system' ? systemSkills : userSkills;
  const filtered = useMemo(
    () => list.filter((s) => s.name.toLowerCase().includes(keyword.toLowerCase())),
    [list, keyword]
  );

  const showDetail = (skill: Skill) => {
    Dialog.show({
      title: `${skill.icon || '🧩'} ${skill.name}`,
      content: (
        <div className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-gray-600">
          {skill.description || '暂无描述'}
        </div>
      ),
      closeOnAction: true,
      actions: [
        [
          { key: 'close', text: '关闭' },
          { key: 'use', text: '使用该技能', bold: true, onClick: () => createNewSession(skill.id) },
        ],
      ],
    });
  };

  return (
    <div className="flex h-full flex-col">
      <NavBar backArrow={<MenuIcon />} onBack={onOpenMenu} className="eido-mobile-nav border-b border-gray-100 bg-white">
        技能广场
      </NavBar>
      <div className="eido-mobile-search-block bg-white px-3 pb-2 pt-1">
        <SearchBar placeholder="搜索技能" value={keyword} onChange={setKeyword} />
      </div>
      <Tabs activeKey={tab} onChange={setTab} className="bg-white">
        <Tabs.Tab title={`系统技能 ${systemSkills.length}`} key="system" />
        <Tabs.Tab title={`我的技能 ${userSkills.length}`} key="user" />
      </Tabs>

      <div className="eido-mobile-skill-list thin-scrollbar flex-1 space-y-3 overflow-y-auto bg-[#f5f5f5] p-3">
        {filtered.length === 0 ? (
          <div className="pt-20 text-center text-sm text-gray-400">没有匹配的技能</div>
        ) : (
          filtered.map((s) => (
            <SkillCard
              key={s.id}
              skill={s}
              onUse={() => createNewSession(s.id)}
              onDetail={() => showDetail(s)}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default SkillsView;
