---
{
  "id": "excel-reader",
  "version": "1.0.0",
  "type": "connector",
  "handler": "excel-reader",
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
      "target_dataset"
    ]
  },
  "config": {
    "source": "excel-targets",
    "sheet": "Targets"
  }
}
---

# excel-reader

Execute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.
