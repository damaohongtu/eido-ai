
import React from 'react';
import { Skill } from '../types';
import { Input, Divider, Card } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { getAssetUrl } from '../config';

const { TextArea } = Input;

interface HomeViewProps {
  onStartSkill: (skillId?: string) => void;
  skills: Skill[];
}

const HomeView: React.FC<HomeViewProps> = ({ onStartSkill, skills }) => {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col items-center justify-start p-8 lg:p-12">
      <div className="max-w-5xl w-full">
        <header className="mb-12 text-center mt-[15vh]">
          <div className="inline-block p-4 bg-white rounded-[2rem] shadow-lg shadow-gray-200/50 mb-8 border border-gray-100">
            <svg className="w-10 h-10 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div> 
          <p className="text-gray-600 text-lg max-w-xl mx-auto font-medium leading-relaxed mb-4">
          How can I help you today?
          </p>
        </header>

        {/* Global Access Point */}
        <div className="relative mx-auto">
        <TextArea
          placeholder="发消息..."
          onClick={() => onStartSkill()}
          className="w-full bg-white border border-gray-200 rounded-2xl p-4 text-left text-gray-500 cursor-pointer hover:border-gray-300 hover:bg-gray-50 transition-all"
          autoSize={{ minRows: 3, maxRows: 6 }}
          readOnly
        />
        {/* 发送图标 - 绝对定位在右下角 */}
        <div
          className="absolute right-4 bottom-4 w-9 h-9 rounded-lg flex items-center justify-center text-gray-600 hover:text-gray-800 transition-colors cursor-pointer bg-white/80 backdrop-blur-sm"
          onClick={(e) => {
            e.stopPropagation();
            onStartSkill();
          }}
        >
          <SendOutlined className="text-lg" />
        </div>
        </div>
        </div>
    </div>
  );
};

export default HomeView;
