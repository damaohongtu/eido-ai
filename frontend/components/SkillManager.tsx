import React, { useState, useEffect } from 'react';
import { Skill } from '../types';
import { api } from '../services/api';
import SkillDetailModal from './SkillDetailModal';
import UploadSkillModal from './UploadSkillModal';

interface SkillManagerProps {
  onSelectSkill?: (skill: Skill) => void;
}

const SkillManager: React.FC<SkillManagerProps> = ({ onSelectSkill }) => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);

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

  return (
    <div className="flex-1 p-6 lg:p-8 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">我的技能</h1>
            <p className="text-sm text-gray-500 font-medium">选择技能开始专业分析工作流</p>
          </div>
          <button
            type="button"
            onClick={() => setUploadModalOpen(true)}
            className="px-4 py-2 bg-gray-700 text-white text-sm font-bold rounded-lg hover:bg-gray-800 transition-colors"
          >
            上传技能
          </button>
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
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {skills.map((skill) => (
              <div
                key={skill.id}
                role="button"
                tabIndex={0}
                onClick={() => setDetailSkill(skill)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setDetailSkill(skill);
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

      <SkillDetailModal
        visible={!!detailSkill}
        onClose={() => setDetailSkill(null)}
        skill={detailSkill}
        onUseSkill={onSelectSkill}
        onDeleted={loadSkills}
      />
      <UploadSkillModal
        visible={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        onSuccess={loadSkills}
      />
    </div>
  );
};

export default SkillManager;
