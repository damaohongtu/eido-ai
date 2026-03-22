---
name: email-master 万能邮箱助手
description: 通过163邮箱等发送邮件。支持发送纯文本/HTML 邮件、带附件邮件、接收邮件、检查新邮件。当用户要求发送邮件、查看邮件、检查新邮件时使用。

---

# 邮件管理

通过163邮箱等发送邮件。

## 配置

编辑 `scripts/config.json`，填写邮箱地址和授权码（非登录密码）。


## 命令行调用

```bash
# 发送纯文本邮件
python3 scripts/mail.py send --to user@example.com --subject "主题" --content "内容"

# 发送 HTML 邮件（正文直接展示 HTML）
python3 scripts/mail.py send --to user@example.com --subject "报告" --html report.html

# 发送带附件
python3 scripts/mail.py send --to user@example.com --subject "报告" --content "请查收" --attach report.pdf

# 接收最新邮件
python3 scripts/mail.py receive --limit 5

# 接收邮件（JSON 输出，推荐 AI 使用）
python3 scripts/mail.py receive --limit 5 --json

# 检查新邮件（最近 N 天）
python3 scripts/mail.py check-new --since 1

# 检查新邮件（JSON 输出）
python3 scripts/mail.py check-new --since 1 --json

# 删除邮件（移到已删除文件夹，QQ邮箱可恢复）
python3 scripts/mail.py delete --ids 123

# 批量删除
python3 scripts/mail.py delete --ids 123 124 125

# 彻底删除（不可恢复）
python3 scripts/mail.py delete --ids 123 --permanent

# 指定邮箱类型
python3 scripts/mail.py --mailbox 163 send --to user@example.com --subject "测试"

# HTML 报告 + 附件
python3 scripts/mail.py send --to user@example.com --subject "行业报告" --html report.html --attach data.xlsx
```

## 发送正文说明

- `--content`：纯文本正文
- `--html`：指定 HTML 文件路径，正文以 HTML 渲染展示（表格、样式等），`--content` 与 `--html` 二选一

## 删除邮件说明

- QQ 邮箱（IMAP）：默认移到「已删除」文件夹，可以从已删除中恢复。加 `--permanent` 彻底删除。
- 163 邮箱（POP3）：POP3 协议不支持文件夹操作，删除始终是永久的，不可恢复。
