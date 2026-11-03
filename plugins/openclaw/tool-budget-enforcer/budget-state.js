export const BUDGET_MARKER_PREFIX = "OMEGA_TOOL_BUDGET_V1 ";

export function parseBudgetMarker(prompt) {
  if (typeof prompt !== "string") return null;
  const firstLine = prompt.split(/\r?\n/, 1)[0];
  if (!firstLine.startsWith(BUDGET_MARKER_PREFIX)) return null;
  let payload;
  try {
    payload = JSON.parse(firstLine.slice(BUDGET_MARKER_PREFIX.length));
  } catch {
    throw new Error("invalid Omega tool-budget marker");
  }
  const limit = payload?.max_tool_calls;
  if (!Number.isSafeInteger(limit) || limit < 1) {
    throw new Error("Omega max_tool_calls must be a positive integer");
  }
  return { maxToolCalls: limit };
}

function identityKeys(event = {}, ctx = {}) {
  const values = [
    ["run", event.runId],
    ["run", ctx.runId],
    ["session", ctx.sessionKey],
    ["session-id", ctx.sessionId],
  ];
  return [...new Set(values
    .filter(([, value]) => typeof value === "string" && value.length > 0)
    .map(([kind, value]) => `${kind}:${value}`))];
}

export class ToolBudgetRegistry {
  constructor(agentIds) {
    this.agentIds = new Set(agentIds);
    this.states = new Map();
  }

  isManaged(ctx = {}) {
    return this.agentIds.has(ctx.agentId);
  }

  begin(prompt, ctx = {}) {
    if (!this.isManaged(ctx)) return { managed: false };
    let budget;
    try {
      budget = parseBudgetMarker(prompt);
    } catch (error) {
      return { managed: true, error: error.message };
    }
    if (!budget) {
      return { managed: true, error: "missing Omega tool-budget marker" };
    }
    const keys = identityKeys({}, ctx);
    if (keys.length === 0) {
      return { managed: true, error: "OpenClaw did not provide run correlation" };
    }
    const state = { limit: budget.maxToolCalls, used: 0, keys };
    for (const key of keys) this.states.set(key, state);
    return { managed: true, limit: state.limit };
  }

  beforeToolCall(event = {}, ctx = {}) {
    if (!this.isManaged(ctx)) return undefined;
    const state = identityKeys(event, ctx)
      .map((key) => this.states.get(key))
      .find(Boolean);
    if (!state) {
      return {
        block: true,
        blockReason: "Omega worker has no active tool-call budget",
      };
    }
    if (state.used >= state.limit) {
      return {
        block: true,
        blockReason: `Omega max_tool_calls exhausted (${state.used}/${state.limit})`,
      };
    }
    state.used += 1;
    return undefined;
  }

  end(event = {}, ctx = {}) {
    const states = new Set(
      identityKeys(event, ctx).map((key) => this.states.get(key)).filter(Boolean),
    );
    for (const state of states) {
      for (const key of state.keys) this.states.delete(key);
    }
  }

  stopRunIds(runIds = []) {
    const states = new Set(
      runIds.map((runId) => this.states.get(`run:${runId}`)).filter(Boolean),
    );
    for (const state of states) {
      for (const key of state.keys) this.states.delete(key);
    }
  }
}
