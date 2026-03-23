/** 与后端 scheduler_service._parse_trigger 一致：interval:秒 或 5 段 cron */

import type { ScheduledTask } from '../types';

export type ScheduleMode = 'interval' | 'cron';

export function buildScheduleString(
  mode: ScheduleMode,
  cronExpression: string,
  intervalSeconds: number
): string {
  if (mode === 'interval') {
    const s = Math.max(1, Math.floor(intervalSeconds));
    return `interval:${s}`;
  }
  return cronExpression.trim();
}

export function parseSchedule(schedule: string): {
  mode: ScheduleMode;
  intervalSeconds: number;
  cron: string;
} {
  const s = schedule.trim();
  if (s.startsWith('interval:')) {
    const sec = parseInt(s.slice('interval:'.length), 10);
    return {
      mode: 'interval',
      intervalSeconds: Number.isFinite(sec) && sec > 0 ? sec : 3600,
      cron: '0 9 * * *',
    };
  }
  return { mode: 'cron', intervalSeconds: 3600, cron: s || '0 9 * * *' };
}

export function describeSchedule(schedule: string): string {
  const s = schedule.trim();
  if (s.startsWith('interval:')) {
    const sec = parseInt(s.slice('interval:'.length), 10);
    if (!Number.isFinite(sec) || sec <= 0) return s;
    if (sec % 86400 === 0) return `间隔：每 ${sec / 86400} 天`;
    if (sec % 3600 === 0) return `间隔：每 ${sec / 3600} 小时`;
    if (sec % 60 === 0) return `间隔：每 ${sec / 60} 分钟`;
    return `间隔：每 ${sec} 秒`;
  }
  return `Cron：${s}`;
}

export function intervalUnitToSeconds(amount: number, unit: 's' | 'm' | 'h' | 'd'): number {
  const n = Math.max(1, Math.floor(amount));
  switch (unit) {
    case 's':
      return n;
    case 'm':
      return n * 60;
    case 'h':
      return n * 3600;
    case 'd':
      return n * 86400;
    default:
      return n * 60;
  }
}

export function secondsToAmountAndUnit(seconds: number): { amount: number; unit: 's' | 'm' | 'h' | 'd' } {
  const s = Math.max(1, Math.floor(seconds));
  if (s % 86400 === 0) return { amount: s / 86400, unit: 'd' };
  if (s % 3600 === 0) return { amount: s / 3600, unit: 'h' };
  if (s % 60 === 0) return { amount: s / 60, unit: 'm' };
  return { amount: s, unit: 's' };
}

export function getChatPrompt(task: { type: string; params: ScheduledTask['params'] }): string {
  if (task.type !== 'chat') return '';
  const msgs = task.params?.messages;
  if (!Array.isArray(msgs) || msgs.length === 0) return '';
  const first = msgs[0];
  return typeof first?.content === 'string' ? first.content : '';
}
