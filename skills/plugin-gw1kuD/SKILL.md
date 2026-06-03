---
name: plugin-gw1kuD
description: 新闻早报 - 获取每日新闻资讯早报。当需要执行该插件提供的功能时可使用此技能。
metadata:
  requires:
    bins: ["curl"]
    env: ["LINKAI_API_KEY"]
---

# 新闻早报

## Setup

This skill requires a LinkAI API Key.

1. Get your API Key from [LinkAI Console](https://link-ai.tech/console/interface)
2. Set the environment variable: `export LINKAI_API_KEY=Link_xxxxxxxxxxxx`

## Skill Args Definition

```json
{
    "type": "function",
    "function": {
        "name": "plugin-gw1kuD",
        "description": "新闻早报 - 获取每日新闻资讯早报。当需要执行该插件提供的功能时可使用此技能。",
        "parameters": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "请求token",
                    "default": "clkvrgabxsmtufqbqtss2ooanfrjlw"
                },
                "format": {
                    "type": "string",
                    "description": "返回格式，json,image",
                    "default": "json"
                }
            },
            "required": [
                "token",
                "format"
            ]
        }
    }
}
```

## Usage

**Example**:

```bash
curl -X POST "https://api.link-ai.tech/v1/plugin/execute" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LINKAI_API_KEY" \
  -d '{
    "code": "gw1kuD",
    "args": {
        "token": "clkvrgabxsmtufqbqtss2ooanfrjlw",
        "format": "json"
    }
}'
```

> 建议设置超时时间为 120s。

**Response**:

```json
{
    "success": true,
    "code": 200,
    "message": "success",
    "data": "<execution result>"
}
```
