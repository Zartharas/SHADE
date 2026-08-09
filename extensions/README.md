# extensions/

Empty as of ADR 0004. This directory previously held three standalone,
solo-researcher-scoped prototypes (LLM policy proposer, MCP tool-call
monitor, DP aggregate reporting) that were built, tested standalone, and
then integrated into `shade/` one at a time, each with its own ADR:

- `docs/adr/0002-integrating-llm-policy-proposer.md`
- `docs/adr/0003-integrating-mcp-tool-call-monitor.md`
- `docs/adr/0004-integrating-dp-aggregate-reporting.md`

See `docs/extensions.md` for the full history of what each module
demonstrated standalone and what its integration did and didn't change.

This directory is kept (rather than deleted) as the place any future
standalone prototype should start: see "Working in extensions/" and
"Graduating an extension into shade/" in `CONTRIBUTING.md` for the
process a new addition here should follow.
