# 🦐 虾米配置（OpenClaw Agent）

守东（@hushoudong77）的个人 AI 助理 **虾米** 的完整配置备份。

## 目录结构

```
shrimp-config/
├── README.md               # 本文件
├── workspace/              # 虾米人格定义 & 工作区规则
│   ├── AGENTS.md           # 虾米自主进化机制、WAL协议、主动预判
│   ├── SOUL.md             # 人格定义（身份/核心性格/行为准则）
│   ├── MEMORY.md           # 长期记忆（守东信息/偏好/规则/股票池）
│   ├── USER.md             # 守东个人信息
│   ├── TOOLS.md            # 本地工具笔记（知识库路径等）
│   ├── HEARTBEAT.md        # 心跳巡检配置
│   └── IDENTITY.md         # 身份标识
├── memory/                 # 日常记忆存档
│   ├── YYYY-MM-DD.md       # 每日日志
│   ├── learnings.md        # 错误/教训记录
│   ├── outcome-journal.md  # 决策复盘
│   └── vlog-workflow.md    # Vlog工作流
├── config/
│   └── openclaw.json       # OpenClaw Gateway 配置（脱敏模板）
└── skills/                 # （引用仓库根 skills/ 目录）
```

## 部署说明

1. 将 `workspace/` 下的文件复制到 OpenClaw 工作区（默认 `~/.openclaw/workspace/`）
2. `config/openclaw.json` 是脱敏模板，需填入真实 API Key 后放入 `~/.openclaw/`
3. `memory/` 为日常运行日志，按需同步
4. 所需技能（mx-data, mx-search, mx-xuangu, mx-moni, mx-zixuan 等）在根目录 `skills/` 下

## 对应仓库

- 仓库：`hushoudong77-source/federal-advisor`
- 守护东的 A 股投资决策系统 & 虾米 AI 助理完整配置
