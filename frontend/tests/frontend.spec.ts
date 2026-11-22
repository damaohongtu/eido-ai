import { expect, test, type Page } from '@playwright/test';

const now = '2026-11-22T12:00:00Z';
const skill = {
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
const project = {
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

async function mockApi(page: Page, authenticated = true) {
  const sessions: any[] = [];
  const projects = [project];
  const skills: any[] = [{ ...skill }];
  const mcps: any[] = [];
  const tasks: any[] = [];
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
    if (path === '/skills/research/files')
      return json([{ name: 'SKILL.md', path: 'SKILL.md', type: 'file' }]);
    if (path === '/skills/research/files/read')
      return json({ content: '# 研究助手' });
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
    if (path === '/mcp/config') return json({ mcpServers: {} });
    return json({ detail: `Unmocked ${path}` }, 404);
  });
  return { chatRequests, errors, sessions, skills, mcps, tasks };
}

test('opens the existing PC application and streams a conversation', async ({
  page,
}, info) => {
  test.skip(info.project.name !== 'pc');
  const mock = await mockApi(page);
  await page.goto('/ai-eido/');
  await expect(page.getByText('How can I help you today?')).toBeVisible();
  await page.getByText('新建会话', { exact: true }).first().click();
  const input = page.locator('textarea').first();
  await input.fill('帮我整理研究要点');
  await input.press('Enter');
  await expect(
    page.getByText('已经整理好研究要点。', { exact: true }),
  ).toBeVisible();
  expect(mock.chatRequests[0].session_id).toBe('session-1');
  expect(mock.errors).toEqual([]);
});

async function verifyTaskManagement(page: Page, mobile: boolean) {
  const mock = await mockApi(page);
  page.on('dialog', (dialog) => dialog.accept());
  await page.goto('/ai-eido/');
  const openTasks = async () => {
    if (mobile) {
      await page.getByRole('button', { name: '打开会话与项目' }).click();
      await page
        .getByRole('navigation', { name: '抽屉导航' })
        .getByRole('button', { name: '自动任务', exact: true })
        .click();
    } else
      await page
        .getByRole('navigation')
        .getByRole('button', { name: '自动任务', exact: true })
        .click();
  };
  await openTasks();
  await page
    .getByRole('button', { name: mobile ? '新建 ＋' : '添加任务', exact: true })
    .click();
  await page.getByPlaceholder('例如：每日晨报').fill('每日晨报');
  await page.getByRole('radio', { name: 'Cron', exact: true }).check();
  await page
    .getByPlaceholder('分 时 日 月 周  例：0 9 * * *')
    .fill('0 9 * * *');
  await page
    .getByPlaceholder('定时发送给 AI 的完整指令，将按对话方式执行…')
    .fill('整理每日市场要点');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '每日晨报', exact: true }),
  ).toBeVisible();
  expect(mock.tasks[0]).toMatchObject({
    schedule: '0 9 * * *',
    type: 'chat',
    params: { messages: [{ role: 'user', content: '整理每日市场要点' }] },
  });
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByRole('radio', { name: '按间隔', exact: true }).check();
  await page.getByRole('spinbutton').fill('2');
  await page.getByRole('dialog').getByRole('combobox').selectOption('h');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  expect(mock.tasks[0].schedule).toBe('interval:7200');
  if (mobile) {
    await page
      .getByRole('switch', { name: '启用 每日晨报', exact: true })
      .click();
    await expect(
      page.getByRole('switch', { name: '启用 每日晨报', exact: true }),
    ).toHaveAttribute('aria-checked', 'false');
  } else {
    await page.getByRole('checkbox', { name: '启用', exact: true }).click();
    await expect(
      page.getByRole('checkbox', { name: '启用', exact: true }),
    ).not.toBeChecked();
  }
  await page.getByRole('button', { name: '立即执行', exact: true }).click();
  await expect(page.getByText('任务执行结果', { exact: true })).toBeVisible();
  await openTasks();
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '每日晨报', exact: true }),
  ).toHaveCount(0);
  expect(mock.tasks).toHaveLength(0);
  expect(mock.errors).toEqual([]);
}

test('PC scheduled task management', async ({ page }, info) => {
  test.skip(info.project.name !== 'pc');
  await verifyTaskManagement(page, false);
});

test.describe('H5', () => {
  test.beforeEach(({}, info) => {
    test.skip(info.project.name !== 'h5');
  });

  for (const [width, height] of [
    [320, 568],
    [390, 844],
    [768, 1024],
    [390, 320],
  ]) {
    test(`left drawer pins controls while history scrolls at ${width}x${height}px`, async ({
      page,
    }) => {
      const mock = await mockApi(page);
      mock.sessions.push(
        ...Array.from({ length: 60 }, (_, index) => ({
          id: `history-${index}`,
          title: `历史会话 ${index + 1}`,
          project_id: null,
          created_at: now,
          updated_at: now,
          messages: [],
        })),
      );
      await page.setViewportSize({ width, height });
      await page.goto('/ai-eido/');
      await page.getByRole('button', { name: '打开会话与项目' }).click();
      const drawer = page.getByRole('dialog', { name: 'Eido', exact: true });
      await expect(drawer).toHaveCSS('transform', 'none');
      const bounds = await drawer.boundingBox();
      expect(bounds!.x).toBe(0);
      expect(bounds!.y).toBe(0);
      expect(bounds!.height).toBe(height);
      expect(bounds!.width).toBeLessThan(width);
      const newChat = drawer.getByRole('button', {
        name: '新建会话',
        exact: true,
      });
      const account = drawer.locator('.h5-account');
      const before = [await newChat.boundingBox(), await account.boundingBox()];
      await drawer.locator('.h5-drawer-body').evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      await expect(
        drawer.getByText('历史会话 60', { exact: true }),
      ).toBeVisible();
      await expect(newChat).toBeInViewport();
      await expect(account).toBeInViewport();
      expect((await newChat.boundingBox())!.y).toBe(before[0]!.y);
      expect((await account.boundingBox())!.y).toBe(before[1]!.y);
      for (const name of ['我的技能', 'MCP 管理', '自动任务'])
        await expect(
          drawer.getByRole('button', { name, exact: true }),
        ).toBeVisible();
      expect(
        await page.evaluate(() =>
          getComputedStyle(document.documentElement)
            .getPropertyValue('--h5-accent')
            .trim(),
        ),
      ).toBe('#374151');
      if (width === 390)
        await page.screenshot({ path: test.info().outputPath('drawer.png') });
      await page.keyboard.press('Escape');
      await expect(drawer).toHaveCount(0);
      await page.getByRole('button', { name: '打开会话与项目' }).click();
      await page.mouse.click(width - 5, 20);
      await expect(drawer).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  }

  test('manages skill creation, editing, deletion and import', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    page.on('dialog', (dialog) => dialog.accept());
    await page.goto('/ai-eido/');
    await page.getByRole('button', { name: '打开会话与项目' }).click();
    await page
      .getByRole('navigation', { name: '抽屉导航' })
      .getByRole('button', { name: '我的技能', exact: true })
      .click();
    await page.getByRole('button', { name: '新建', exact: true }).click();
    await page.getByRole('textbox', { name: '技能名称' }).fill('我的研究');
    await page
      .getByRole('textbox', { name: '简介', exact: true })
      .fill('个人研究流程');
    await page
      .getByRole('textbox', { name: '技能说明（Markdown）' })
      .fill('# 我的研究\n整理观点');
    await page.getByRole('button', { name: '保存技能', exact: true }).click();
    await page.getByRole('button', { name: /我的研究 个人研究流程/ }).click();
    await page.getByRole('button', { name: '编辑技能', exact: true }).click();
    await page.getByRole('textbox', { name: '技能名称' }).fill('我的研究更新');
    await page.getByRole('button', { name: '保存技能', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: '我的研究更新', exact: true }),
    ).toBeVisible();
    expect(mock.skills.find((s) => s.id === 'owned-skill').name).toBe(
      '我的研究更新',
    );
    await page.getByRole('button', { name: '删除技能', exact: true }).click();
    await expect(
      page.getByRole('button', { name: /我的研究更新/ }),
    ).toHaveCount(0);
    await page.locator('.h5-upload input[type=file]').setInputFiles({
      name: 'SKILL.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# 导入技能'),
    });
    await expect(
      page.getByRole('button', { name: /导入技能 整理资料/ }),
    ).toBeVisible();
    expect(mock.errors).toEqual([]);
  });

  test('manages MCP creation, secret-preserving toggles, editing and deletion', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    page.on('dialog', (dialog) => dialog.accept());
    await page.goto('/ai-eido/');
    await page.getByRole('button', { name: '打开会话与项目' }).click();
    await page
      .getByRole('navigation', { name: '抽屉导航' })
      .getByRole('button', { name: 'MCP 管理', exact: true })
      .click();
    await page.getByRole('button', { name: '新增 MCP ＋' }).click();
    await page
      .getByRole('textbox', { name: '服务名称' })
      .fill('research-tools');
    await page
      .getByRole('textbox', { name: '服务地址' })
      .fill('https://example.test/mcp');
    await page
      .getByRole('textbox', { name: '请求头（JSON 对象）' })
      .fill('{"Authorization":"__EIDO_SECRET__"}');
    await page.getByRole('button', { name: '保存 MCP', exact: true }).click();
    const card = page.getByRole('article', { name: 'MCP 服务 research-tools' });
    await expect(card).toBeVisible();
    await card.getByRole('switch').click();
    await expect(card.getByRole('switch')).toHaveAttribute(
      'aria-checked',
      'false',
    );
    expect(mock.mcps[0].config.headers.Authorization).toBe('__EIDO_SECRET__');
    await card.getByRole('button', { name: '编辑', exact: true }).click();
    await page
      .getByRole('combobox', { name: '连接方式' })
      .selectOption('stdio');
    await page.getByRole('textbox', { name: '启动命令' }).fill('uvx');
    await page
      .getByRole('textbox', { name: '启动参数（JSON 数组）' })
      .fill('{"invalid":true}');
    await page.getByRole('button', { name: '保存 MCP', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('JSON 数组');
    await page
      .getByRole('textbox', { name: '启动参数（JSON 数组）' })
      .fill('["research-server"]');
    await page.getByRole('button', { name: '保存 MCP', exact: true }).click();
    await expect(card).toContainText('STDIO');
    expect(mock.mcps[0].config.args).toEqual(['research-server']);
    await card.getByRole('button', { name: '删除', exact: true }).click();
    await expect(card).toHaveCount(0);
    await page.getByRole('button', { name: '统一配置', exact: true }).click();
    await expect(
      page.getByRole('textbox', { name: 'MCP JSON 配置' }),
    ).toHaveValue('{\n  "mcpServers": {}\n}');
    expect(mock.errors).toEqual([]);
  });

  test('scheduled task management matches PC behavior', async ({ page }) => {
    await verifyTaskManagement(page, true);
  });

  for (const width of [320, 390, 768]) {
    test(`fits ${width}px and navigates all main views`, async ({ page }) => {
      const mock = await mockApi(page);
      await page.setViewportSize({ width, height: 844 });
      await page.goto('/ai-eido/');
      await expect(page.getByRole('heading', { name: /让想法/ })).toBeVisible();
      if (width === 390)
        await page.screenshot({ path: test.info().outputPath('home.png') });
      for (const name of ['技能', '工具', '自动任务', '探索']) {
        await page
          .getByRole('navigation', { name: '主导航' })
          .getByRole('button', { name, exact: true })
          .click();
        await expect(page.locator('.h5-page')).toBeVisible();
        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth > innerWidth ||
            document.querySelector('.h5-page')!.scrollWidth >
              document.querySelector('.h5-page')!.clientWidth,
        );
        expect(overflow).toBe(false);
      }
      expect(mock.errors).toEqual([]);
    });
  }

  test('streams chat, restores history, and opens settings and files', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    await page.goto('/ai-eido/');
    await page.getByRole('button', { name: /开启新的对话/ }).click();
    const input = page.getByRole('textbox', { name: '消息内容' });
    await input.fill('第一行\n第二行');
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(
      page.getByText('已经整理好研究要点。', { exact: true }),
    ).toBeVisible();
    expect(mock.chatRequests[0].messages[0].content).toBe('第一行\n第二行');
    await page.screenshot({ path: test.info().outputPath('chat.png') });
    await page.reload();
    await expect(
      page.getByText('已经整理好研究要点。', { exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Agent 模式', exact: true }).click();
    await expect(
      page.getByRole('combobox', { name: 'Claude Code 执行模式' }),
    ).toBeVisible();
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    await page
      .getByRole('button', { name: '资料与执行记录', exact: true })
      .click();
    await expect(page.getByText('工作区文件', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: '打开会话与项目' }).click();
    await expect(
      page.getByRole('dialog').getByText('第一行\n第二行', { exact: true }),
    ).toBeVisible();
    expect(mock.errors).toEqual([]);
  });

  test('creates a project and starts a chat in its context', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    await page.goto('/ai-eido/');
    await page.getByRole('button', { name: '新建 ＋', exact: true }).click();
    await page.getByRole('textbox', { name: '项目名称' }).fill('移动端研究');
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: '移动端研究', exact: true }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: '新建对话 ＋', exact: true })
      .click();
    await page
      .getByRole('textbox', { name: '消息内容' })
      .fill('结合项目资料进行研究');
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(
      page.getByText('已经整理好研究要点。', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('项目 · 移动端研究', { exact: true }),
    ).toBeVisible();
    expect(mock.errors).toEqual([]);
  });

  test('browses skill files with system permissions enforced', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    await page.goto('/ai-eido/');
    await page
      .getByRole('navigation')
      .getByRole('button', { name: '技能', exact: true })
      .click();
    await page.getByRole('button', { name: /研究助手 整理资料/ }).click();
    await page.getByRole('button', { name: '技能文件', exact: true }).click();
    await page.getByRole('button', { name: 'SKILL.md', exact: false }).click();
    await expect(page.getByRole('textbox', { name: '文件内容' })).toHaveValue(
      '# 研究助手',
    );
    await expect(
      page.getByRole('textbox', { name: '文件内容' }),
    ).toHaveAttribute('readonly', '');
    await expect(
      page.getByRole('button', { name: '保存文件', exact: true }),
    ).toHaveCount(0);
    expect(mock.errors).toEqual([]);
  });

  test('preserves the same OAuth login URL', async ({ page }) => {
    const mock = await mockApi(page, false);
    await page.goto('/ai-eido/?login=success');
    await expect(
      page.getByRole('link', { name: /使用 GitHub 登录/ }),
    ).toHaveAttribute('href', '/ai-eido/api/v1/auth/login/github');
    await expect(
      page.getByRole('link', { name: /使用 CAS 登录/ }),
    ).toHaveAttribute('href', '/ai-eido/api/v1/auth/login');
    expect(mock.errors).toEqual([]);
  });
});
