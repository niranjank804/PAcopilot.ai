# Changelog

## 2026-07-25

### Added
- **House-Style Code Generation** — the TI and Developer agents now call `search_knowledge_base` before drafting any TurboIntegrator process, rule, or feeder, learn the organization's naming/logging/error-handling/comment conventions from whatever reference material exists, and write new code in that same style rather than generic TM1 templates. When no exact reference exists, the style is inferred from whatever standards the Knowledge Base does hold, falling back to generic TM1 practice only when none exist at all — and saying so plainly.
- TI process drafts (`propose_process_update`) can now declare a `datasource_type`, its variables, and its parameters, so a process meant to read a file (e.g. an ASCII/CSV import) actually compiles instead of referencing undefined source columns.
