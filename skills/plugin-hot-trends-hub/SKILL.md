---
name: plugin-hot-trends-hub
description: 热点资讯聚合 - 全网热点新闻资讯排行榜，包括知乎、头条、微博、36氪、豆瓣、掘金等平台的新闻热榜。当需要执行该插件提供的功能时可使用此技能。
metadata:
  requires:
    bins: ["curl"]
    env: ["LINKAI_API_KEY"]
---

# 热点资讯聚合

## Setup

This skill requires a LinkAI API Key.

1. Get your API Key from [LinkAI Console](https://link-ai.tech/console/interface)
2. Set the environment variable: `export LINKAI_API_KEY=Link_xxxxxxxxxxxx`

## Skill Args Definition

```json
{
    "type": "function",
    "function": {
        "name": "plugin-hot-trends-hub",
        "description": "热点资讯聚合 - 全网热点新闻资讯排行榜，包括知乎、头条、微博、36氪、豆瓣、掘金等平台的新闻热榜。当需要执行该插件提供的功能时可使用此技能。",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "用户的请求内容"
                }
            },
            "required": [
                "input"
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
    "code": "hot-trends-hub",
    "input": "用户请求内容"
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
