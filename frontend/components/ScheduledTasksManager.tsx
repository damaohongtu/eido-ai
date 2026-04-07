import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import type { ScheduledTask } from '../types';
import { describeSchedule, getChatPrompt } from '../utils/scheduleTask';
import ScheduledTaskModal from './ScheduledTaskModal';

/**
 * 布局与「我的技能」(SkillManager) 一致：同外边距、max-w-6xl、标题行、md 三列卡片网格。
 */
const ScheduledTasksManager: React.FC = () => {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.listTasks();
      setTasks(list);
    } catch (e) {
      console.error(e);
      setError(e instanceof Error ? e.message : '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (t: ScheduledTask) => {
    if (t.type !== 'chat') {
      alert('当前仅支持编辑「对话类」自动任务');
      return;
    }
    setEditing(t);
    setModalOpen(true);
  };

  const handleModalSubmit = async (payload: {
    name: string;
    schedule: string;
    type: 'chat';
    params: { messages: { role: 'user'; content: string }[] };
  }) => {
    if (editing) {
      await api.updateTask(editing.id, {
        name: payload.name,
        schedule: payload.schedule,
        type: payload.type,
        params: payload.params,
      });
    } else {
      await api.createTask(payload);
    }
    await load();
  };

  const toggleEnabled = async (t: ScheduledTask) => {
    try {
      await api.updateTask(t.id, { enabled: !t.enabled });
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleDelete = async (e: React.MouseEvent, t: ScheduledTask) => {
    e.stopPropagation();
    if (!confirm(`确定删除任务「${t.name}」？`)) return;
    try {
      await api.deleteTask(t.id);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleRun = async (e: React.MouseEvent, t: ScheduledTask) => {
    e.stopPropagation();
    try {
      await api.runTaskNow(t.id);
      alert('已触发执行（后台运行）');
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : '触发失败');
    }
  };

  const cardSubtitle = (t: ScheduledTask) => {
    const scheduleLine = describeSchedule(t.schedule);
    const prompt = getChatPrompt(t);
    const preview = prompt ? (prompt.length > 80 ? `${prompt.slice(0, 80)}…` : prompt) : '（无提示词）';
    return `${scheduleLine}\n${preview}`;
  };

  return (
    <div className="flex-1 p-6 lg:p-8 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">自动任务</h1>
            <p className="text-sm text-gray-500 font-medium">定时执行对话任务，支持 Cron 与固定间隔</p>
          </div>
          <button
            type="button"
            onClick={openCreate}
            className="px-4 py-2 bg-gray-700 text-white text-sm font-bold rounded-lg hover:bg-gray-800 transition-colors"
          >
            添加任务
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-500 mx-auto mb-4" />
              <p className="text-gray-500">加载自动任务中...</p>
            </div>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="text-4xl mb-4 opacity-20">⚠️</div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">加载失败</h3>
            <p className="text-gray-500 mb-4">{error}</p>
            <button
              type="button"
              onClick={() => load()}
              className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-800 transition-colors"
            >
              重试
            </button>
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-20 text-gray-500 text-sm border border-dashed border-gray-200 rounded-xl">
            暂无自动任务，点击右上角「添加任务」创建
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {tasks.map((t) => (
              <div
                key={t.id}
                role="button"
                tabIndex={0}
                onClick={() => openEdit(t)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openEdit(t);
                  }
                }}
                className="bg-white rounded-xl border border-gray-200 p-5 cursor-pointer hover:border-gray-300 hover:bg-gray-50/50 transition-all text-left flex flex-col"
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="text-base font-bold text-gray-900 leading-tight flex-1 min-w-0">{t.name}</h3>
                  <div
                    className="shrink-0"
                    onClick={(e) => e.stopPropagation()}
                    onMouseDown={(e) => e.stopPropagation()}
                  >
                    <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={t.enabled}
                        onChange={() => void toggleEnabled(t)}
                      />
                      启用
                    </label>
                  </div>
                </div>
                <p className="text-sm text-gray-600 leading-relaxed line-clamp-4 whitespace-pre-line flex-1">
                  {cardSubtitle(t)}
                </p>
                {t.last_run_at ? (
                  <p className="text-[11px] text-gray-400 mt-2">
                    上次运行：{new Date(t.last_run_at).toLocaleString()}
                  </p>
                ) : null}
                <div
                  className="mt-4 pt-3 border-t border-gray-100 flex flex-wrap gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    onClick={(e) => handleRun(e, t)}
                    className="px-3 py-1.5 text-xs font-bold rounded-lg border border-gray-200 hover:bg-gray-50"
                  >
                    立即执行
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openEdit(t);
                    }}
                    className="px-3 py-1.5 text-xs font-bold rounded-lg border border-gray-200 hover:bg-gray-50"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, t)}
                    className="px-3 py-1.5 text-xs font-bold rounded-lg text-red-600 border border-red-100 hover:bg-red-50"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ScheduledTaskModal
        visible={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        editing={editing}
        onSuccess={load}
        onSubmit={handleModalSubmit}
      />
    </div>
  );
};

export default ScheduledTasksManager;
