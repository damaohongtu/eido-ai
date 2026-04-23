import React, { useState } from 'react';
import { Modal } from 'antd';
import { FolderOutlined, DownOutlined, RightOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skill } from '../types';
import { api } from '../services/api';
import SkillFileBrowser from './SkillFileBrowser';

interface SkillDetailModalProps {
  visible: boolean;
  onClose: () => void;
  skill: Skill | null;
  onUseSkill?: (skill: Skill) => void;
  /** 删除用户上传技能成功后回调（用于刷新列表） */
  onDeleted?: () => void;
  /** 编辑用户上传技能 */
  onEdit?: (skill: Skill) => void;
}

const SkillDetailModal: React.FC<SkillDetailModalProps> = ({
  visible,
  onClose,
  skill,
  onUseSkill,
  onDeleted,
  onEdit,
}) => {
  const [deleting, setDeleting] = useState(false);
  const [filesExpanded, setFilesExpanded] = useState(false);

  if (!skill) return null;

  const MarkdownComponents = {
    h1: ({ ...props }) => <h1 className="text-2xl font-black text-gray-900 mb-4 mt-6 first:mt-0 border-b-2 border-gray-300 pb-2" {...props} />,
    h2: ({ ...props }) => <h2 className="text-xl font-bold text-gray-800 mb-3 mt-5 first:mt-0" {...props} />,
    h3: ({ ...props }) => <h3 className="text-lg font-bold text-gray-700 mb-2 mt-4" {...props} />,
    p: ({ ...props }) => <p className="text-gray-600 mb-3 leading-relaxed" {...props} />,
    ul: ({ ...props }) => <ul className="list-disc list-inside mb-3 space-y-1 text-gray-600" {...props} />,
    ol: ({ ...props }) => <ol className="list-decimal list-inside mb-3 space-y-1 text-gray-600" {...props} />,
    li: ({ ...props }) => <li className="ml-4" {...props} />,
    strong: ({ ...props }) => <strong className="font-bold text-gray-800" {...props} />,
    code: ({ ...props }) => <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-sm font-mono" {...props} />,
    pre: ({ ...props }) => <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-3 overflow-x-auto" {...props} />,
    blockquote: ({ ...props }) => <blockquote className="border-l-4 border-gray-400 pl-4 italic text-gray-600 my-3" {...props} />,
    hr: ({ ...props }) => <hr className="my-6 border-gray-200" {...props} />,
    table: ({ ...props }) => <table className="w-full border-collapse mb-3" {...props} />,
    th: ({ ...props }) => <th className="border border-gray-300 bg-gray-50 px-3 py-2 text-left font-bold text-gray-700" {...props} />,
    td: ({ ...props }) => <td className="border border-gray-300 px-3 py-2 text-gray-600" {...props} />,
  };

  const hasDetail = !!skill.detail;
  const content = skill.detail || skill.description;
  const canDelete = skill.is_system === false;
  const canEdit = skill.is_system === false && !!onEdit;

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
          onDeleted?.();
          onClose();
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

  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      width={640}
      className="detail-modal"
      styles={{ body: { padding: 0 } }}
    >
      <div className="flex flex-col" style={{ maxHeight: '70vh' }}>
        <div className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-1">{skill.name}</h2>
          {hasDetail && (
            <p className="text-sm text-gray-600 leading-relaxed line-clamp-2">{skill.description}</p>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar">
          <div className="markdown-body prose prose-gray max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MarkdownComponents}>
              {content}
            </ReactMarkdown>
          </div>
        </div>
        {/* 文件浏览器折叠区域 */}
        <div className="flex-shrink-0 border-t border-gray-100">
          <button
            type="button"
            onClick={() => setFilesExpanded(!filesExpanded)}
            className="w-full px-6 py-3 flex items-center gap-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <FolderOutlined className="text-amber-500" />
            <span className="font-medium">文件</span>
            {filesExpanded ? <DownOutlined className="text-xs ml-auto" /> : <RightOutlined className="text-xs ml-auto" />}
          </button>
          {filesExpanded && (
            <div className="px-6 pb-4" style={{ height: '400px' }}>
              <SkillFileBrowser
                skillId={skill.id}
                isSystem={skill.is_system}
                visible={filesExpanded}
              />
            </div>
          )}
        </div>
        {(onUseSkill || canDelete || canEdit) && (
          <div className="flex-shrink-0 px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex flex-col gap-2">
            {canEdit && (
              <button
                type="button"
                onClick={() => { onEdit(skill); onClose(); }}
                className="w-full py-2.5 border border-gray-200 text-gray-700 text-sm font-bold rounded-lg hover:bg-gray-100 transition-colors"
              >
                编辑此技能
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                disabled={deleting}
                onClick={handleDelete}
                className="w-full py-2.5 border border-red-200 text-red-700 text-sm font-bold rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
              >
                {deleting ? '删除中…' : '删除此技能'}
              </button>
            )}
            {onUseSkill && (
              <button
                type="button"
                onClick={() => { onUseSkill(skill); onClose(); }}
                className="w-full py-2.5 bg-gray-700 text-white text-sm font-bold rounded-lg hover:bg-gray-800 transition-colors"
              >
                使用此技能
              </button>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};

export default SkillDetailModal;
