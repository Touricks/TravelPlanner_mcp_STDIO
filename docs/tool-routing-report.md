---
generated_at: 2026-04-02
project: TravelPlannerAgent
status: approved
total_skills_scanned: 58
skills_included: 19
skills_excluded: 32
skills_uncertain: 7
---

# Tool Routing Report

## Included Skills

| Skill | Source | Rationale |
|-------|--------|-----------|
| sentinel:progress | plugin:sentinel | Session logging and progress.yaml maintenance |
| codex:rescue | plugin:codex | Codex-assisted review, diagnosis, and search tasks |
| codex:setup | plugin:codex | Codex CLI readiness check |
| Notion:create-page | plugin:notion | Stage 6: create parent travel plan page |
| Notion:create-database-row | plugin:notion | Stage 6: populate Itinerary/Restaurant/Hotel/Notices databases |
| Notion:find | plugin:notion | Locate existing travel planner pages for updates |
| Notion:search | plugin:notion | Search workspace for trip content |
| Notion:database-query | plugin:notion | Read back database contents for verification |
| original:web-extractor | plugin:fanshi | Extract POI data from web pages (Stage 2/4 search) |
| codex:review | plugin:codex | Stage 5 structured review of generated YAML/JSON artifacts |
| codex:result | plugin:codex | Parse and present Codex review results |
| playwright (MCP) | plugin:playwright | Stage 7 screenshot verification of Notion output |
| computer-use (MCP) | mcp:computer-use | Stage 7 fallback screenshot capture for native apps |

## Excluded Skills

| Skill | Source | Rationale |
|-------|--------|-----------|
| original:start_simple | plugin:fanshi | Project uses sentinel:start instead |
| original:push | plugin:fanshi | Git push — not specific to this project's pipeline |
| original:tailored-resume-generator | plugin:fanshi | Unrelated domain |
| original:pdf | plugin:fanshi | No PDF generation in pipeline |
| original:langchain-architecture | plugin:fanshi | Architecture explicitly avoids LangChain |
| original:langgraph | plugin:fanshi | Architecture explicitly avoids LangGraph |
| original:plugin-publishing | plugin:fanshi | Not publishing a plugin |
| original:claude-d3js-skill | plugin:fanshi | No d3.js visualization in scope |
| original:xlsx | plugin:fanshi | No spreadsheet work |
| original:humanizer-zh | plugin:fanshi | Not editing prose for AI-pattern removal |
| original:humanizer | plugin:fanshi | Not editing prose for AI-pattern removal |
| original:study-notes-generator | plugin:fanshi | Not generating study materials |
| original:docx | plugin:fanshi | No Word document generation |
| original:latex-posters | plugin:fanshi | No LaTeX poster work |
| original:ml-paper-writing | plugin:fanshi | Not writing papers |
| original:scientific-slides | plugin:fanshi | Not making slides |
| original:skill-creator | plugin:fanshi | Not creating new skills in this project |
| skill-creator:skill-creator | plugin:skill-creator | Not creating new skills in this project |
| frontend-design:frontend-design | plugin:frontend-design | No frontend UI work |
| figma:figma-code-connect | plugin:figma | No Figma design work |
| figma:figma-use | plugin:figma | No Figma design work |
| figma:figma-generate-library | plugin:figma | No Figma design work |
| figma:figma-implement-design | plugin:figma | No Figma design work |
| figma:figma-create-design-system-rules | plugin:figma | No Figma design work |
| figma:figma-generate-design | plugin:figma | No Figma design work |
| ant_prompt:install-ant-hooks | plugin:fanshi | Coding standard hooks — project uses sentinel hooks |
| ant_prompt:remove-ant-hooks | plugin:fanshi | Inverse of above |
| sentinel:submit-issue | plugin:sentinel | Bug reporting for Sentinel itself, not this project |
| Notion:tasks:setup | plugin:notion | Notion task board — project uses progress.yaml instead |
| Notion:tasks:build | plugin:notion | Notion task management — not this project's workflow |
| Notion:tasks:plan | plugin:notion | Notion task management — not this project's workflow |
| Notion:tasks:explain-diff | plugin:notion | Code change docs — not relevant to pipeline |

## Excluded Skills (deprecated / internal)

| Skill | Source | Rationale |
|-------|--------|-----------|
| superpowers:execute-plan | plugin:superpowers | Deprecated |
| superpowers:write-plan | plugin:superpowers | Deprecated |
| superpowers:brainstorm | plugin:superpowers | Deprecated |
| codex:codex-cli-runtime | plugin:codex | Internal helper |
| codex:codex-result-handling | plugin:codex | Internal helper |
| codex:gpt-5-4-prompting | plugin:codex | Internal helper |

## Uncertain — Needs Developer Decision

| Skill | Source | Rationale | Developer Decision |
|-------|--------|-----------|-------------------|
| superpowers:writing-plans | plugin:superpowers | Could help structure multi-stage pipeline implementation plans | |
| superpowers:executing-plans | plugin:superpowers | Could help execute pipeline stages with review checkpoints | |
| superpowers:verification-before-completion | plugin:superpowers | Aligns with Stage 5 review philosophy — verify before claiming done | |
| superpowers:systematic-debugging | plugin:superpowers | Useful if pipeline stages produce unexpected failures | |
| superpowers:subagent-driven-development | plugin:superpowers | Pipeline stages are independent — could parallelize with subagents | |
| ralph-loop:ralph-loop | plugin:ralph-loop | Alternative to sentinel-loop for iterative dev; may conflict | |
| claude-md-management:revise-claude-md | plugin:claude-md | Could help maintain CLAUDE.md as project evolves | |

## Excluded Skills (superpowers — low relevance)

| Skill | Source | Rationale |
|-------|--------|-----------|
| superpowers:brainstorming | plugin:superpowers | Pipeline design already decided |
| superpowers:finishing-a-development-branch | plugin:superpowers | Git branch workflow not primary concern |
| superpowers:dispatching-parallel-agents | plugin:superpowers | Pipeline is linear, not parallel |
| superpowers:writing-skills | plugin:superpowers | Not creating skills |
| superpowers:using-superpowers | plugin:superpowers | Meta-skill for discovering superpowers |
| superpowers:receiving-code-review | plugin:superpowers | Code review feedback handling — not primary workflow |
| superpowers:requesting-code-review | plugin:superpowers | Code review requests — not primary workflow |
| superpowers:test-driven-development | plugin:superpowers | TDD — could be useful but rule engine tests are straightforward |
| superpowers:using-git-worktrees | plugin:superpowers | Worktree isolation not needed for single-pipeline project |

## Developer Notes

> Review the Uncertain skills. The superpowers:writing-plans and superpowers:executing-plans pair may be valuable for structuring the 7-stage pipeline implementation. ralph-loop may conflict with sentinel-loop — recommend choosing one.

## Appendix: Full Global Skill List

| # | Skill | Source | Description |
|---|-------|--------|-------------|
| 1 | update-config | built-in | Configure Claude Code settings.json |
| 2 | keybindings-help | built-in | Customize keyboard shortcuts |
| 3 | simplify | built-in | Review changed code for quality |
| 4 | loop | built-in | Run prompt on recurring interval |
| 5 | schedule | built-in | Create scheduled remote agents |
| 6 | claude-api | built-in | Build apps with Claude API/SDK |
| 7 | code-review:code-review | plugin:code-review | Code review a PR |
| 8 | feature-dev:feature-dev | plugin:feature-dev | Guided feature development |
| 9 | ralph-loop:help | plugin:ralph-loop | Explain Ralph Loop |
| 10 | ralph-loop:ralph-loop | plugin:ralph-loop | Start Ralph Loop |
| 11 | ralph-loop:cancel-ralph | plugin:ralph-loop | Cancel Ralph Loop |
| 12 | agent-sdk-dev:new-sdk-app | plugin:agent-sdk-dev | Create Agent SDK app |
| 13 | hookify:list | plugin:hookify | List hookify rules |
| 14 | hookify:help | plugin:hookify | Hookify help |
| 15 | hookify:hookify | plugin:hookify | Create hooks from conversation |
| 16 | hookify:configure | plugin:hookify | Configure hookify rules |
| 17 | hookify:writing-rules | plugin:hookify | Write hook rules |
| 18 | claude-md-management:revise-claude-md | plugin:claude-md | Update CLAUDE.md with session learnings |
| 19 | claude-md-management:claude-md-improver | plugin:claude-md | Audit and improve CLAUDE.md |
| 20 | codex:setup | plugin:codex | Check Codex CLI readiness |
| 21 | codex:rescue | plugin:codex | Delegate to Codex subagent |
| 22 | codex:codex-cli-runtime | plugin:codex | Internal: Codex runtime |
| 23 | codex:codex-result-handling | plugin:codex | Internal: result presentation |
| 24 | codex:gpt-5-4-prompting | plugin:codex | Internal: GPT prompt crafting |
| 25 | sentinel:progress | plugin:sentinel | Generate progress.yaml entry |
| 26 | sentinel:call-codex | plugin:sentinel | Codex second opinion |
| 27 | sentinel:routing | plugin:sentinel | Tool routing report |
| 28 | sentinel:boundary | plugin:sentinel | Tool boundary declarations |
| 29 | sentinel:sentinel-loop | plugin:sentinel | Iterative dev loop |
| 30 | sentinel:sentinel-export | plugin:sentinel | Export compliance docs |
| 31 | sentinel:start | plugin:sentinel | Project bootstrap |
| 32 | sentinel:submit-issue | plugin:sentinel | Report Sentinel bugs |
| 33 | original:start_simple | plugin:fanshi | Simple project bootstrap |
| 34 | original:push | plugin:fanshi | Git commit and push |
| 35 | original:web-extractor | plugin:fanshi | Extract web page content |
| 36 | original:tailored-resume-generator | plugin:fanshi | Resume generation |
| 37 | original:pdf | plugin:fanshi | PDF manipulation |
| 38 | original:langchain-architecture | plugin:fanshi | LangChain app design |
| 39 | original:langgraph | plugin:fanshi | LangGraph agent design |
| 40 | original:plugin-publishing | plugin:fanshi | Plugin packaging guide |
| 41 | original:claude-d3js-skill | plugin:fanshi | D3.js visualizations |
| 42 | original:xlsx | plugin:fanshi | Spreadsheet operations |
| 43 | original:humanizer-zh | plugin:fanshi | Remove AI patterns (Chinese) |
| 44 | original:humanizer | plugin:fanshi | Remove AI patterns (English) |
| 45 | original:study-notes-generator | plugin:fanshi | Study note generation |
| 46 | original:docx | plugin:fanshi | Word document operations |
| 47 | original:latex-posters | plugin:fanshi | LaTeX posters |
| 48 | original:ml-paper-writing | plugin:fanshi | ML paper writing |
| 49 | original:scientific-slides | plugin:fanshi | Scientific presentations |
| 50 | original:skill-creator | plugin:fanshi | Skill creation guide |
| 51 | skill-creator:skill-creator | plugin:skill-creator | Create/modify skills |
| 52 | frontend-design:frontend-design | plugin:frontend-design | Frontend UI creation |
| 53 | figma:* (6 skills) | plugin:figma | Figma design tools |
| 54 | Notion:* (8 skills) | plugin:notion | Notion workspace tools |
