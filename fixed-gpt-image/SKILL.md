---
name: fixed-gpt-image
description: 固定自定义提供商和精确模型 ID 的 GPT Image 生图工作流。用于用户说“自定义生图”“按固定生图流程”“用 GPT Image 2.5 生图”，或明确调用 fixed-gpt-image。支持命令行文生图、本地参考图编辑、无费用预检；不静默换模型、不自动重试。不能改变宿主内置绘图工具的模型选择。
agent_created: true
---

# 固定 GPT Image 工作流

## 固定行为

- 读取 `~/.config/fixed-gpt-image/config.json`，使用其中的 endpoint、api_key、model。
- 将模型 ID 原样传给上游，不把 `gpt-image-2.5` 映射成 flare 或 sunburst。用户未要求时，不改模型或提供商。
- 将“自定义生图”作为本技能的明确入口；不要混用其他同类技能的默认配置。
- 遵守宿主的工具要求。若宿主强制使用内置绘图且不能选择自定义模型，明确说明限制；不要声称该技能能覆盖宿主规则，不伪装执行结果。
- 仅在用户请求实际出图时提交一次图片请求。默认一张、PNG、1024x1024、low。超时和 401/429/5xx 均停止，不自动重试或换渠道。
- 不把模型列表可见、发送的模型 ID、提供商实际底层模型身份混为一谈。

## 预检

将下面的 `SKILL_DIR` 替换成当前技能真实绝对路径，不直接使用占位符。

```bash
python3 "SKILL_DIR/scripts/image.py" doctor
python3 "SKILL_DIR/scripts/image.py" models
```

`doctor` 不联网。`models` 只请求模型列表，不发起图片生成。配置缺失时参照 `references/setup.md` 一次配置，不擅自读取或使用其他服务密钥。依赖缺失时运行 `npm --prefix "SKILL_DIR" ci --ignore-scripts --no-audit --no-fund`，不要全局安装同名 CLI。

## 调用

确认输出父目录存在，使用新文件绝对路径。首次可添加 `--dry-run` 核实请求计划，不产生生成费用。

```bash
python3 "SKILL_DIR/scripts/image.py" generate --prompt "一只橘猫，简洁插画" --output "/absolute/workspace/outputs/cat.png"
python3 "SKILL_DIR/scripts/image.py" edit --image "/absolute/input.png" --prompt "改为蓝色背景" --output "/absolute/workspace/outputs/edited.png"
```

- 用 `--prompt-file` 读取长提示词；用重复的 `--image` 传本地参考图。
- 不传 API Key 到命令行，不打印配置，不使用 URL 参考图。当前版本不支持 URL-only 返回，不自动下载图片链接。
- 将长调用放入受管理后台任务并等待完成，不重复提交。
- 检查退出码及 JSON 的 `ok`。成功后读取图片检查结果，交付 PNG 及同名 `.png.json` 元数据。
- 报告实际请求模型、耗时、输出路径；不声称已验证底层模型权重。
- 失败后提示“不自动重试；服务端可能仍处理或计费”。不要换模型后假装原模型成功。

## 边界

本技能使用固定版本的独立 CLI。它不会修改 WorkBuddy 内置图片模型，也不会自动禁用其他技能。真实提供商是否支持所选模型、尺寸和编辑接口，需要实际调用验证。安装、dry-run 和模拟测试不是付费生图成功的证明。
