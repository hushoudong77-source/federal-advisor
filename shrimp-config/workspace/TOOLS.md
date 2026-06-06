# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## 培训知识库

- **路径**: `/Users/komamorudong/FangCloudV2/个人文件/培训知识库`
- **规模**: 9671 份 .md 课件，约 332MB
- **话题索引**: `tools/kb_index.md` — 按业务方向/行业/方法论分类
- **搜索命令**:
  - `python3 tools/kb_search.py "关键词"` — 全文搜索，返回文件路径和匹配片段
  - `python3 tools/kb_search.py -l "关键词"` — 只列出文件名
  - `python3 tools/kb_search.py --count "关键词"` — 只统计匹配数
  - `python3 tools/kb_search.py --stats` — 知识库统计
- **手动 grep**: `grep -rl "关键词" /path/to/知识库 --include="*.md"`

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)
