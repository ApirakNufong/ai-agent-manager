# Validation record

Build environment: Windows, 25 November 2026 (Asia/Bangkok).

## Checks performed

| Check | Result |
| --- | --- |
| React/TypeScript type checking | PASS |
| Vite production build | PASS |
| Python model/schema compilation | PASS |
| Backend regression suite | PASS: 29 tests |
| Mosca 2.8.3 startup with topic authentication/authorization | PASS |
| Real MQTT + separate engine, Manager, three workers | PASS |
| Real Excel read + preparation + numerical/statistical analysis + report | PASS |
| Expected sample yield | 96.05%; gap −1.95 percentage points |
| Actual duplicate START delivery over Mosca | PASS: one execution per agent; duplicates audited |
| Missing Excel source failure | PASS: BOT-001 fails; downstream BOTs do not run |
| Chrome: all 11 navigation screens | PASS |
| Chrome: create and delete agent through UI | PASS |
| Chrome: WebSocket/backend connection | PASS |
| Chrome: light/dark mode, desktop/tablet | PASS; no horizontal overflow at 768 px |
| Browser JavaScript exceptions | None observed |

The test suite covers execution order, duplicate results, stale results, retries, lost workers, acknowledgement timeout, graph/heartbeat validation, schema failures, SQL identifier rejection, path confinement, unsafe upload rejection, immutable versions, approval gates, configuration invalidation, transformation logs, source upload/inspection, and API token enforcement.

## Verification limits

Docker is not installed in the build environment. The Compose stack, PostgreSQL service, MySQL 8.4 service, and real MySQL query have **not been executed here**. The live MQTT integration supplies the MySQL input as a clearly identified fixture; it does not substitute that fixture in production code. Run `python scripts/acceptance.py` against the deployed stack to verify the real-source vertical slice.

The frontend uses Vite 6, React 19, and React Flow 12. Python checks use a project-local Python 3.12 interpreter. Dependency lockfiles are included. Mosca's `jsonschema` dependency is pinned to 1.2.6 for legacy compatibility. Mosca started and routed the test messages on the installed Node 24 host; the Dockerfile uses Node 20 and still needs image-level verification.

The backend test run emits one upstream Starlette deprecation warning about its HTTPX-based TestClient. It does not affect the passing assertions.

## Scope boundaries

This is a functioning implementation of the specified linear three-BOT vertical slice and its management screens, not a claim that every enterprise feature in the full brief is complete.

- Agent and workflow versions, associations, edges, tests, and errors are stored as validated configuration/run documents plus audit history, not all as separate normalized tables.
- One operator token is supported. Multi-user login, roles, and approval separation are not implemented.
- Instructions/prompts are configurable; built-in manufacturing execution is deterministic. No LLM provider is connected.
- Visual workflows are linear. Parallel branches, conditional routing, and distributed engine leadership are not implemented.
- Custom scripts use allowlisted handlers. Uploaded arbitrary executables are not run. ZIP import intentionally imports only SKILL.md.
- Data operations include configured joins, renaming, mapping, casting, dates, missing-value handling, filtering, duplicate removal, sorting, grouping, pivoting, descriptive statistics, configured ratios, cumulative values, time-series aggregation, trends, growth, and z-score outliers. Full free-form analytics/query authoring is not implemented.
- Read-only MySQL uses an approved parameterized SELECT template and metadata inspection. Unrestricted SQL, database writes, and `.xls` are not enabled.
- API sources require administrator-configured public HTTPS host allowlists. Live external API connectivity has not been tested.
- Stop prevents downstream work; it does not immediately interrupt already-running read-only work.
- No cloud/VPS deployment was performed. The unrelated VPS connection file in the parent workspace was not read or used.
