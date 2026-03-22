
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
          prefix={
            <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-500 group-hover:text-gray-700 transition-colors">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            </div>
          }
          suffix={
            <div className="flex items-center space-x-2">
              <span className="text-[9px] font-black text-gray-400 uppercase tracking-widest mr-2">快速开始</span>
              <kbd className="bg-gray-100 px-2 py-1 rounded text-[10px] font-black text-gray-500 border border-gray-200 shadow-sm">⌘ K</kbd>
            </div>
          }
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
