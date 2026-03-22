
import React, { useState, useMemo, useEffect } from 'react';
import { Tool } from '../types';
import { getAssetUrl } from '../config';
import DetailModal from './DetailModal';
import { api } from '../services/api';

const ToolMarket: React.FC<{ tools?: Tool[] }> = ({ tools: propTools }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [tools, setTools] = useState<Tool[]>(propTools || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 从后端加载工具列表
  useEffect(() => {
    const loadTools = async () => {
      // 如果传入了 tools props，则使用 props
      if (propTools && propTools.length > 0) {
        setTools(propTools);
        return;
      }

      setLoading(true);
      setError(null);
      
      try {
        const result = await api.getTools({
          limit: 100, // 获取所有工具
        });
        setTools(result.items);
      } catch (err) {
        console.error('加载工具列表失败:', err);
        setError('加载工具列表失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    };

    loadTools();
  }, [propTools]);

  const categories = useMemo(() => {
    const cats = Array.from(new Set(tools.map(t => t.category).filter(Boolean)));
    return cats.sort();
  }, [tools]);

  const filteredTools = useMemo(() => {
    return tools.filter(tool => {
      const matchesSearch = tool.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                           tool.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory = selectedCategory ? tool.category === selectedCategory : true;
      return matchesSearch && matchesCategory;
    });
  }, [tools, searchQuery, selectedCategory]);

  // 加载中状态
  if (loading) {
    return (
      <div className="flex-1 p-10 overflow-y-auto">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-500 mx-auto mb-4"></div>
              <p className="text-gray-500">加载工具列表中...</p>
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
              <h3 className="text-lg font-bold text-slate-900 mb-2">加载失败</h3>
              <p className="text-slate-500 mb-4">{error}</p>
              <button 
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
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
            <h1 className="text-3xl font-black text-slate-900">工具中心</h1>
            <p className="text-slate-500 font-medium">连接外部 API 和计算能力</p>
          </div>
          <div className="w-full md:w-80">
            <div className="relative">
              <input 
                type="text" 
                placeholder="搜索工具..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition-all outline-none"
              />
              <svg className="w-4 h-4 absolute left-3.5 top-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            </div>
          </div>
        </div>

        {/* Categories */}
        <div className="flex flex-wrap gap-2 mb-10">
          <button 
            onClick={() => setSelectedCategory(null)}
            className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${!selectedCategory ? 'bg-indigo-600 text-white shadow-md' : 'bg-white text-slate-500 hover:bg-slate-100 border border-slate-200'}`}
          >
            所有工具
          </button>
          {categories.map(cat => (
            <button 
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${selectedCategory === cat ? 'bg-indigo-600 text-white shadow-md' : 'bg-white text-slate-500 hover:bg-slate-100 border border-slate-200'}`}
            >
              {cat}
            </button>
          ))}
        </div>

        {filteredTools.length === 0 ? (
          <div className="py-20 text-center">
            <div className="text-4xl mb-4 opacity-20">🛠️</div>
            <h3 className="text-lg font-bold text-slate-400">没有找到符合条件的工具</h3>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {filteredTools.map(tool => {
              // Map tool names to image filenames
              const toolImageMap: Record<string, string> = {
                'Wolfram AIpha': 'Wolfram AIpha.png',
                'PDF 导出器': 'PDF 导出器.png',
                'Python 执行器': 'Python 执行器.png',
                '报告发布器': '报告发布器.png',
                '报告编辑器': '报告编辑器.png',
                'Google 搜索': 'Google 搜索.png',
                '知识库': '知识库.png',
                '研究分析师': '研究分析师.png',
                '科学查询': '科学查询.png',
                '通用助手': '通用助手.png'
              };
              const imageName = toolImageMap[tool.name] || '通用助手.png';
              
              return (
                <div 
                  key={tool.id} 
                  className="bg-white border border-slate-200 p-6 rounded-[1.5rem] hover:shadow-xl hover:shadow-slate-200/50 transition-all cursor-pointer group flex flex-col relative"
                  onClick={() => {
                    setSelectedTool(tool);
                    setModalVisible(true);
                  }}
                >
                  <div className="flex">
                    <div className="flex-shrink-0 mr-4">
                      <div className="rounded-lg p-1.5 flex items-center justify-center w-12 h-12">
                        <img
                          src={getAssetUrl(`/images/tools/${imageName}`)}
                          alt={tool.name}
                          className="w-9 h-9 object-contain"
                        />
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-bold text-gray-900 mb-1">{tool.name}</h3>
                      <p className="text-[10px] text-gray-500 font-medium leading-relaxed line-clamp-3">
                        {tool.description}
                      </p>
                    </div>
                  </div>
                  <div className="absolute bottom-3">
                    <div className="px-2 py-0.5 rounded text-[8px] bg-slate-50 text-slate-500 font-black border border-slate-200 tracking-wider uppercase">
                      {tool.category || '未分类'}
                    </div>
                  </div>
                </div>
              );
            })}

            {!searchQuery && !selectedCategory && (
              <div className="bg-white/50 border border-dashed border-slate-300 p-8 rounded-[2rem] flex flex-col items-center justify-center group cursor-pointer hover:bg-white transition-all text-center">
                 <span className="text-slate-400 group-hover:text-indigo-600 font-bold transition-colors">请求工具</span>
              </div>
            )}
          </div>
        )}
      </div>

      <DetailModal
        visible={modalVisible}
        onClose={() => {
          setModalVisible(false);
          setSelectedTool(null);
        }}
        item={selectedTool}
        type="tool"
      />
    </div>
  );
};

export default ToolMarket;
