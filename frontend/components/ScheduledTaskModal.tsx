import React, { useEffect, useState } from 'react';
import type { ScheduledTask } from '../types';
import {
  buildScheduleString,
  parseSchedule,
  intervalUnitToSeconds,
  secondsToAmountAndUnit,
  type ScheduleMode,
} from '../utils/scheduleTask';

export interface ScheduledTaskModalProps {
  visible: boolean;
  onClose: () => void;
  /** 传入则编辑，否则新建（仅支持 chat） */
  editing: ScheduledTask | null;
  onSuccess: () => void;
  onSubmit: (payload: {
    name: string;
    schedule: string;
    type: 'chat';
    params: { messages: { role: 'user'; content: string }[] };
  }) => Promise<void>;
}

const ScheduledTaskModal: React.FC<ScheduledTaskModalProps> = ({
  visible,
  onClose,
  editing,
  onSuccess,
  onSubmit,
}) => {
  const [name, setName] = useState('');
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>('interval');
  const [cronExpr, setCronExpr] = useState('0 9 * * *');
  const [intervalAmount, setIntervalAmount] = useState(60);
  const [intervalUnit, setIntervalUnit] = useState<'s' | 'm' | 'h' | 'd'>('m');
  const [prompt, setPrompt] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    setFormError(null);
    if (editing) {
      setName(editing.name);
      const p = parseSchedule(editing.schedule);
      setScheduleMode(p.mode);
      setCronExpr(p.cron);
      if (p.mode === 'interval') {
        const { amount, unit } = secondsToAmountAndUnit(p.intervalSeconds);
        setIntervalAmount(amount);
        setIntervalUnit(unit);
      }
      const msgs = editing.params?.messages;
      const content =
        Array.isArray(msgs) && msgs[0] && typeof msgs[0].content === 'string'
          ? msgs[0].content
          : '';
      setPrompt(content);
    } else {
      setName('');
      setScheduleMode('interval');
      setCronExpr('0 9 * * *');
      setIntervalAmount(60);
      setIntervalUnit('m');
      setPrompt('');
    }
  }, [visible, editing]);

  if (!visible) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const n = name.trim();
    if (!n) {
      setFormError('请填写任务名称');
      return;
    }
    const p = prompt.trim();
    if (!p) {
      setFormError('请填写任务提示词');
      return;
    }
    if (scheduleMode === 'cron') {
      const parts = cronExpr.trim().split(/\s+/);
      if (parts.length < 5) {
        setFormError('Cron 需 5 段：分 时 日 月 周（空格分隔）');
        return;
      }
    }

    const intervalSeconds =
      scheduleMode === 'interval' ? intervalUnitToSeconds(intervalAmount, intervalUnit) : 0;
    const schedule = buildScheduleString(scheduleMode, cronExpr, intervalSeconds);

    setSaving(true);
    try {
      await onSubmit({
        name: n,
        schedule,
        type: 'chat',
        params: { messages: [{ role: 'user', content: p }] },
      });
      onSuccess();
      onClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/40">
      <div
        className="bg-white rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scheduled-task-modal-title"
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 id="scheduled-task-modal-title" className="text-lg font-black text-gray-900">
            {editing ? '编辑自动任务' : '添加自动任务'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg text-gray-500 hover:bg-gray-100"
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {formError ? (
            <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{formError}</div>
          ) : null}

          <div>
            <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">
              任务名称
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-gray-300 outline-none"
              placeholder="例如：每日晨报"
            />
          </div>

          <div>
            <span className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
              触发方式
            </span>
            <div className="flex gap-4 mb-3">
              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="radio"
                  name="sched"
                  checked={scheduleMode === 'interval'}
                  onChange={() => setScheduleMode('interval')}
                />
                按间隔
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="radio"
                  name="sched"
                  checked={scheduleMode === 'cron'}
                  onChange={() => setScheduleMode('cron')}
                />
                Cron
              </label>
            </div>

            {scheduleMode === 'interval' ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-gray-600">每</span>
                <input
                  type="number"
                  min={1}
                  value={intervalAmount}
                  onChange={(e) => setIntervalAmount(parseInt(e.target.value, 10) || 1)}
                  className="w-20 border border-gray-200 rounded-lg px-2 py-1.5 text-sm"
                />
                <select
                  value={intervalUnit}
                  onChange={(e) => setIntervalUnit(e.target.value as 's' | 'm' | 'h' | 'd')}
                  className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm"
                >
                  <option value="s">秒</option>
                  <option value="m">分钟</option>
                  <option value="h">小时</option>
                  <option value="d">天</option>
                </select>
                <span className="text-xs text-gray-400">执行一次</span>
              </div>
            ) : (
              <div>
                <input
                  type="text"
                  value={cronExpr}
                  onChange={(e) => setCronExpr(e.target.value)}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm font-mono"
                  placeholder="分 时 日 月 周  例：0 9 * * *"
                />
                <p className="text-xs text-gray-400 mt-1">5 段 Linux cron，与 APScheduler 一致</p>
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">
              任务提示词
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={6}
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-gray-300 outline-none resize-y min-h-[120px]"
              placeholder="定时发送给 AI 的完整指令，将按对话方式执行…"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-bold text-gray-600 rounded-xl hover:bg-gray-100"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm font-bold text-white bg-gray-800 rounded-xl hover:bg-gray-900 disabled:opacity-50"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ScheduledTaskModal;
