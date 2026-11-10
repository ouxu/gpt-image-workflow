# GPT Image Workflow

固定提供商、固定模型、单次提交的 GPT Image CLI + Agent Skill。

> 一次配置，后续只说“自定义生图”。默认模型 ID 是 `gpt-image-2.5`，不会擅自改成其他别名。此项目不能覆盖宿主对内置绘图工具的强制要求。

## 为什么做这个

直接安装多个生图技能容易出现默认模型不同、提供商环境变量互相覆盖、失败自动重试等问题。本项目围绕 [zjandrew/gpt-image-cli](https://github.com/zjandrew/gpt-image-cli) 的 **1.3.0** 版本提供独立入口：

- endpoint / key / model 一次保存在仓库外的用户配置。
- 每次明确传递精确模型 ID；不提供自动模型/渠道回退。
- 默认一张 PNG，支持文生图及本地参考图编辑。
- SDK 零重试、拒绝重定向、拒绝图片 URL 下载；真实请求最多一次。
- 密钥不出现在命令行、日志或输出元数据；隔离常见 OpenAI 环境变量和用户 CLI profile。
- 不覆盖已有输出；输出 PNG 和不含提示词/密钥的审计元数据。
- 可先运行 doctor / dry-run，不消耗图片生成费用。

## 安装

要求 Python 3.10+、Node.js 18+、npm。

```bash
git clone https://github.com/ouxu/gpt-image-workflow.git
cd gpt-image-workflow
npm --prefix fixed-gpt-image ci --ignore-scripts --no-audit --no-fund
```

通过密码管理器或其他安全方式设置 `OPENAI_API_KEY`，然后配置一次：

```bash
python3 fixed-gpt-image/scripts/image.py configure \
  --endpoint https://api.example.com/v1 \
  --model gpt-image-2.5
```

`api.example.com` 是示例地址，不是可用服务。配置写到 `~/.config/fixed-gpt-image/config.json`，权限 0600；拒绝覆盖已有配置。真实密钥不要进入 Git、截图、issue 或 shell 历史。也支持从用户指定的 WorkBuddy 提供商记录导入，详见 [配置指南](fixed-gpt-image/references/setup.md)。

## 使用

```bash
python3 fixed-gpt-image/scripts/image.py doctor
python3 fixed-gpt-image/scripts/image.py models
mkdir -p outputs
python3 fixed-gpt-image/scripts/image.py generate \
  --prompt "一只橘猫，扁平插画" --output "$PWD/outputs/cat.png" --dry-run
# 去掉 --dry-run 才会提交真实生成请求，可能计费。
python3 fixed-gpt-image/scripts/image.py generate \
  --prompt "一只橘猫，扁平插画" --output "$PWD/outputs/cat.png"
python3 fixed-gpt-image/scripts/image.py edit \
  --image "$PWD/outputs/cat.png" --prompt "改成蓝色背景" \
  --output "$PWD/outputs/cat-blue.png"
```

`--size` 默认 `1024x1024`，`--quality` 默认 `low`。长提示词可用 `--prompt-file`，多张本地参考图可重复 `--image`。默认模型只从配置读取，禁止通过环境变量悄悄替换。

## 安装为个人 Skill

复制仓库中的完整 `fixed-gpt-image` 目录到 `~/.workbuddy/skills/fixed-gpt-image`，在目标目录执行 `npm ci --ignore-scripts`。不要覆盖已有同名技能。重新加载技能或开启新会话后，使用“自定义生图”或显式选中该技能。适配其他 Agent 时保留目录结构。

**它提供一个明确执行入口，不会强制接管所有普通“画图”请求，也不会改变宿主内置图片模型。** 宿主若不允许调用外部 CLI，必须如实说明，不能把内置绘图结果当作指定提供商的结果。

## 安全与实现

- 上游 npm 包锁定版本并提交 `package-lock.json`。
- 每次运行校验上游 bundle 的 SHA-256；不符则停止。
- 不修改已安装依赖，生成临时运行副本，精确注入 `maxRetries: 0`、超时与网络限制；运行后删除临时副本。
- API 请求限定为当前 endpoint 的图片接口；响应大小限制 64 MiB；只接受 base64 PNG 返回。
- 本地 HTTP 仅通过 `allow_local_http: true` 显式用于回环测试，远程服务必须 HTTPS。
- 服务端错误不原样回显，避免提示词或密钥被恶意回传到日志。
- PNG 仅验证签名，并非完整解码/安全审计；调用方仍应检查生成图片。
- 请求超时不代表服务端没有处理或计费，重新提交必须由用户决定。

## 验证

```bash
npm --prefix fixed-gpt-image test
```

测试使用本地模拟 HTTP 接口，不调用真实生成服务，覆盖固定模型、参考图 multipart、零重试、重定向拦截、URL 下载拦截、环境隔离和密钥脱敏。`models` 中出现某个 ID 不代表该模型能实际生成，也不能证明提供商底层模型身份。

## 当前边界

不支持 Azure、异步任务、URL-only 图片返回、蒙版或自动批量生成。上游 CLI 有更多能力，本封装刻意只开放可约束的子集。真实提供商是否支持裸 `gpt-image-2.5`、尺寸和编辑路由，需要实际调用验证；本项目不会自动改成 flare/sunburst。

## 致谢与许可

封装代码使用 MIT License。上游执行器来自 [zjandrew/gpt-image-cli](https://github.com/zjandrew/gpt-image-cli)（npm 元数据声明 MIT），通过 npm 安装，不把上游源码或依赖目录纳入本仓库。依赖按各自许可分发。
