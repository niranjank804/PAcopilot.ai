# Developing AI Features in PA-Copilot

A practical guide to how the AI layer is built and how to extend it — written
from the Visualize and Explain Error features (built 2026-07-23) as worked
examples. If you're adding a new AI-powered capability, the fastest path is
usually: **find the closest existing feature, copy its shape.**

---

## 1. The mental model

Everything goes through one place: `AIOrchestrator.chat()` /
`AIOrchestrator.stream_chat()` in `backend/src/ai/orchestrator.py`. Nothing
else in the codebase calls Anthropic directly.

```
User request
    │
    ▼
API endpoint (api/v1/*.py)
    │
    ▼
Some *Service (knowledge_service, generate_visualization, ...)
    │
    ▼
ai_orchestrator.chat(agent=..., message=..., system=...)
    │
    ├── no agent  →  one-shot call to the provider, no tools
    │
    └── agent set →  bounded tool-calling loop:
            provider.chat() → model requests a tool call
                → look up the tool in the Tool Registry
                → tool.execute() runs real backend logic
                → result fed back to the model
                → repeat until the model stops asking for tools
                  (capped by persona.max_tool_rounds, hard ceiling 15)
```

There is **no separate intent classifier or planner**. The model's own
native tool-calling *is* the planner — it decides which tool to call each
round based on what came back from the last one. This has been the
project's standing decision since Phase 15 and has been re-confirmed every
time a "planner/classifier" layer gets proposed since. Don't add one.

### The three registries

| Registry | Location | What it holds |
|---|---|---|
| **Tool Registry** | `src/ai/tools/registry.py` | Every function the AI is allowed to call (`list_cubes`, `execute_mdx`, ...) |
| **Prompt Registry** (personas) | `src/ai/prompts/*.yaml` | Named system prompts + curated tool subsets (`developer`, `analyst`, ...) |
| **Provider Registry** | `src/ai/registry.py` | Which LLM provider backs a model name (currently just Anthropic) |

---

## 2. Adding a new AI tool

A tool is a typed, permission-gated function the model can call mid-conversation.

**1. Does the backend capability already exist?** Tools are thin wrappers —
if `tm1_integration_service` (or another `*_service`) doesn't have the
method yet, add it there first (see §4 below), one layer down.

**2. Write the tool class.** Copy the shape of an existing one — e.g.
`src/ai/tools/tm1/cells.py::ExecuteMDXTool`:

```python
class ExecuteMDXTool(Tool):
    name = "execute_mdx"                    # what the model calls it
    description = "..."                     # the model reads this to decide *when* to call it — be specific about limits/caveats here
    required_permission = "tm1.read"        # checked inside execute(), not via FastAPI Depends — tools don't run through routing
    input_schema = { ... }                  # JSON schema, becomes the model's function signature

    async def execute(self, db, *, organization_id, user_id, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(...)
        # ... call the real service method, return a JSON string
```

**3. Register it** in `src/ai/tools/registry.py` — add the import and add
an instance to the `TOOLS` dict literal.

**4. Cap anything unbounded.** Every tool that can return a large/unbounded
result caps it: `MAX_CELLS = 500` in `cell_service.py`, `MAX_ELEMENTS = 200`
in `dimension_service.py`, `MAX_NODES = 80` in the graph traversal,
`truncate_code()` for rule/process text. A tool with no cap is a tool that
can blow up context or hang on a bad query — always add one.

**5. Test it** the same way `tests/unit/ai/test_tools.py` tests the others:
a `fake_tm1_client` fixture (`MagicMock` with the relevant TM1py method
stubbed), call `.execute()` directly, assert the JSON output.

---

## 3. Adding a new persona

Personas are **data, not code** — YAML files in `src/ai/prompts/`, loaded
once at import time by `src/ai/agents/registry.py::_load_all_personas()`.
Adding one is just adding a file:

```yaml
name: analyst                      # must be unique — duplicate names fail app startup, not silently
description: >-
  One sentence — shown in the agent picker UI.
system_prompt: >-
  Full instructions for this specialist. Be explicit about what it must
  verify before acting (e.g. "never guess element names, confirm with
  list_dimension_elements first") — this is most of what makes a persona
  actually reliable vs. just a label.
tool_names:
  - list_cubes
  - execute_mdx
  # ... the curated subset this persona is allowed to use
max_tool_rounds: 10                # optional, default 5, hard ceiling 15
safety_notes:
  - >-
    What this persona explicitly cannot do (e.g. "cannot access security
    groups", "can only draft, never execute"). Required — every persona
    must have at least one (enforced by test_every_persona_has_safety_notes).
```

That's it — no Python change needed. The loader picks up any `*.yaml` file
in that directory automatically. `GET /ai/agents` and the frontend's agent
picker both reflect it immediately on restart.

**Checklist before shipping a new persona:**
- Every tool name in `tool_names` must exist in the Tool Registry
  (`test_every_persona_tool_name_exists_in_the_tool_registry` enforces this).
- Update the expected persona count/name-set in 3 test files whenever you
  add one: `tests/unit/ai/test_agents.py`,
  `tests/integration/ai/test_ai_conversations_api.py`,
  `tests/integration/ai/test_ai_tools_api.py`.

---

## 4. Building a whole new AI-powered feature, end to end

Worked example: **Visualize** (`src/ai/visualization.py` +
`POST /tm1/connections/{id}/visualize` + `frontend/src/app/(app)/visualize/page.tsx`).

**Step 1 — does the backend even have the data-access capability yet?**
Check the relevant `src/tm1/services/*_service.py` (or equivalent). If not,
add it there first, following the existing pattern exactly: takes a raw
TM1py `client` + `connection_id`, goes through
`call_with_resilience(connection_id, client.some.method, ...)`, returns a
small typed result object. See `cell_service.py::execute_mdx()` — this is
the *only* layer that touches TM1py directly.

**Step 2 — wire it into `TM1IntegrationService`** (`src/tm1/service.py`) —
the one method every API route and AI tool calls through. It resolves the
connection, gets a cached client, delegates to the service function from
step 1. This is the layer that enforces "you can only touch connections in
your own org" (via `get_connection()`).

**Step 3 — decide: does the model need to reason its way there, or is it a
fixed operation?**
- Fixed operation (upload a file, delete a document) → plain API endpoint,
  no AI involved.
- Needs the model to find the right object / write a query / compose
  multiple facts → route it through `ai_orchestrator.chat(agent=...)`,
  reusing an existing persona if one fits, or adding a new one (§3).

**Step 4 — write the orchestration function**, if the feature does more
than one AI call's worth of work. `generate_visualization()` in
`src/ai/visualization.py` is the template:

```python
async def generate_visualization(db, *, organization_id, user_id, connection_id, query):
    # 1. Ask the agent to do the grounding work via its own tool loop —
    #    don't hand-roll a "first look up X, then look up Y" pipeline,
    #    the agent's native tool-calling already does this.
    chat_result = await ai_orchestrator.chat(
        db, organization_id=organization_id, user_id=user_id,
        message=f"...instructions telling it exactly what shape to answer in...",
        agent="analyst",
    )

    # 2. Parse the model's final answer for the structured piece you need
    #    (a fenced ```json block worked well — ask for it explicitly).
    match = _JSON_BLOCK.search(chat_result.content)
    ...

    # 3. Re-derive the actual result YOURSELF from what the model reported,
    #    rather than trying to read it back off the model's own tool calls.
    result = await tm1_integration_service.execute_mdx(db, connection_id, organization_id, mdx)
    return VisualizationResult(...)
```

**Why step 3 re-executes instead of reading the tool-call result back:**
`AIToolExecution.result_summary` (the persisted audit-log row for each tool
call the model makes) is deliberately truncated to 500 characters in
`orchestrator.py::_execute_tool_call()` — that's correct for an audit trail
but means it is **not a reliable source for real feature data**. If your
feature needs the *full* result of something the agent did, re-run that
specific operation yourself in your orchestration function once you know
what to run — don't try to extract it from the tool-execution log.

**Step 5 — API endpoint.** Same shape as every other endpoint in
`api/v1/tm1.py` / `api/v1/knowledge.py`: `Depends(get_db)`,
`Depends(require_permission("..."))`, call the service/orchestration
function, wrap the result in `ApiResponse[YourResponseSchema]`.

**Step 6 — frontend page.** Copy an existing page's shape
(`knowledge/page.tsx` is the simplest full example: TanStack Query for GET,
`useMutation` for the POST, `isError → isPending → data` ordering always,
never bare `isLoading`). Add the route to `NAV_ITEMS` in
`components/app-sidebar.tsx`.

---

## 5. Testing conventions

- **Unit tests** for pure service functions: mock the TM1py client with
  `MagicMock`, stub the specific method used, assert the return shape.
  See `tests/unit/tm1/test_cell_service.py`.
- **Unit tests** for tools: same TM1py mock, but call `Tool().execute(...)`
  directly and assert the JSON string output. See `tests/unit/ai/test_tools.py`.
- **Integration tests** for endpoints that call the AI orchestrator: swap
  `PROVIDERS["anthropic"]` for a `FakeProvider` (a small `AIProvider`
  subclass whose `chat()` returns a canned `ChatResponse`). Since
  `_run_tool_loop` stops as soon as `stop_reason != "tool_use"`, a fake
  provider returning `stop_reason="end_turn"` on the first call exercises
  your endpoint's *parsing* logic without needing to simulate a multi-round
  tool-calling conversation. See `tests/integration/tm1/test_visualize_api.py`.
- Always add a **permission-denied test**. Note: several permissions
  (`knowledge.read`, `ai.chat`, `tm1.read` for Planner/Analyst) are granted
  to *every* seeded role except one gap case — check
  `backend/scripts/seed_permissions.py`'s `ROLE_PERMISSIONS` before writing
  a "Viewer gets 403" test; if the permission is in
  `GENERAL_ROLE_PERMISSIONS`, Viewer actually has it, and you need a user
  with **no role granted at all** to get a real 403.

Run the full suite before considering anything done:
```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q --ignore=tests/live
```

---

## 6. Live verification workflow

Passing tests is not the same claim as "this works." The standing practice
for this project is to actually drive the running app in a browser against
real backend + (when relevant) the real TM1 connection before calling a
feature done.

**Playwright isn't a permanent project dependency** — it's installed
per-session into a scratch directory when needed:
```bash
mkdir some-scratch-dir && cd some-scratch-dir
npm init -y && npm install playwright
npx playwright install chromium
```

**Don't touch real user accounts to test.** Rather than resetting a real
user's password, create a scoped throwaway user directly against the DB
(same org as the TM1 connection you need, granted a real role via
`role_repository.get_system_role()` + `user_role_repository.create()`),
drive the app as that user, then delete it afterward. See the pattern used
to create/delete the `roundverify` user this round.

**Write a driver script**, not ad hoc commands — log in, navigate, fill
fields by real selector (check the actual `.tsx` for `name=`/`aria-label`
attributes rather than guessing), take a screenshot, print the rendered
page text. `getByRole(..., { exact: true })` beats `has-text()`/`text=`
substring matching once there's real data on the page — TM1 object names
have repeatedly collided with intended substring matches (a "Graph" tab
matched a "Geography" badge; a "Reset" button matched a process literally
named `reset_employee_input_to_orig`).

---

## 7. Known dev-environment gotcha: the orphaned-socket bug

Killing a `uvicorn` process on Windows sometimes leaves the port itself
reporting `LISTEN` under the dead PID (`netstat -ano | grep LISTENING`
still shows it after the PID is confirmed gone via `tasklist`). Restarting
on the *same* port after this does not reliably work, even repeatedly.

**The only fix that has worked:** move to a brand-new port that has never
been used in this session, rather than trying to free the stuck one.
Update `frontend/.env.local`'s `NEXT_PUBLIC_API_URL` to match and restart
the frontend dev server too (`NEXT_PUBLIC_*` vars are read at process
start). This has recurred 6+ times across ports 8000→8001→8002→8003→8004 —
if it keeps happening, it's worth resolving at the OS level (WSL2
networking reset, or a reboot), not something fixable from inside a shell.
