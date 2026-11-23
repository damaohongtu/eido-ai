import { expect, test, type Page } from '@playwright/test';

export const now = '2026-11-22T12:00:00Z';
export const skill = {
  id: 'research',
  name: '研究助手',
  description: '整理资料与研究观点',
  detail: '# 研究助手\n\n帮助你完成研究。',
  icon: '✧',
  is_system: true,
  is_owner: false,
  is_active: true,
  is_public: true,
  version: 1,
  usage_count: 0,
  created_at: now,
  updated_at: now,
};
export const project = {
  id: 'project-1',
  name: '行业研究',
  description: '持续积累研究资料',
  instructions: '',
  archived_at: null,
  user_id: 'tester',
  context_revision: 1,
  session_count: 0,
  created_at: now,
  updated_at: now,
  last_activity_at: now,
};

export async function mockApi(page: Page, authenticated = true) {
  const sessions: any[] = [];
  const projects = [project];
  const skills: any[] = [{ ...skill }];
  const mcps: any[] = [];
  const tasks: any[] = [];
  let mcpConfig: any = { mcpServers: {} };
  const fileContents: Record<string, string> = { 'SKILL.md': '# 研究助手' };
  const directories: string[] = [];
  const chatRequests: any[] = [];
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/ai-eido/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/ai-eido/api/v1', '').replace(/\/$/, '');
    const body = ['POST', 'PUT', 'PATCH'].includes(request.method())
      ? request.postDataJSON.bind(request)
      : () => ({});
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, json: data });
    if (path === '/auth/me')
      return json(
        authenticated ? { user_id: 'tester', username: '测试用户' } : {},
        authenticated ? 200 : 401,
      );
    if (path === '/auth/providers')
      return json([
        { id: 'github', name: 'GitHub' },
        { id: 'cas', name: 'CAS' },
      ]);
    if (path === '/sandbox/warmup') return json({ ready: true });
    if (path === '/chat/models')
      return json({
        default: 'test-model',
        models: [
          {
            id: 'test-model',
            label: '测试模型',
            model: 'test',
            description: '',
          },
        ],
      });
    if (path === '/skills' && request.method() === 'POST') {
      const item = {
        ...skill,
        ...body(),
        id: 'owned-skill',
        is_system: false,
        is_owner: true,
        detail: body().content,
      };
      skills.push(item);
      return json(item);
    }
    if (path === '/skills/upload') {
      const item = {
        ...skill,
        id: 'imported-skill',
        name: '导入技能',
        is_system: false,
        is_owner: true,
      };
      skills.push(item);
      return json(item);
    }
    if (path === '/skills')
      return json({
        items: skills.filter(
          (s) =>
            !url.searchParams.has('is_system') ||
            s.is_system === (url.searchParams.get('is_system') === 'true'),
        ),
        total: skills.length,
      });
    if (/^\/skills\/(owned-skill|imported-skill)$/.test(path)) {
      const index = skills.findIndex((s) => s.id === path.split('/')[2]);
      if (request.method() === 'DELETE') {
        skills.splice(index, 1);
        return json({ deleted: true });
      }
      if (request.method() === 'PUT')
        Object.assign(skills[index], body(), { detail: body().content });
      return json(skills[index]);
    }
    if (path === '/skills/research') return json(skill);
    if (/^\/skills\/[^/]+\/files$/.test(path))
      return json([
        ...Object.keys(fileContents).map((path) => ({
          name: path,
          path,
          type: 'file',
        })),
        ...directories.map((path) => ({
          name: path,
          path,
          type: 'dir',
          children: [],
        })),
      ]);
    if (/^\/skills\/[^/]+\/files\/read$/.test(path))
      return json({
        content: fileContents[url.searchParams.get('path')!] || '',
      });
    if (/^\/skills\/[^/]+\/files\/write$/.test(path)) {
      fileContents[body().path] = body().content;
      return json({});
    }
    if (/^\/skills\/[^/]+\/files\/mkdir$/.test(path)) {
      directories.push(body().path);
      return json({});
    }
    if (/^\/skills\/[^/]+\/files\/delete$/.test(path)) {
      delete fileContents[url.searchParams.get('path')!];
      return json({});
    }
    if (path === '/projects') {
      if (request.method() === 'POST') {
        const p = { ...project, ...body(), id: 'project-2' };
        projects.push(p);
        return json(p);
      }
      return json(projects);
    }
    if (/^\/projects\/[^/]+\/files$/.test(path)) return json([]);
    if (path === '/sessions') {
      if (request.method() === 'POST') {
        const input = body();
        const s = {
          id: `session-${sessions.length + 1}`,
          user_id: 'tester',
          title: '新建会话',
          project_id: input.project_id,
          skill_id: input.skill_id,
          runtime_mode: 'agent',
          created_at: now,
          updated_at: now,
          messages: [],
        };
        sessions.push(s);
        return json(s);
      }
      return json(sessions);
    }
    if (/^\/sessions\/[^/]+$/.test(path)) {
      const s = sessions.find((item) => item.id === path.split('/')[2]);
      if (request.method() === 'PATCH') Object.assign(s, body());
      return json(s || {}, s ? 200 : 404);
    }
    if (path.startsWith('/chat/queue/'))
      return json({
        active: false,
        count: 0,
        items: [],
        steer_available: false,
      });
    if (path === '/chat/chat') {
      const input = body();
      chatRequests.push(input);
      const s = sessions.find((item) => item.id === input.session_id);
      s.messages.push(
        { ...input.messages[0], extra: {}, created_at: now },
        {
          id: input.assistant_message_id,
          role: 'assistant',
          content: '已经整理好研究要点。',
          extra: {},
          created_at: now,
        },
      );
      return route.fulfill({
        contentType: 'text/event-stream',
        body: 'data: {"type":"content","content":"已经整理好研究要点。"}\n\ndata: [DONE]\n\n',
      });
    }
    if (path === '/workspace/files') return json({ files: [] });
    if (path === '/tasks') {
      if (request.method() === 'POST') {
        const item = {
          ...body(),
          id: 'task-1',
          enabled: true,
          last_run_at: null,
          created_at: now,
          updated_at: now,
        };
        tasks.push(item);
        return json(item);
      }
      return json(tasks);
    }
    if (/^\/tasks\/[^/]+\/run$/.test(path)) {
      const session = {
        id: 'task-session',
        title: '[自动任务] 每日晨报',
        project_id: null,
        created_at: now,
        updated_at: now,
        messages: [
          {
            id: 'task-answer',
            role: 'assistant',
            content: '任务执行结果',
            extra: {},
            created_at: now,
          },
        ],
      };
      sessions.push(session);
      return json({ ok: true, session_id: session.id, session });
    }
    if (/^\/tasks\/[^/]+$/.test(path)) {
      const index = tasks.findIndex((t) => t.id === path.split('/')[2]);
      if (request.method() === 'DELETE') {
        tasks.splice(index, 1);
        return json({ deleted: true });
      }
      Object.assign(tasks[index], body());
      return json(tasks[index]);
    }
    if (path === '/mcp/servers') {
      if (request.method() === 'POST') {
        const data = body();
        const item = {
          id: 'mcp-1',
          name: data.name,
          transport: data.transport,
          enabled: data.enabled,
          config: {
            url: data.url,
            headers: data.headers,
            command: data.command,
            args: data.args,
            env: data.env,
          },
        };
        mcps.push(item);
        return json(item);
      }
      return json(mcps);
    }
    if (/^\/mcp\/servers\/[^/]+$/.test(path)) {
      const index = mcps.findIndex((m) => m.id === path.split('/')[3]);
      if (request.method() === 'DELETE') {
        mcps.splice(index, 1);
        return json({ deleted: true });
      }
      const data = body();
      Object.assign(mcps[index], {
        name: data.name,
        transport: data.transport,
        enabled: data.enabled,
        config: {
          url: data.url,
          headers: data.headers,
          command: data.command,
          args: data.args,
          env: data.env,
        },
      });
      return json(mcps[index]);
    }
    if (path === '/mcp/status')
      return json(
        mcps.map((m) => ({
          ...m,
          target: m.config.url || m.config.command,
          status: m.enabled ? 'connected' : 'disabled',
          tools: [],
          tool_count: 0,
        })),
      );
    if (path === '/mcp/config') {
      if (request.method() === 'PUT') {
        mcpConfig = body();
        mcps.splice(
          0,
          mcps.length,
          ...Object.entries(mcpConfig.mcpServers).map(
            ([name, config]: [string, any]) => ({
              id: name,
              name,
              transport: config.type,
              enabled: !config.disabled,
              config,
            }),
          ),
        );
      }
      return json(mcpConfig);
    }
    if (path === '/search') return json({ projects, sessions: [] });
    if (path === '/auth/api-key') return json({ api_key: 'test-api-key' });
    return json({ detail: `Unmocked ${path}` }, 404);
  });
  return {
    chatRequests,
    errors,
    sessions,
    skills,
    mcps,
    tasks,
    fileContents,
    directories,
  };
}
