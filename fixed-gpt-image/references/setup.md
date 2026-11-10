# 一次配置

运行环境：Python 3.10+、Node.js 18+、npm。配置位于仓库外，权限 0600。

```bash
npm --prefix /absolute/fixed-gpt-image ci --ignore-scripts --no-audit --no-fund
```

## 通用提供商

通过环境变量注入 API Key，再执行一次配置。不要把真实密钥写到 README、命令行参数、Git 或 issue 中。下面的地址仅为示例，请替换成已授权的实际 API 根路径。

```bash
python3 /absolute/fixed-gpt-image/scripts/image.py configure --endpoint https://api.example.com/v1 --model gpt-image-2.5
```

默认读取 `OPENAI_API_KEY`，也可用 `--key-env` 指定变量名。可以使用密码管理器注入变量，避免密钥进入 shell 历史。

## 导入 WorkBuddy 的已授权提供商

```bash
python3 /absolute/fixed-gpt-image/scripts/image.py configure --workbuddy-provider YOUR_EXISTING_RECORD_ID --model gpt-image-2.5
```

选择器是 `~/.workbuddy/models.json` 中的记录 ID，不是图片模型。该命令将此记录的地址和密钥复制到独立的本地配置，之后不再自动跟随宿主的提供商变化。只导入用户指定的记录。

## 修改默认值

显式编辑 `~/.config/fixed-gpt-image/config.json` 的 `model` 或 `endpoint`。不自动选择别名。配置命令拒绝覆盖已有文件。保留 0600 权限，不提交真实配置。可通过顶层 `--config /absolute/config.json` 选择另一份显式配置。

## 安装技能

把完整 `fixed-gpt-image` 目录复制到 `~/.workbuddy/skills/fixed-gpt-image`，在目标目录运行 `npm ci --ignore-scripts`。若目标已存在，先检查并备份，不盲目覆盖。重新加载技能或开启新会话后，用“自定义生图”或显式选择 `fixed-gpt-image`。

安装技能不保证宿主一定允许外部生图命令；遇到宿主要求使用固定图片工具时应说明限制。
