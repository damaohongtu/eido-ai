
import React, { useState, useRef, useMemo, useEffect } from 'react';
import { Skill, Tool, Agent, SkillAction } from '../types';
import { api } from '../services/api';
import { Input } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DetailModal from './DetailModal';

interface SkillEditorProps {
  skill: Skill | null;
  onSave: (skill: Skill) => void;
  onCancel: () => void;
}

const SkillEditor: React.FC<SkillEditorProps> = ({ skill, onSave, onCancel }) => {
  const isReadOnly = skill?.is_system || false;
  const [name, setName] = useState(skill?.name || '');
  const [icon, setIcon] = useState(skill?.icon || '⚡');
  const [blueprint, setBlueprint] = useState(skill?.detail || skill?.description || '');
  const [isFullscreen, setIsFullscreen] = useState(false);

  // 当 skill prop 变化时同步状态（用于切换编辑不同技能）
  useEffect(() => {
    setName(skill?.name || '');
    setIcon(skill?.icon || '⚡');
    setBlueprint(skill?.detail || skill?.description || '');
  }, [skill?.id, skill?.name, skill?.icon, skill?.detail, skill?.description]);
  const [showPreview, setShowPreview] = useState(true);
  const [selectedItem, setSelectedItem] = useState<Tool | Agent | null>(null);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [detailModalType, setDetailModalType] = useState<'tool' | 'agent'>('tool');
  
  // 从后端加载的工具和Agent
  const [allTools, setAllTools] = useState<Tool[]>([]);
  const [allAgents, setAllAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [mentionMenu, setMentionMenu] = useState<{ 
    visible: boolean; 
    filter: string; 
    index: number; 
    pos: { top: number; left: number };
  }>({
    visible: false,
    filter: '',
    index: 0,
    pos: { top: 0, left: 0 }
  });

  const blueprintRef = useRef<HTMLTextAreaElement>(null);
  const mentionListRef = useRef<HTMLDivElement>(null);

  // 加载工具和Agent
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const [toolsResult, agentsResult] = await Promise.all([
          api.getTools({ limit: 100 }),
          api.getAgents({ limit: 100 })
        ]);
        setAllTools(toolsResult.items);
        setAllAgents(agentsResult.items);
      } catch (error) {
        console.error('加载工具和Agent失败:', error);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  const allMentions = useMemo(() => [
    ...allAgents.map(a => ({ id: a.id, name: a.name, icon: a.icon || '🤖', type: 'Agent' as const })),
    ...allTools.map(t => ({ id: t.id, name: t.name, icon: t.icon || '🔧', type: 'Tool' as const }))
  ], [allAgents, allTools]);

  const filteredMentions = useMemo(() => {
    return allMentions.filter(m => 
      m.name.toLowerCase().includes(mentionMenu.filter.toLowerCase())
    );
  }, [allMentions, mentionMenu.filter]);

  const activeComponents = useMemo(() => {
    return allMentions.filter(m => blueprint.includes(`@${m.name}`));
  }, [blueprint, allMentions]);

  useEffect(() => {
    if (mentionMenu.visible && mentionListRef.current) {
      const activeItem = mentionListRef.current.children[mentionMenu.index] as HTMLElement;
      if (activeItem) {
        activeItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [mentionMenu.index, mentionMenu.visible]);

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (isReadOnly) return;
    const value = e.target.value;
    const cursorPosition = e.target.selectionStart || 0;
    const textBeforeCursor = value.slice(0, cursorPosition);
    const atMatch = textBeforeCursor.match(/@([\u4e00-\u9fa5\w]*)$/);

    if (atMatch) {
      const lines = textBeforeCursor.split('\n');
      const currentLine = lines.length;
      const charInLine = lines[lines.length - 1].length;
      
      setMentionMenu({ 
        visible: true, 
        filter: atMatch[1], 
        index: 0,
        pos: { 
          top: currentLine * 24 + 40, 
          left: charInLine * 8 + 20 
        }
      });
    } else {
      setMentionMenu(prev => ({ ...prev, visible: false }));
    }

    setBlueprint(value);
  };

  const insertMention = (mention: typeof allMentions[0]) => {
    if (isReadOnly) return;
    const ref = blueprintRef.current as HTMLTextAreaElement | null;
    if (!ref) return;
    
    const currentValue = ref.value || blueprint;
    const cursorPosition = ref.selectionStart ?? currentValue.length;
    const filterLength = mentionMenu.filter.length;

    let atPos = currentValue.lastIndexOf('@', Math.max(0, cursorPosition - 1));
    if (atPos === -1) atPos = currentValue.lastIndexOf('@');
    if (atPos === -1) return;

    const replaceEnd = Math.min(currentValue.length, atPos + 1 + filterLength);
    
    const newValue = currentValue.slice(0, atPos) + `@${mention.name} ` + currentValue.slice(replaceEnd);
    setBlueprint(newValue);
    setMentionMenu(prev => ({ ...prev, visible: false }));
    
    setTimeout(() => {
      ref.focus();
      const newPos = atPos + mention.name.length + 2; // @ + name + trailing space
      ref.setSelectionRange(newPos, newPos);
    }, 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isReadOnly) return;
    if (mentionMenu.visible) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionMenu(prev => ({ ...prev, index: (prev.index + 1) % (filteredMentions.length || 1) }));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionMenu(prev => ({ ...prev, index: (prev.index - 1 + (filteredMentions.length || 1)) % (filteredMentions.length || 1) }));
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (filteredMentions.length > 0) {
          e.preventDefault();
          insertMention(filteredMentions[mentionMenu.index]);
        }
      } else if (e.key === 'Escape') {
        setMentionMenu(prev => ({ ...prev, visible: false }));
      }
    }
  };

  const handleSave = () => {
    if (isReadOnly) {
      onCancel();
      return;
    }
    if (!name.trim() || !blueprint.trim()) return;

    const mentionedTools: typeof allTools = [];
    const mentionedAgents: typeof allAgents = [];

    allMentions.forEach(m => {
      if (blueprint.includes(`@${m.name}`)) {
        if (m.type === 'Tool') {
          const tool = allTools.find(t => t.id === m.id);
          if (tool) mentionedTools.push(tool);
        }
        if (m.type === 'Agent') {
          const agent = allAgents.find(a => a.id === m.id);
          if (agent) mentionedAgents.push(agent);
        }
      }
    });

    onSave({
      id: skill?.id || '',
      name,
      icon: icon || '⚡',
      description: blueprint,
      output_schema: skill?.output_schema,
      is_system: false,
      is_public: skill?.is_public || false,
      is_active: skill?.is_active !== false,
      version: skill?.version || 1,
      usage_count: skill?.usage_count || 0,
      user_id: skill?.user_id,
      created_at: skill?.created_at || new Date().toISOString(),
      updated_at: new Date().toISOString(),
      tools: mentionedTools.map((t, idx) => ({
        id: t.id,
        name: t.name,
        description: t.description,
        icon: t.icon,
        category: t.category,
        order: idx,
      })),
      agents: mentionedAgents.map((a, idx) => ({
        id: a.id,
        name: a.name,
        description: a.description,
        icon: a.icon,
        category: a.category,
        order: idx,
      })),
    });
  };

  const handleComponentClick = (mention: typeof allMentions[0]) => {
    if (mention.type === 'Tool') {
      const tool = allTools.find(t => t.id === mention.id);
      if (tool) {
        setSelectedItem(tool);
        setDetailModalType('tool');
        setDetailModalVisible(true);
      }
    } else {
      const agent = allAgents.find(a => a.id === mention.id);
      if (agent) {
        setSelectedItem(agent);
        setDetailModalType('agent');
        setDetailModalVisible(true);
      }
    }
  };

  // 加载中状态
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-slate-500">加载编辑器资源中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex-1 flex flex-col h-full text-slate-900 overflow-hidden ${isFullscreen ? 'fixed inset-0 z-[9999] bg-white' : ''}`}>
      <header className="h-20 border-b border-slate-100 px-10 flex items-center justify-between z-20">
        <div className="flex items-center space-x-6">
          <button onClick={onCancel} className="p-2.5 hover:bg-slate-50 rounded-2xl transition-all text-slate-400 hover:text-slate-600">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" /></svg>
          </button>
          <div className="flex items-center space-x-4">
            <div>
               <Input
                 size="large"
                 value={name}
                 onChange={e => setName(e.target.value)}
                 readOnly={isReadOnly}
                 placeholder="为技能命名..."
                 style={{width: "400px"}}
               />
            </div>
          </div>
        </div>
        <div className="flex items-center space-x-4">
          {/* 预览切换按钮 - 仅在非只读模式显示 */}
          {!isReadOnly && (
            <button 
              onClick={() => setShowPreview(!showPreview)}
              className="px-4 py-2.5 text-sm font-bold text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-xl transition-all flex items-center gap-2"
              title={showPreview ? "隐藏预览" : "显示预览"}
            >
              {showPreview ? (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                  隐藏预览
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                  显示预览
                </>
              )}
            </button>
          )}
          
          {/* 全屏切换按钮 - 仅在非只读模式显示 */}
          {!isReadOnly && (
            <button 
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="px-4 py-2.5 text-sm font-bold text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-xl transition-all flex items-center gap-2"
              title={isFullscreen ? "退出全屏" : "全屏模式"}
            >
              {isFullscreen ? (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  退出全屏
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                  </svg>
                  全屏
                </>
              )}
            </button>
          )}
          
          {!isReadOnly && <button onClick={onCancel} className="px-5 py-2.5 text-sm font-bold text-slate-400 hover:text-slate-600">取消</button>}
          <button 
            onClick={handleSave} 
            disabled={!isReadOnly && (!name.trim() || !blueprint.trim())} 
            className={`px-8 py-3 rounded-[1.2rem] font-bold transition-all shadow-xl active:scale-95 ${
              isReadOnly 
                ? 'bg-slate-100 text-slate-600 hover:bg-slate-200 shadow-none' 
                : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-indigo-600/20 disabled:bg-slate-100 disabled:text-slate-400'
            }`}
          >
            {isReadOnly ? '关闭查看' : '发布'}
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* 编辑器区域 - 仅在非只读模式显示 */}
        {!isReadOnly && (
          <div className={`flex flex-col relative bg-white border-r border-slate-50 transition-all ${showPreview ? (isFullscreen ? 'w-1/2' : 'flex-1') : 'flex-1'}`}>
            <div className="flex-1 p-12 overflow-y-auto custom-scrollbar relative">
              <div className="max-w-4xl mx-auto h-full flex flex-col">
                <div className="mb-8 flex items-center justify-between">
                  <label className="text-[11px] font-black text-indigo-500 uppercase tracking-[0.2em] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></span>
                    Markdown 编辑
                  </label>
                  <div className="text-[12px] text-slate-300 font-medium">
                    支持 Markdown 格式 | 使用 @ 链接组件
                  </div>
                </div>

                <div className="flex-1 relative font-mono">
                  <Input.TextArea
                    ref={blueprintRef}
                    value={blueprint}
                    onChange={handleTextChange}
                    onKeyDown={handleKeyDown}
                    placeholder={`在此定义你的工作流...

支持 Markdown 格式：
# 一级标题
## 二级标题
**粗体** *斜体*
- 列表项
1. 有序列表

使用 @ 链接智能体和工具`}
                    style={{ height: '100%', fontSize: '14px', lineHeight: '1.6' }}
                  />

                  {mentionMenu.visible && filteredMentions.length > 0 && (
                    <div 
                      className="absolute w-80 bg-white border border-slate-200 rounded-[2rem] shadow-2xl overflow-hidden z-[100] animate-in fade-in zoom-in-95 duration-100"
                      style={{ top: mentionMenu.pos.top + 10, left: mentionMenu.pos.left + 12 }}
                    >
                      <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50/50 text-[9px] font-black text-slate-400 uppercase tracking-widest flex justify-between">
                        <span>知识注入</span>
                        <span>{filteredMentions.length} 选项</span>
                      </div>
                      <div ref={mentionListRef} className="max-h-64 overflow-y-auto custom-scrollbar">
                        {filteredMentions.map((m, i) => (
                          <button 
                            key={m.id} 
                            onClick={() => insertMention(m)} 
                            className={`w-full flex items-center space-x-4 px-5 py-4 text-left transition-all ${mentionMenu.index === i ? 'bg-indigo-600 text-white' : 'hover:bg-slate-50 text-slate-700'}`}
                          >
                            <span className="text-2xl">{m.icon}</span>
                            <div className="flex-1 min-w-0">
                              <div className={`text-sm font-bold truncate ${mentionMenu.index === i ? 'text-white' : 'text-slate-900'}`}>{m.name}</div>
                              <div className={`text-[9px] font-black uppercase tracking-tighter ${mentionMenu.index === i ? 'text-indigo-200' : 'text-slate-400'}`}>{m.type}</div>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
            
            <div className="h-24 bg-slate-50/50 border-t border-slate-100 flex items-center px-12 space-x-8">
               <div className="text-[12px] font-black text-slate-400 uppercase tracking-widest">活动蓝图:</div>
               <div className="flex flex-wrap gap-3">
                 {activeComponents.length === 0 ? (
                   <span className="text-sm text-slate-300 italic">尚未链接工具或智能体...</span>
                 ) : (
                   activeComponents.map(m => (
                     <div 
                       key={m.id} 
                       className="flex items-center space-x-2 bg-white px-4 py-2 rounded-xl border border-slate-200 shadow-sm animate-in zoom-in-90 cursor-pointer hover:shadow-md hover:border-indigo-300 transition-all"
                       onClick={() => handleComponentClick(m)}
                     >
                        <span className="text-sm">{m.icon}</span>
                        <span className="text-[11px] font-bold text-slate-700">@{m.name}</span>
                        <span className={`text-[8px] px-1 rounded font-black uppercase ${m.type === 'Agent' ? 'bg-indigo-50 text-indigo-600' : 'bg-emerald-50 text-emerald-600'}`}>{m.type}</span>
                     </div>
                   ))
                 )}
               </div>
            </div>
          </div>
        )}

        {/* Markdown 预览区域 */}
        {(showPreview || isReadOnly) && (
          <div className={`flex flex-col relative bg-slate-50/50 transition-all ${
            isReadOnly 
              ? 'flex-1' 
              : (isFullscreen ? 'w-1/2' : 'w-[500px]')
          }`}>
            <div className="flex-1 p-12 overflow-y-auto custom-scrollbar">
              <div className="max-w-4xl mx-auto">
                <div className="mb-8 flex items-center justify-between">
                  <label className="text-[11px] font-black text-emerald-500 uppercase tracking-[0.2em] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    {isReadOnly ? '系统技能文档' : '实时预览'}
                  </label>
                  {isReadOnly && (
                    <span className="text-[10px] bg-indigo-100 text-indigo-700 px-3 py-1 rounded-full font-bold uppercase tracking-wider">
                      只读模式
                    </span>
                  )}
                </div>
                
                <div className="prose prose-slate max-w-none">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    className="markdown-preview"
                  >
                    {blueprint || '*预览将在此显示...*'}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
            
            {/* 只读模式下显示链接的组件 */}
            {isReadOnly && activeComponents.length > 0 && (
              <div className="h-24 bg-white/50 border-t border-slate-200 flex items-center px-12 space-x-8">
                <div className="text-[12px] font-black text-slate-400 uppercase tracking-widest">使用的组件:</div>
                <div className="flex flex-wrap gap-3">
                  {activeComponents.map(m => (
                    <div 
                      key={m.id} 
                      className="flex items-center space-x-2 bg-white px-4 py-2 rounded-xl border border-slate-200 shadow-sm cursor-pointer hover:shadow-md hover:border-indigo-300 transition-all"
                      onClick={() => handleComponentClick(m)}
                    >
                      <span className="text-sm">{m.icon}</span>
                      <span className="text-[11px] font-bold text-slate-700">@{m.name}</span>
                      <span className={`text-[8px] px-1 rounded font-black uppercase ${m.type === 'Agent' ? 'bg-indigo-50 text-indigo-600' : 'bg-emerald-50 text-emerald-600'}`}>{m.type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 侧边栏 - 仅在非全屏时显示 */}
        {!isFullscreen && (
          <aside className="w-[400px] bg-slate-50/30 p-12 overflow-y-auto custom-scrollbar">
             <div className="space-y-12">
               <section>
                  <h3 className="text-lg font-black text-slate-900 mb-4 tracking-tight">Eido 逻辑设计</h3>
                  <p className="text-sm text-slate-500 leading-relaxed font-medium">
                    {isReadOnly ? "这是预配置模板。你不能编辑它，但可以将其逻辑复制到新技能中。" : "Eido 中的技能是**涌现的**。你不需要配置步骤；你只需描述一个**蓝图**。"}
                  </p>
               </section>
               
               <section className="bg-white p-6 rounded-[2rem] border border-slate-100 shadow-sm">
                  <h4 className="text-[12px] font-black text-indigo-600 uppercase tracking-widest mb-3">人格注入</h4>
                  <p className="text-sm text-slate-400 leading-relaxed mb-4">
                    提及一个 <b>@智能体</b>（如 @研究分析师）会让 Eido 采用该人格的推理风格。
                  </p>
                  <h4 className="text-[12px] font-black text-emerald-600 uppercase tracking-widest mb-3">工具映射</h4>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    提及一个 <b>@工具</b>（如 @谷歌搜索）会在思考过程中赋予 Eido 该特定能力。
                  </p>
               </section>

               <section>
                  <h4 className="text-[12px] font-black text-slate-400 uppercase tracking-widest mb-4">Markdown 支持</h4>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    技能描述支持完整的 Markdown 语法，包括标题、列表、粗体、斜体等格式。使用全屏模式获得更大的编辑空间。
                  </p>
               </section>

               <section>
                  <h4 className="text-[12px] font-black text-slate-400 uppercase tracking-widest mb-4">结果生成</h4>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    提及工作区工具（如 <b>@报告编辑器</b>）将在成功的对话交互结束时自动生成可操作按钮。
                  </p>
               </section>
             </div>
          </aside>
        )}
      </div>

      <DetailModal
        visible={detailModalVisible}
        onClose={() => {
          setDetailModalVisible(false);
          setSelectedItem(null);
        }}
        item={selectedItem}
        type={detailModalType}
      />
    </div>
  );
};

export default SkillEditor;
