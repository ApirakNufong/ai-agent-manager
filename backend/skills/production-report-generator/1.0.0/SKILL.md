---
{
  "id": "production-report-generator",
  "version": "1.0.0",
  "type": "script",
  "handler": "production-report-generator",
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
      "report_url"
    ]
  },
  "config": {}
}
---

# production-report-generator

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
