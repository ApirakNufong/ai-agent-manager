---
{
  "id": "data-preparation",
  "version": "1.0.0",
  "type": "script",
  "handler": "data-preparation",
  "permissions": [
    "data:read",
    "dataset:write"
  ],
  "dependencies": [],
  "input_schema": {
    "type": "object",
    "required": [
      "actual_dataset",
      "target_dataset"
    ]
  },
  "output_schema": {
    "type": "object",
    "required": [
      "dataset_id"
    ]
  },
  "config": {
    "join_keys": [
      "production_date",
      "product_code"
    ]
  }
}
---

# data-preparation

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
