---
name: database-1h7Axcvj
description: 金融数据库 - 金融数据。当需要对该数据库执行增删改查操作时可使用此技能。
metadata:
  requires:
    bins: ["curl"]
    env: ["LINKAI_API_KEY"]
---

# 金融数据库

## Setup

This skill requires a LinkAI API Key.

1. Get your API Key from [LinkAI Console](https://link-ai.tech/console/interface)
2. Set the environment variable: `export LINKAI_API_KEY=Link_xxxxxxxxxxxx`

## Database Schema

_No tables found._

## Allowed Operations

- **SELECT** — Query data
- **INSERT** — Insert data
- **UPDATE** — Update data

## Skill Args Definition

This skill provides two APIs:

### 1. Get Metadata (table schema)

```json
{{
    "type": "function",
    "function": {{
        "name": "database-1h7Axcvj-meta",
        "description": "Get database metadata including all tables and fields",
        "parameters": {{
            "type": "object",
            "properties": {{
                "code": {{
                    "type": "string",
                    "enum": ["1h7Axcvj"],
                    "description": "Database code"
                }}
            }},
            "required": ["code"]
        }}
    }}
}}
```

### 2. Execute SQL

```json
{{
    "type": "function",
    "function": {{
        "name": "database-1h7Axcvj-sql",
        "description": "Execute SQL query on the database. Use table names from the schema above.",
        "parameters": {{
            "type": "object",
            "properties": {{
                "code": {{
                    "type": "string",
                    "enum": ["1h7Axcvj"],
                    "description": "Database code"
                }},
                "sql": {{
                    "type": "string",
                    "description": "SQL statement to execute. Use the table and field names from the schema."
                }}
            }},
            "required": ["code", "sql"]
        }}
    }}
}}
```

## Usage

### Get metadata

```bash
curl -X GET "https://api.link-ai.tech/v1/database/meta?code=1h7Axcvj" \
  -H "Authorization: Bearer $LINKAI_API_KEY"
```

**Response**:

```json
{{
    "success": true,
    "code": 200,
    "data": {{
        "code": "<database_code>",
        "name": "<database_name>",
        "description": "<description>",
        "type": "BUILTIN",
        "permissions": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "tables": [
            {{
                "name": "<table_name>",
                "description": "<table_description>",
                "fields": [
                    {{ "name": "<field_name>", "type": "<field_type>", "comment": "<field_description>" }}
                ]
            }}
        ]
    }}
}}
```

> Use the `name` from `tables` as table names in SQL, and `fields[].name` as column names.

### Execute SQL

```bash
curl -X POST "https://api.link-ai.tech/v1/database/sql" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LINKAI_API_KEY" \
  -d '{
    "code": "1h7Axcvj",
    "sql": "SELECT * FROM <table_name> LIMIT 10"
}'
```

> 建议设置超时时间为 30s。

**Response** (SELECT):

```json
{{
    "success": true,
    "code": 200,
    "data": {{
        "status": "SUCCESS",
        "data": [{{ "field1": "value1", "field2": "value2" }}],
        "total": 1
    }}
}}
```

**Response** (INSERT/UPDATE/DELETE):

```json
{{
    "success": true,
    "code": 200,
    "data": {{
        "status": "SUCCESS",
        "affected_rows": 1
    }}
}}
```
