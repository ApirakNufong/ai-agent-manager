---
{
  "id": "mysql-reader",
  "version": "1.0.0",
  "type": "connector",
  "handler": "mysql-reader",
  "permissions": [
    "data:read",
    "dataset:write"
  ],
  "dependencies": [],
  "input_schema": {
    "type": "object",
    "required": []
  },
  "output_schema": {
    "type": "object",
    "required": [
      "actual_dataset"
    ]
  },
  "config": {
    "source": "mysql-production",
    "table": "production"
  }
}
---

# mysql-reader

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
