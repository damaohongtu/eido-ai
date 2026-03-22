
import React, { useState, useMemo, useEffect } from 'react';
import { Agent } from '../types';
import { getAssetUrl } from '../config';
import DetailModal from './DetailModal';
import { api } from '../services/api';

const AgentMarket: React.FC<{ agents?: Agent[] }> = ({ agents: propAgents }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [agents, setAgents] = useState<Agent[]>(propAgents || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 从后端加载Agent列表
  useEffect(() => {
    const loadAgents = async () => {
      // 如果传入了 agents props，则使用 props
      if (propAgents && propAgents.length > 0) {
        setAgents(propAgents);
        return;
      }

      setLoading(true);
      setError(null);
      
      try {
        const result = await api.getAgents({
          limit: 100, // 获取所有Agent
        });
        setAgents(result.items);
      } catch (err) {
        console.error('加载Agent列表失败:', err);
        setError('加载Agent列表失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    };

    loadAgents();
  }, [propAgents]);

  const categories = useMemo(() => {
    const cats = Array.from(new Set(agents.map(a => a.category).filter(Boolean)));
    return cats.sort();
  }, [agents]);

  const filteredAgents = useMemo(() => {
    return agents.filter(agent => {
      const matchesSearch = agent.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                           agent.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory = selectedCategory ? agent.category === selectedCategory : true;
      return matchesSearch && matchesCategory;
    });
  }, [agents, searchQuery, selectedCategory]);

  // 加载中状态
  if (loading) {
    return (
      <div className="flex-1 p-10 overflow-y-auto">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-500 mx-auto mb-4"></div>
              <p className="text-gray-500">加载Agent列表中...</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 错误状态
  if (error) {
    return (
      <div className="flex-1 p-10 overflow-y-auto">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="text-4xl mb-4 opacity-20">⚠️</div>
              <h3 className="text-lg font-bold text-gray-900 mb-2">加载失败</h3>
              <p className="text-gray-500 mb-4">{error}</p>
              <button 
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-800 transition-colors"
              >
                重新加载
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 p-10 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-end justify-between mb-10 gap-6">
          <div className="flex-1">
            <h1 className="text-3xl font-black text-gray-900">Agent市场</h1>
            <p className="text-gray-500 font-medium">为你的工作流部署自主专家</p>
          </div>
          <div className="w-full md:w-80">
            <div className="relative">
              <input 
                type="text" 
                placeholder="搜索智能体..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-gray-200 focus:border-gray-400 transition-all outline-none"
              />
              <svg className="w-4 h-4 absolute left-3.5 top-3.5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            </div>
          </div>
        </div>

        {/* Categories */}
        <div className="flex flex-wrap gap-2 mb-10">
          <button 
            onClick={() => setSelectedCategory(null)}
            className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${!selectedCategory ? 'bg-gray-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'}`}
          >
            所有智能体
          </button>
          {categories.map(cat => (
            <button 
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${selectedCategory === cat ? 'bg-gray-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'}`}
            >
              {cat}
            </button>
          ))}
        </div>

        {filteredAgents.length === 0 ? (
          <div className="py-20 text-center">
            <div className="text-4xl mb-4 opacity-20">🔍</div>
            <h3 className="text-lg font-bold text-gray-500">没有找到符合条件的智能体</h3>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {filteredAgents.map(agent => {
              // Map agent category to image filename
              const categoryImageMap: Record<string, string> = {
                '技术': '代码大师.png',
                '学术': '研究分析师.png',
                '通用': '通用助手.png'
              };
              const imageName = categoryImageMap[agent.category] || '通用助手.png';
              
              return (
                <div 
                  key={agent.id} 
                  className="group bg-white border border-gray-200 rounded-[1.75rem] p-6 hover:border-gray-300 hover:shadow-lg hover:bg-gray-50/30 transition-all relative cursor-pointer"
                  onClick={() => {
                    setSelectedAgent(agent);
                    setModalVisible(true);
                  }}
                >
                  <div className="flex items-start space-x-6">
                    <div className="flex-shrink-0">
                      <img
                        src={getAssetUrl(`/images/agent/${imageName}`)}
                        alt={agent.name}
                        className="w-12 h-12 rounded-2xl object-cover shadow-md group-hover:scale-110 transition-transform"
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-lg font-bold text-gray-900 mb-1">{agent.name}</h3>
                      <p className="text-gray-500 text-xs font-medium leading-relaxed mb-2 line-clamp-3">
                        {agent.description}
                      </p>
                      <div className="flex items-center space-x-2 text-[9px] text-gray-500 uppercase tracking-widest font-black">
                        <span>能力:</span>
                        <span className="text-gray-600">{agent.category || '未分类'}</span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            
            {/* Marketplace Empty Slot */}
            {!searchQuery && !selectedCategory && (
              <div className="bg-white/50 border border-dashed border-gray-300 rounded-[2.5rem] p-8 flex flex-col items-center justify-center text-center opacity-60 hover:opacity-100 transition-opacity">
                <div className="w-16 h-16 rounded-full border-2 border-gray-200 flex items-center justify-center text-2xl mb-4 text-gray-400">+</div>
                <div className="text-gray-500 font-black uppercase tracking-wider text-xs">发布你的智能体</div>
                <div className="text-[11px] text-gray-500 mt-2 font-medium">即将登陆市场</div>
              </div>
            )}
          </div>
        )}
      </div>

      <DetailModal
        visible={modalVisible}
        onClose={() => {
          setModalVisible(false);
          setSelectedAgent(null);
        }}
        item={selectedAgent}
        type="agent"
      />
    </div>
  );
};

export default AgentMarket;
