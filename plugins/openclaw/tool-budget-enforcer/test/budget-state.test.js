import assert from "node:assert/strict";
import test from "node:test";

import { ToolBudgetRegistry, parseBudgetMarker } from "../budget-state.js";

const managed = { agentId: "coding-agent", runId: "run-1", sessionKey: "session-1" };

test("parses only a valid first-line budget marker", () => {
  assert.deepEqual(
    parseBudgetMarker('OMEGA_TOOL_BUDGET_V1 {"max_tool_calls":2}\nROLE\nCoding'),
    { maxToolCalls: 2 },
  );
  assert.equal(parseBudgetMarker("ROLE\nOMEGA_TOOL_BUDGET_V1 {}"), null);
  assert.throws(
    () => parseBudgetMarker('OMEGA_TOOL_BUDGET_V1 {"max_tool_calls":0}'),
    /positive integer/,
  );
});

test("allows exactly N calls and blocks N plus one before execution", () => {
  const registry = new ToolBudgetRegistry(["coding-agent"]);
  assert.deepEqual(
    registry.begin('OMEGA_TOOL_BUDGET_V1 {"max_tool_calls":2}\nTask', managed),
    { managed: true, limit: 2 },
  );
  assert.equal(registry.beforeToolCall({ toolName: "read" }, managed), undefined);
  assert.equal(registry.beforeToolCall({ toolName: "exec" }, managed), undefined);
  assert.deepEqual(
    registry.beforeToolCall({ toolName: "write" }, managed),
    { block: true, blockReason: "Omega max_tool_calls exhausted (2/2)" },
  );
});

test("dedicated Omega workers fail closed without an active budget", () => {
  const registry = new ToolBudgetRegistry(["coding-agent"]);
  assert.deepEqual(
    registry.beforeToolCall({ toolName: "exec" }, managed),
    { block: true, blockReason: "Omega worker has no active tool-call budget" },
  );
  assert.equal(
    registry.beforeToolCall(
      { toolName: "exec" },
      { agentId: "unmanaged-agent", runId: "other" },
    ),
    undefined,
  );
});

test("agent completion clears the budget state", () => {
  const registry = new ToolBudgetRegistry(["coding-agent"]);
  registry.begin('OMEGA_TOOL_BUDGET_V1 {"max_tool_calls":1}\nTask', managed);
  registry.end({}, managed);
  assert.match(
    registry.beforeToolCall({ toolName: "read" }, managed).blockReason,
    /no active/,
  );
});
