# Services Layer — Agent Context

> Subdirectory-specific context for the `src/services/` layer.
> See the root [AGENTS.md](../../AGENTS.md) for repository-wide rules.

---

## Rules

1. **Service Instantiation**: Every service class should be instantiable with minimal
   dependencies. Use constructor parameters for `db: AsyncSession`, `user: User`, etc.

2. **Dependency Injection**: Receive `AsyncSession` as a parameter — never create engines
   or sessions directly. The session lifecycle is managed by FastAPI's dependency injection.

3. **Error Handling**: External API calls must be wrapped in `try/except` with proper
   error classification using the taxonomy from `observability/errors.py`:
   - `USER_ERROR` (400) — Bad input from user
   - `VALIDATION_ERROR` (422) — Schema mismatch
   - `SYSTEM_ERROR` (500) — Internal failure
   - `EXTERNAL_API_ERROR` (502) — Third-party failure
   - `TIMEOUT` (504) — Deadline exceeded
   - `RATE_LIMIT` (429) — Throttled

4. **Observability**: Use `observability_execute_tool()` wrapper for any tool execution.
   All methods must use `logger = logging.getLogger(__name__)`.

5. **Import Direction**: Services must **never** import from `src/routers/`. Cross-service
   calls go through explicit service method calls.

6. **Harness Integration**: New agent types must inherit `HarnessedExecutionMixin` from
   `harness/mixin.py`. See below for the integration pattern.

---

## Key Service Relationships

```
ExecutionOrchestrator
    ├── IntentProcessor (classify user intent)
    ├── ToolRouter / ToolSelector (semantic tool matching)
    ├── DynamicToolRegistry (runtime tool manifest)
    ├── ToolExecutor (dispatch to services)
    ├── Harness Components (guardrails, feedback, quality)
    └── LLMService (AI provider abstraction)

ConversationalAgentService
    ├── ToolExecutor (inner tool-calling loop)
    ├── ConversationContextManager (Redis memory)
    ├── HarnessedExecutionMixin (runtime harness)
    └── LLMService

BaseAgent (autonomous agents)
    ├── HarnessedExecutionMixin (runtime harness)
    └── LLMService
```

---

## Harness Integration Pattern

When creating a new agent type:

```python
from .harness.mixin import HarnessedExecutionMixin

class MyNewAgent(HarnessedExecutionMixin):
    def __init__(self, db, user):
        self.db = db
        self.user = user
        self._init_harness("my_new_agent")  # Initialize harness components

    async def process_message(self, message: str) -> str:
        # Reset per-turn state
        self._harness_reset_turn()

        # Build agent context for system prompt
        context = await self._harness_build_context(
            user=self.user,
            conversation_type="chat",
            db=self.db,
        )

        # ... your agent logic ...

        # Pre-execution: validate tool calls
        guardrail = await self._harness_validate_tool_call(
            tool_name="some_tool",
            arguments={"key": "value"},
            user=self.user,
            available_tools=["some_tool", "other_tool"],
        )
        if not guardrail.passed:
            correction = await self._harness_handle_guardrail_failure(guardrail)
            # Inject correction into LLM conversation

        # Post-execution: evaluate response quality
        score = await self._harness_evaluate_response(
            response=response_text,
            user_intent=message,
            tools_used=tools_called,
        )
        if self._harness_should_block_response(score):
            return self._harness_get_safe_fallback()

        return response_text
```

---

## Tool Registration Pattern

When adding a new tool to an existing service:

```python
# 1. In platform_registry.py — add tool schema
"my_new_tool": {
    "name": "my_new_tool",
    "description": "What this tool does",
    "inputSchema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"]
    }
}

# 2. In tool_executor.py — add dispatch
elif tool_name == "my_new_tool":
    result = await self._execute_my_platform_tool(tool_name, arguments)

# 3. In the service method
async def _execute_my_platform_tool(self, tool_name, arguments):
    service = MyPlatformService(self.db, self.user)
    return await service.my_new_method(**arguments)
```

---

## File Naming Conventions

| Pattern | Example | Purpose |
|---|---|---|
| `<platform>_service.py` | `slack_service.py` | Platform integration service |
| `<platform>_router.py` | `slack_router.py` | HTTP endpoints for platform |
| `<domain>_service.py` | `billing_service.py` | Domain-specific business logic |
| `<platform>_workflow_trigger.py` | `slack_workflow_trigger.py` | Webhook-to-workflow bridge |
| `test_<module>.py` | `test_slack_service.py` | Test file (mirrors source file) |
