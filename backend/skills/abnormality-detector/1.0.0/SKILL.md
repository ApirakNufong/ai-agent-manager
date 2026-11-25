---
{
  "id": "abnormality-detector",
  "version": "1.0.0",
  "type": "script",
  "handler": "abnormality-detector",
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
      "abnormalities"
    ]
  },
  "config": {
    "z_threshold": 3
  }
}
---

# abnormality-detector

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
