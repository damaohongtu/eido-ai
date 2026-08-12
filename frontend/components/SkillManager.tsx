import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Modal, Input, message } from 'antd';
import { Skill } from '../types';
import { api } from '../services/api';
import UploadSkillModal from './UploadSkillModal';

interface SkillManagerProps {
  onSelectSkill?: (skill: Skill) => void;
  onViewDetail: (skill: Skill) => void;
  onRefreshAppSkills?: () => void;
}

const SkillManager: React.FC<SkillManagerProps> = ({ onSelectSkill, onViewDetail, onRefreshAppSkills }) => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newSkillName, setNewSkillName] = useState('');
  const [creating, setCreating] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<any>(null);

  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const filteredSkills = useMemo(() => {
    if (!normalizedQuery) return skills;
    return skills.filter(skill => [
      skill.name,
      skill.description,
      skill.id,
      skill.owner_type,
      ...(skill.tools || []).flatMap(tool => [tool.name, tool.description]),
      ...(skill.agents || []).flatMap(agent => [agent.name, agent.description]),
    ].some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery)));
  }, [normalizedQuery, skills]);

  const loadSkills = async () => {
    setSkillsLoading(true);
    setSkillsError(null);
    try {
      const result = await api.getSkills({ limit: 100 });
      setSkills(result.items);
    } catch (err) {
      console.error('加载Skills列表失败:', err);
      setSkillsError('加载技能列表失败，请稍后重试');
    } finally {
      setSkillsLoading(false);
    }
  };

  useEffect(() => {
    loadSkills();
  }, []);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      event.preventDefault();
      searchInputRef.current?.focus();
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, []);

  const handleCreateSkill = async () => {
    const name = newSkillName.trim();
    if (!name) {
      message.warning('请输入技能名称');
      return;
    }
    setCreating(true);
    try {
      const newSkill = await api.createSkill({ name, description: '', content: '' });
      message.success('技能创建成功');
      setCreateModalOpen(false);
      setNewSkillName('');
      onRefreshAppSkills?.();
      loadSkills();
      onViewDetail(newSkill);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex-1 p-6 lg:p-8 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">我的技能</h1>
            <p className="text-sm text-gray-500 font-medium">选择技能开始专业分析工作流</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => { setNewSkillName(''); setCreateModalOpen(true); }}
              className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-bold rounded-lg hover:bg-gray-100 hover:border-gray-400 transition-colors"
            >
              新建技能
            </button>
            <button
              type="button"
              onClick={() => setUploadModalOpen(true)}
              className="px-4 py-2 bg-gray-700 text-white text-sm font-bold rounded-lg hover:bg-gray-800 transition-colors"
            >
              上传技能
            </button>
          </div>
        </div>

        <div className="mb-6">
          <Input
            ref={searchInputRef}
            allowClear
            size="large"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setSearchQuery('');
                (event.currentTarget as HTMLInputElement).blur();
              }
            }}
            prefix={
              <svg className="h-4 w-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-4.35-4.35m1.35-5.65a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            }
            suffix={!searchQuery ? <span className="rounded border border-gray-200 px-1.5 py-0.5 text-[10px] font-bold text-gray-400">/</span> : null}
            placeholder="搜索技能名称、描述或关联工具"
            aria-label="搜索我的技能"
          />
          {normalizedQuery && (
            <div className="mt-2 px-1 text-xs font-medium text-gray-400">
              找到 {filteredSkills.length} 个技能
            </div>
          )}
        </div>

        {skillsLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-500 mx-auto mb-4" />
              <p className="text-gray-500">加载技能列表中...</p>
            </div>
          </div>
        ) : skillsError ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="text-4xl mb-4 opacity-20">⚠️</div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">加载失败</h3>
            <p className="text-gray-500 mb-4">{skillsError}</p>
            <button
              type="button"
              onClick={() => loadSkills()}
              className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-800 transition-colors"
            >
              重试
            </button>
          </div>
        ) : filteredSkills.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white py-20 text-center">
            <div className="mb-3 text-3xl opacity-40">🔎</div>
            <h2 className="font-bold text-gray-800">没有匹配的技能</h2>
            <p className="mt-1 text-sm text-gray-500">尝试搜索技能名称、描述或关联工具</p>
            <button type="button" onClick={() => setSearchQuery('')} className="mt-4 text-sm font-bold text-gray-700 hover:underline">清空搜索</button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {filteredSkills.map((skill) => (
              <div
                key={skill.id}
                role="button"
                tabIndex={0}
                onClick={() => onViewDetail(skill)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onViewDetail(skill);
                  }
                }}
                className="bg-white rounded-xl border border-gray-200 p-5 cursor-pointer hover:border-gray-300 hover:bg-gray-50/50 transition-all text-left"
              >
                <h3 className="text-base font-bold text-gray-900 mb-2 leading-tight">{skill.name}</h3>
                <p className="text-sm text-gray-600 leading-relaxed line-clamp-2">{skill.description}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <UploadSkillModal
        visible={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        onSuccess={() => { loadSkills(); onRefreshAppSkills?.(); }}
      />

      <Modal
        title="新建技能"
        open={createModalOpen}
        onOk={handleCreateSkill}
        onCancel={() => { setCreateModalOpen(false); setNewSkillName(''); }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ disabled: !newSkillName.trim() }}
      >
        <div className="py-2">
          <label className="block text-sm font-medium text-gray-700 mb-2">请输入技能名称</label>
          <Input
            placeholder="例如：数据分析助手"
            value={newSkillName}
            onChange={(e) => setNewSkillName(e.target.value)}
            onPressEnter={handleCreateSkill}
            autoFocus
            maxLength={50}
          />
        </div>
      </Modal>
    </div>
  );
};

export default SkillManager;
