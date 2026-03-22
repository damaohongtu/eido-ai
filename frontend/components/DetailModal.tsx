import React from 'react';
import { Modal } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Tool, Agent } from '../types';

interface DetailModalProps {
  visible: boolean;
  onClose: () => void;
  item: Tool | Agent | null;
  type: 'tool' | 'agent';
}

const DetailModal: React.FC<DetailModalProps> = ({ visible, onClose, item, type }) => {
  if (!item) return null;

  const MarkdownComponents = {
    h1: ({ ...props }) => <h1 className="text-2xl font-black text-gray-900 mb-4 mt-6 first:mt-0 border-b-2 border-gray-400 pb-2" {...props} />,
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

  const isTool = type === 'tool';
  const tool = isTool ? (item as Tool) : null;
  const agent = !isTool ? (item as Agent) : null;

  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      className="detail-modal"
      styles={{
        body: { padding: 0 }
      }}
    >
      <div className="flex flex-col" style={{ maxHeight: '70vh' }}>
        {/* 头部信息 - 固定不滚动 */}
        <div className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-gray-200">
          <div className="flex items-start space-x-4">
            <div className="flex-shrink-0">
              <div className="w-16 h-16 rounded-2xl bg-gray-600 flex items-center justify-center text-3xl shadow-lg">
                {isTool ? tool?.icon : agent?.avatar}
              </div>
            </div>
            <div className="flex-1">
              <h2 className="text-2xl font-black text-gray-900 mb-1">
                {isTool ? tool?.name : agent?.name}
              </h2>
              <p className="text-gray-500 mb-2">
                {isTool ? tool?.description : agent?.description}
              </p>
              <div className="flex items-center space-x-2">
                <span className={`text-xs px-3 py-1 rounded-full font-bold ${
                  isTool 
                    ? 'bg-emerald-50 text-emerald-600' 
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  {isTool ? '工具' : 'Agent'}
                </span>
                <span className="text-xs px-3 py-1 rounded-full font-bold bg-slate-100 text-slate-600">
                  {isTool ? tool?.category : agent?.category}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Markdown内容 - 可滚动区域 */}
        <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar">
          <div className="markdown-body prose prose-slate max-w-none">
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              components={MarkdownComponents}
            >
              {item.detail || '暂无详细信息'}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default DetailModal;
