import { expect, test, type Page } from '@playwright/test';
import { mockApi, now } from './fixtures';

async function navigate(page: Page, mobile: boolean, name: string) {
  if (mobile)
    await page.getByRole('button', { name: '打开会话与项目' }).click();
  await page
    .getByRole('navigation')
    .getByRole('button', { name, exact: true })
    .click();
}

async function screenshot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`) });
}

async function assertFits(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth > innerWidth ||
        document.querySelector('.h5-management')?.scrollWidth > innerWidth,
    ),
  ).toBe(false);
}

for (const mobile of [true, false]) {
  test.describe(
    mobile ? 'H5 shared PC functionality' : 'PC functionality',
    () => {
      test.beforeEach(({}, info) => {
        test.skip(info.project.name !== (mobile ? 'h5' : 'pc'));
      });

      test('streams chat and restores persisted history', async ({ page }) => {
        const mock = await mockApi(page);
        await page.goto('/ai-eido/');
        if (mobile)
          await page.getByRole('button', { name: '打开会话与项目' }).click();
        await page
          .getByRole('button', { name: /新建会话/, exact: false })
          .click();
        const input = mobile
          ? page.getByRole('textbox', { name: '消息内容' })
          : page.locator('textarea').first();
        await input.fill('整理研究要点');
        if (mobile)
          await page
            .getByRole('button', { name: '发送消息', exact: true })
            .click();
        else await input.press('Enter');
        await expect(
          page.getByText('已经整理好研究要点。', { exact: true }),
        ).toBeVisible();
        await page.reload();
        await expect(
          page.getByText('已经整理好研究要点。', { exact: true }),
        ).toBeVisible();
        expect(mock.chatRequests[0].messages[0].content).toBe('整理研究要点');
        expect(mock.errors).toEqual([]);
      });

      test('skill creation, file editing, folders, deletion and import match', async ({
        page,
      }) => {
        const mock = await mockApi(page);
        await page.goto('/ai-eido/');
        await navigate(page, mobile, '我的技能');
        await page
          .getByRole('button', { name: '新建技能', exact: true })
          .click();
        await page.getByPlaceholder('例如：数据分析助手').fill('我的研究');
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^创\s*建$/ })
          .click();
        await expect(
          page.getByRole('heading', { name: '我的研究', exact: true }),
        ).toBeVisible();
        await page.getByRole('tab', { name: '文件管理', exact: true }).click();
        await page
          .locator('.ant-tree-title')
          .getByText('SKILL.md', { exact: true })
          .click();
        const files = page.locator('.skill-file-browser');
        await files.getByRole('button', { name: /编辑/ }).click();
        await files.locator('textarea').fill('# 修改后的技能说明');
        await files.getByRole('button', { name: /保存/ }).click();
        await expect
          .poll(() => mock.fileContents['SKILL.md'])
          .toBe('# 修改后的技能说明');
        await expect(files.getByRole('button', { name: /删除/ })).toHaveCount(
          0,
        );
        await files.getByRole('button', { name: /新建文件夹/ }).click();
        await page.getByRole('dialog').locator('input').fill('scripts');
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^创\s*建$/ })
          .click();
        await expect.poll(() => mock.directories).toContain('scripts');
        await page
          .locator('.ant-tree-title')
          .getByText('scripts', { exact: true })
          .waitFor();
        if (mobile) {
          await assertFits(page);
          await screenshot(page, 'skill-files');
        }
        await page
          .locator('.management-header')
          .getByRole('button', { name: /删除/ })
          .click();
        await page
          .locator('.ant-modal-confirm')
          .getByRole('button', { name: /^删\s*除$/ })
          .click();
        await expect(
          page.getByRole('heading', { name: '我的技能', exact: true }),
        ).toBeVisible();
        await page
          .getByRole('button', { name: '上传技能', exact: true })
          .click();
        await page.locator('#upload-skill-input').setInputFiles({
          name: 'SKILL.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# 导入技能'),
        });
        await expect(
          page.getByRole('heading', { name: '导入技能', exact: true }),
        ).toBeVisible();
        expect(mock.skills.some((s) => s.id === 'owned-skill')).toBe(false);
        expect(mock.errors).toEqual([]);
      });

      test('system skill files enforce identical read-only permissions', async ({
        page,
      }) => {
        const mock = await mockApi(page);
        await page.goto('/ai-eido/');
        await navigate(page, mobile, '我的技能');
        await page.getByRole('button', { name: /研究助手 整理资料/ }).click();
        await page.getByRole('tab', { name: '文件管理', exact: true }).click();
        await page
          .locator('.ant-tree-title')
          .getByText('SKILL.md', { exact: true })
          .click();
        await expect(page.locator('.skill-file-browser pre')).toHaveText(
          '# 研究助手',
        );
        await expect(
          page
            .locator('.skill-file-browser')
            .getByRole('button', { name: /编辑|新建文件|删除/ }),
        ).toHaveCount(0);
        expect(mock.errors).toEqual([]);
      });

      test('MCP unified config supports create, edit, disable and delete', async ({
        page,
      }) => {
        const mock = await mockApi(page);
        await page.goto('/ai-eido/');
        await navigate(page, mobile, '我的工具');
        await page
          .getByRole('button', { name: '统一配置', exact: true })
          .click();
        const config = {
          mcpServers: {
            research: {
              type: 'http',
              url: 'https://example.test/mcp',
              headers: { Authorization: '__EIDO_SECRET__' },
              disabled: true,
            },
          },
        };
        await page
          .getByRole('textbox', { name: 'MCP JSON 配置' })
          .fill(JSON.stringify(config));
        await page
          .getByRole('button', { name: '保存配置', exact: true })
          .click();
        await expect(
          page.getByText('配置已保存，新的 Claude 会话将立即使用。'),
        ).toBeVisible();
        if (mobile) {
          await assertFits(page);
          await screenshot(page, 'mcp-config');
        }
        await page.getByRole('button', { name: '关闭', exact: true }).click();
        await expect(
          page.getByRole('heading', { name: 'research', exact: true }),
        ).toBeVisible();
        await page
          .getByRole('button', { name: '统一配置', exact: true })
          .click();
        config.mcpServers.research.disabled = false;
        await page
          .getByRole('textbox', { name: 'MCP JSON 配置' })
          .fill(JSON.stringify(config));
        await page
          .getByRole('button', { name: '保存配置', exact: true })
          .click();
        await expect.poll(() => mock.mcps[0]?.enabled).toBe(true);
        expect(mock.mcps[0].config.headers.Authorization).toBe(
          '__EIDO_SECRET__',
        );
        await page
          .getByRole('textbox', { name: 'MCP JSON 配置' })
          .fill('{"mcpServers":{}}');
        await page
          .getByRole('button', { name: '保存配置', exact: true })
          .click();
        await expect.poll(() => mock.mcps.length).toBe(0);
        await page.getByRole('button', { name: '关闭', exact: true }).click();
        await expect(
          page.getByRole('heading', { name: '尚未配置 MCP', exact: true }),
        ).toBeVisible();
        expect(mock.errors).toEqual([]);
      });

      test('scheduled task CRUD, cron, interval, enable and run match', async ({
        page,
      }) => {
        const mock = await mockApi(page);
        page.on('dialog', (dialog) => dialog.accept());
        await page.goto('/ai-eido/');
        await navigate(page, mobile, '自动任务');
        await page
          .getByRole('button', { name: '添加任务', exact: true })
          .click();
        await page.getByPlaceholder('例如：每日晨报').fill('每日晨报');
        await page.getByRole('radio', { name: 'Cron', exact: true }).check();
        await page
          .getByPlaceholder('分 时 日 月 周  例：0 9 * * *')
          .fill('0 9 * * *');
        await page
          .getByPlaceholder('定时发送给 AI 的完整指令，将按对话方式执行…')
          .fill('整理每日市场要点');
        if (mobile) {
          await assertFits(page);
          await screenshot(page, 'task-form');
        }
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
        await expect.poll(() => mock.tasks[0].schedule).toBe('interval:7200');
        await page.getByRole('checkbox', { name: '启用', exact: true }).click();
        await expect(
          page.getByRole('checkbox', { name: '启用', exact: true }),
        ).not.toBeChecked();
        await page
          .getByRole('button', { name: '立即执行', exact: true })
          .click();
        await expect(
          page.getByText('任务执行结果', { exact: true }),
        ).toBeVisible();
        await navigate(page, mobile, '自动任务');
        await page.getByRole('button', { name: /^删\s*除$/ }).click();
        await expect(
          page.getByRole('heading', { name: '每日晨报', exact: true }),
        ).toHaveCount(0);
        expect(mock.tasks).toHaveLength(0);
        expect(mock.errors).toEqual([]);
      });
    },
  );
}

test.describe('H5 navigation and layout', () => {
  for (const [width, height] of [
    [320, 568],
    [390, 844],
    [768, 1024],
    [390, 320],
  ]) {
    test(`only project and conversation sections scroll at ${width}x${height}`, async ({
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
      await expect(page.locator('.h5-tabs')).toHaveCount(0);
      await expect(page.locator('.h5-header .eido-brand')).toHaveCount(1);
      await expect(page.locator('img[src*="images/logo.png"]')).toHaveCount(0);
      await page.getByRole('button', { name: '打开会话与项目' }).click();
      const drawer = page.getByRole('dialog', {
        name: '对话与项目',
        exact: true,
      });
      await expect(drawer).toHaveCSS('transform', 'none');
      const bounds = await drawer.boundingBox();
      expect(bounds!.x).toBe(0);
      expect(bounds!.height).toBe(height);
      const header = drawer.locator('.sidebar-header');
      const account = drawer.locator('.sidebar-account');
      const before = [await header.boundingBox(), await account.boundingBox()];
      const avatar = account.getByRole('button', { name: '账户', exact: true });
      await expect(avatar).toHaveCSS('width', '32px');
      await expect(avatar).toHaveCSS('height', '32px');
      await expect(avatar).toHaveCSS('background-color', 'rgb(229, 231, 235)');
      await avatar.click();
      await expect(
        drawer.getByRole('menuitem', { name: 'API Key', exact: true }),
      ).toBeVisible();
      await expect(
        drawer.getByRole('menuitem', { name: '登出', exact: true }),
      ).toBeVisible();
      await avatar.click();
      const projects = drawer.getByRole('button', { name: /^项目 \d/ });
      await projects.click();
      await expect(projects).toHaveAttribute('aria-expanded', 'false');
      await projects.click();
      await expect(projects).toHaveAttribute('aria-expanded', 'true');
      const conversations = drawer.getByRole('button', { name: /^对话 \d/ });
      await conversations.click();
      await expect(conversations).toHaveAttribute('aria-expanded', 'false');
      await conversations.click();
      await drawer.locator('.sidebar-content').evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      await expect(
        drawer.getByText('历史会话 60', { exact: true }),
      ).toBeInViewport();
      expect((await header.boundingBox())!.y).toBe(before[0]!.y);
      expect((await account.boundingBox())!.y).toBe(before[1]!.y);
      await expect(
        drawer.getByRole('button', { name: /新建会话/ }),
      ).toBeInViewport();
      await expect(account).toBeInViewport();
      await expect(drawer.getByRole('button', { name: /新建会话/ })).toHaveCSS(
        'border-top-style',
        'solid',
      );
      await expect(drawer.getByRole('button', { name: /新建会话/ })).toHaveCSS(
        'border-top-width',
        '1px',
      );
      for (const name of ['我的技能', '我的工具', '自动任务'])
        await expect(
          drawer.getByRole('button', { name, exact: true }),
        ).toBeInViewport();
      if (width === 390 && height === 844) await screenshot(page, 'drawer');
      await page.keyboard.press('Escape');
      await expect(drawer).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  }

  for (const width of [320, 390, 768]) {
    test(`management pages remain usable at ${width}px`, async ({ page }) => {
      const mock = await mockApi(page);
      await page.setViewportSize({ width, height: 844 });
      await page.goto('/ai-eido/');
      for (const name of ['我的技能', '我的工具', '自动任务']) {
        await navigate(page, true, name);
        await expect(
          page.getByRole('heading', { name, exact: true }),
        ).toBeVisible();
        await assertFits(page);
        if (width === 390) await screenshot(page, name);
      }
      await expect(page.locator('.h5-tabs')).toHaveCount(0);
      expect(mock.errors).toEqual([]);
    });
  }

  test('shares project context and reference/file tools with PC', async ({
    page,
  }) => {
    const mock = await mockApi(page);
    await page.goto('/ai-eido/');
    await page.getByRole('button', { name: '打开会话与项目' }).click();
    await page.getByRole('button', { name: '新建项目', exact: true }).click();
    await page.getByRole('textbox', { name: '项目名称' }).fill('移动端研究');
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: '移动端研究', exact: true }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: '+ 项目内新建会话', exact: true })
      .click();
    await page
      .getByRole('textbox', { name: '消息内容' })
      .fill('结合项目资料研究');
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(
      page.getByText('已经整理好研究要点。', { exact: true }),
    ).toBeVisible();
    expect(mock.sessions[0].project_id).toBe('project-2');
    await page
      .getByRole('button', { name: '资料与执行记录', exact: true })
      .click();
    await expect(page.getByRole('button', { name: '项目资料', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '会话文件', exact: true }).click();
    await expect(page.getByText('暂无文件', { exact: true })).toBeVisible();
    expect(mock.errors).toEqual([]);
  });

  test('login is independent of stale logo assets and preserves OAuth links', async ({
    page,
  }) => {
    const mock = await mockApi(page, false);
    await page.goto('/ai-eido/?login=success');
    await expect(page.locator('.eido-brand')).toBeVisible();
    await expect(page.locator('img[src*="logo.png"]')).toHaveCount(0);
    await expect(
      page.getByRole('link', { name: /使用 GitHub 登录/ }),
    ).toHaveAttribute('href', '/ai-eido/api/v1/auth/login/github');
    expect(mock.errors).toEqual([]);
  });
});
