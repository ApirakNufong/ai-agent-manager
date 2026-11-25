---
{
  "id": "statistical-analysis",
  "version": "1.0.0",
  "type": "script",
  "handler": "statistical-analysis",
  "permissions": [
    "data:read",
    "dataset:write"
  ],
  "dependencies": [],
  "input_schema": {
    "type": "object",
    "required": [
      "dataset_id"
    ]
  },
  "output_schema": {
    "type": "object",
    "required": [
      "statistics"
    ]
  },
  "config": {}
}
---

# statistical-analysis

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
