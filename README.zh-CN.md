# harbor-trajectory-extractor

[English](README.md)

将已经完成的 agent 会话提取为 Harbor 的 ATIF `trajectory.json` 格式。

当前支持的 agent 是 `claude-code`、`codex` 和 `opencode`。输入是该 agent 自己在刚完成的运行中留下的原生工件：session JSONL 文件、sessions 目录，或 JSON stdout 捕获文件。这里 Harbor 只是输出 schema；你不需要通过 Harbor 来启动 agent。

转换代码来自 Harbor installed-agent adapters 的 vendored 版本，并在本项目内运行。它不会 shell out 到 `harbor`，也不要求本机安装 Harbor。

## 克隆与安装

```bash
git clone git@github.com:WTHSBG/harbor-trajectory-extractor.git
cd harbor-trajectory-extractor
scripts/install-skill.sh
```

这会做三件事：

- 将 `htextract` CLI 安装到 `./.venv`
- 将 `skills/agent-session-trajectory` 软链到 `${CODEX_HOME:-~/.codex}/skills/agent-session-trajectory`
- 将 wrapper 写入 `~/.local/bin/htextract` 和 `~/.local/bin/agent-session-trajectory`

如果想复制 skill 而不是创建软链，使用 `--copy`；如果要替换已有 skill，使用 `--force`；如果 `htextract` 已经安装好，使用 `--no-tool`。

安装后，如果你的 Codex 使用界面需要重新加载 skill，请重启 Codex 或刷新 skill。skill 名称是 `$agent-session-trajectory`，安装后的辅助命令是：

```bash
agent-session-trajectory --help
```

## 手动安装 CLI

如果你只需要 trajectory 提取工具：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/htextract --help
```

也可以激活 venv：

```bash
source .venv/bin/activate
htextract --help
```

如果 `python3 -m venv` 因为缺少 `ensurepip` 而失败，可以使用 uv：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## 项目结构

```text
.
├── scripts/install-skill.sh              # 安装到 Codex 的脚本
├── skills/agent-session-trajectory/      # 可安装的 Codex skill
├── src/harbor_trajectory_extractor/      # 独立 htextract CLI 包
├── tests/                                # CLI 和转换器测试
├── pyproject.toml
└── requirements.txt
```

## 使用思路

只需要回答两个问题。

1. agent 已经跑完了：这次运行的原生 session 工件在哪里？

```bash
htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary
htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
htextract --agent opencode --source ./opencode-export.json --summary
```

对于 OpenCode 交互式 session，先导出已保存的 session：

```bash
opencode session list
agent-session-trajectory --agent opencode --session <sessionID> --summary
```

2. agent 还没有跑：运行前必须开启或保留什么？

```bash
htextract --describe-agent opencode
```

然后按输出提示运行 agent，保留生成的工件，再用 `--source` 把该工件传回来。

默认输出会写到 source 文件旁边，或 source 目录内，文件名为 `trajectory.json`。使用 `--output` 可以写到其他位置。

## 常用命令

列出支持的 agent 名称：

```bash
htextract --list-agents
```

当前只会打印：

```text
claude-code
codex
opencode
```

查看某个 agent 需要的 source 工件和捕获方式：

```bash
htextract --describe-agent claude-code
```

提取并打印简短摘要：

```bash
htextract --agent claude-code --source <session.jsonl> --summary
```

写入指定文件：

```bash
htextract --agent codex --source <session.jsonl> --output /tmp/trajectory.json
```

## Codex Skill

本仓库包含一个本地 Codex skill：

`skills/agent-session-trajectory/`

安装方式：

```bash
scripts/install-skill.sh
```

安装器默认创建软链，因此之后 `git pull` 会自动更新已安装的 skill。这个 skill 可以帮助另一个 Codex session 从 agent session/source 工件生成 Harbor ATIF trajectory。

skill 的 helper 脚本只支持 Codex、Claude Code 和 OpenCode。它可以为 Codex、Claude Code 自动选择最新的本地 session，也支持 OpenCode session id 或本地 capture。对于精确 session，可以传 `--source` 或 OpenCode 的 `--session`。

默认输出文件名会写到当前工作目录：

```text
<agent>-<session>-trajectory.json
```

示例：

```bash
agent-session-trajectory --agent codex --summary
agent-session-trajectory --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
agent-session-trajectory --agent claude-code --summary
agent-session-trajectory --agent opencode --session <sessionID> --summary
agent-session-trajectory --agent opencode --source ./opencode.jsonl --summary
```

使用 `--output-dir <dir>` 可以把默认文件名输出到其他目录，使用 `--output <file>` 可以指定完整输出路径。

查看某个支持的 agent 需要什么：

```bash
agent-session-trajectory --list-agents
agent-session-trajectory --describe-agent opencode
```

如果无法导出，脚本会打印 `cannot export` 信息，其中包含 agent、source 和下一步要运行的命令。

本地开发时，如果不想安装 wrapper，可以在仓库根目录直接运行内置脚本：

```bash
python3 skills/agent-session-trajectory/scripts/export_trajectory.py --agent codex --summary
```

## Claude Code

已经跑完：

```bash
htextract \
  --agent claude-code \
  --source ~/.claude/projects/<project>/<session>.jsonl \
  --summary
```

如果 `CLAUDE_CONFIG_DIR` 中只有一个 session，也可以直接传该目录：

```bash
htextract --agent claude-code --source <CLAUDE_CONFIG_DIR> --summary
```

Claude Code 默认会记录 session JSONL。如果希望未来的 source 目录更容易定位，可以在启动 Claude Code 前设置 `CLAUDE_CONFIG_DIR`：

```bash
export CLAUDE_CONFIG_DIR="$PWD/.claude-session"

claude --print -- "$INSTRUCTION"

htextract --agent claude-code --source "$CLAUDE_CONFIG_DIR" --summary
```

只有 Claude Code 输出 thinking blocks 时，trajectory 才会包含 reasoning。需要 `reasoning_content` 时，请显式请求 thinking：

```bash
claude \
  --output-format=stream-json \
  --thinking enabled \
  --thinking-display summarized \
  --max-thinking-tokens 4096 \
  --print -- "$INSTRUCTION"
```

`claude-code.txt` 是可选文件。它不是 Claude Code 创建的 session log，只是从 `--output-format=stream-json --print` 捕获的 stdout；本工具只会在它存在时用它补充 `total_cost_usd`。

## OpenCode

OpenCode 交互式 session 会保存在本地。正常交互使用时，`agent-session-trajectory` skill wrapper 可以按 session id 导出已保存的 OpenCode session，并一步完成转换：

```bash
opencode session list
agent-session-trajectory --agent opencode --session <sessionID> --summary
```

底层会运行 `opencode export <sessionID>`，再把导出的 JSON 交给 `htextract`。你也可以手动完成同样的事：

```bash
opencode export <sessionID> > opencode-export.json
htextract --agent opencode --source ./opencode-export.json --summary
```

`opencode export` JSON 包含 `messages[].parts[]`，当模型/provider 输出明文 reasoning 时，其中也会包含 `reasoning` parts。

对于非交互的一次性运行，也可以直接捕获 stdout：

```bash
opencode --model="$MODEL" run \
  --format=json \
  --thinking \
  --dangerously-skip-permissions \
  -- "$INSTRUCTION" \
  2>&1 | tee opencode.jsonl
```

然后提取：

```bash
htextract --agent opencode --source ./opencode.jsonl --summary
```

如果 run-mode JSONL stream 中没有用户 prompt，可以传 instruction 文件：

```bash
htextract \
  --agent opencode \
  --source ./opencode.jsonl \
  --instruction-path ./instruction.txt \
  --summary
```

不使用 helper 时，也可以导出 session 后直接查看 reasoning：

```bash
opencode export <sessionID> | jq '.messages[].parts[] | select(.type=="reasoning")'
```

## Codex

已经跑完：

```bash
htextract \
  --agent codex \
  --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl \
  --summary
```

如果 session 目录或 `CODEX_HOME/sessions` 中只有一个明确 session，也可以传目录：

```bash
htextract --agent codex --source <CODEX_HOME>/sessions --summary
```

未来运行时，建议使用独立 `CODEX_HOME`，方便定位 session：

```bash
export CODEX_HOME="$PWD/.codex-session"

codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --model "$MODEL" \
  --json \
  -c model_reasoning_effort=high \
  -c model_reasoning_summary=auto \
  -- "$INSTRUCTION"

htextract --agent codex --source "$CODEX_HOME/sessions" --summary
```

转换器读取 Codex session JSONL 文件。`codex.txt` 这类 stdout 捕获文件对人阅读可能有用，但它不是 trajectory source。

Codex reasoning 有一个重要限制：本工具只能导出 Codex 写入 session JSONL 的明文 reasoning summary。在当前测试中，使用 `codex exec` 和 `model_reasoning_summary=auto`/`detailed` 时，Codex 记录了 `reasoning_output_tokens` 和一个 `reasoning` event，但实际 reasoning body 被保存为 `encrypted_content`，且 `summary` 为空。Harbor 的转换器不会解密该字段，本独立提取器也保持同样行为，因此这类 Codex 运行生成的 trajectory 不会包含 `reasoning_content`。

## 其他 Agent

本工具当前只支持：

- `claude-code`
- `codex`
- `opencode`

vendored source tree 中可能存在其他 Harbor installed-agent adapters，但这个独立 extractor 暂未暴露或验证它们。

当 source agent 输出了明文 reasoning 时，生成的 trajectory 可能包含显式 `reasoning_content`。已验证行为：

- Claude Code 在启用 thinking 时可以导出明文 `reasoning_content`，例如 `--thinking enabled --thinking-display summarized`。
- OpenCode 在 session/export 中包含 `reasoning` parts 时可以导出明文 `reasoning_content`；run-mode JSONL 需要使用 `opencode run --format=json --thinking` 捕获。
- Codex 可能只记录 reasoning token 计数，同时把 reasoning body 存为 encrypted content；这种情况下无法获得 `reasoning_content`。

请把 trajectory 文件视为敏感工件。

## Vendored Source

`src/harbor_trajectory_extractor/vendor/harbor/` 下的 Harbor 兼容 namespace 来源于 Harbor 0.13.2 的 installed-agent trajectory conversion 代码，并加了一层很小的本地兼容代码。归属说明见 `NOTICE`。
