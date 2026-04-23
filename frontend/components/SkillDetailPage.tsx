import React, { useState, useEffect } from 'react';
import { Tabs, Button, Modal, message, Spin } from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skill } from '../types';
import { api } from '../services/api';
import SkillFileBrowser from './SkillFileBrowser';

interface SkillDetailPageProps {
  skill: Skill;
  onBack: () => void;
  onUseSkill: (skill: Skill) => void;
  onEdit: (skill: Skill) => void;
  onDeleted: () => void;
}

const MarkdownComponents = {
  h1: ({ ...props }: any) => <h1 className="text-2xl font-black text-gray-900 mb-4 mt-6 first:mt-0 border-b-2 border-gray-300 pb-2" {...props} />,
  h2: ({ ...props }: any) => <h2 className="text-xl font-bold text-gray-800 mb-3 mt-5 first:mt-0" {...props} />,
  h3: ({ ...props }: any) => <h3 className="text-lg font-bold text-gray-700 mb-2 mt-4" {...props} />,
  p: ({ ...props }: any) => <p className="text-gray-600 mb-3 leading-relaxed" {...props} />,
  ul: ({ ...props }: any) => <ul className="list-disc list-inside mb-3 space-y-1 text-gray-600" {...props} />,
  ol: ({ ...props }: any) => <ol className="list-decimal list-inside mb-3 space-y-1 text-gray-600" {...props} />,
  li: ({ ...props }: any) => <li className="ml-4" {...props} />,
  strong: ({ ...props }: any) => <strong className="font-bold text-gray-800" {...props} />,
  code: ({ ...props }: any) => <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-sm font-mono" {...props} />,
  pre: ({ ...props }: any) => <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-3 overflow-x-auto" {...props} />,
  blockquote: ({ ...props }: any) => <blockquote className="border-l-4 border-gray-400 pl-4 italic text-gray-600 my-3" {...props} />,
  hr: ({ ...props }: any) => <hr className="my-6 border-gray-200" {...props} />,
  table: ({ ...props }: any) => <table className="w-full border-collapse mb-3" {...props} />,
  th: ({ ...props }: any) => <th className="border border-gray-300 bg-gray-50 px-3 py-2 text-left font-bold text-gray-700" {...props} />,
  td: ({ ...props }: any) => <td className="border border-gray-300 px-3 py-2 text-gray-600" {...props} />,
};

const SkillDetailPage: React.FC<SkillDetailPageProps> = ({
  skill: initialSkill,
  onBack,
  onUseSkill,
  onEdit,
  onDeleted,
}) => {
  const [skill, setSkill] = useState<Skill>(initialSkill);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [activeTab, setActiveTab] = useState('docs');

  const isSystem = skill.is_system;
  const canEdit = !isSystem;
  const canDelete = !isSystem;

  useEffect(() => {
    const loadDetail = async () => {
      setLoading(true);
      try {
        const detail = await api.getSkill(initialSkill.id);
        setSkill(detail);
      } catch (err) {
        console.error('加载技能详情失败:', err);
        message.error('加载技能详情失败');
        // fallback to initial skill data
        setSkill(initialSkill);
      } finally {
        setLoading(false);
      }
    };
    loadDetail();
  }, [initialSkill.id]);

  const handleDelete = () => {
    Modal.confirm({
      title: '删除技能',
      content: `确定删除「${skill.name}」？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setDeleting(true);
        try {
          await api.deleteSkill(skill.id);
          message.success('技能删除成功');
          onDeleted();
        } catch (e) {
          const msg = e instanceof Error ? e.message : '删除失败';
          Modal.error({ title: '删除失败', content: msg });
          throw e;
        } finally {
          setDeleting(false);
        }
      },
    });
  };

  const content = skill.detail || skill.description;

  const tabItems = [
    {
      key: 'docs',
      label: '技能说明',
      children: (
        <div className="markdown-body prose prose-gray max-w-none py-4">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MarkdownComponents}>
            {content}
          </ReactMarkdown>
        </div>
      ),
    },
    {
      key: 'files',
      label: '文件管理',
      children: (
        <div className="py-4" style={{ height: '600px' }}>
          <SkillFileBrowser
            skillId={skill.id}
            isSystem={skill.is_system}
            visible={activeTab === 'files'}
          />
        </div>
      ),
    },
  ];

  return (
    <div className="flex-1 p-6 lg:p-8 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <button
              onClick={onBack}
              className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-xl text-gray-500 hover:text-gray-800 transition-all font-bold text-sm"
            >
              <ArrowLeftOutlined />
              <span>返回</span>
            </button>
            <div className="flex items-center gap-3">
              <span className="text-3xl">{skill.icon || '⚡'}</span>
              <div>
                <h1 className="text-2xl font-black text-gray-900 tracking-tight">{skill.name}</h1>
                <p className="text-sm text-gray-500 font-medium">{skill.description}</p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {canEdit && (
              <Button
                icon={<EditOutlined />}
                onClick={() => onEdit(skill)}
                className="font-bold"
              >
                编辑
              </Button>
            )}
            {canDelete && (
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={handleDelete}
                loading={deleting}
                className="font-bold"
              >
                删除
              </Button>
            )}
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={() => onUseSkill(skill)}
              className="bg-gray-700 hover:bg-gray-800 font-bold"
            >
              使用此技能
            </Button>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <Spin size="large" className="mb-4" />
              <p className="text-gray-500">加载技能详情中...</p>
            </div>
          </div>
        ) : (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            className="skill-detail-tabs"
          />
        )}
      </div>
    </div>
  );
};

export default SkillDetailPage;

