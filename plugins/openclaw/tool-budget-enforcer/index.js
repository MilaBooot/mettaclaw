import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { ToolBudgetRegistry } from "./budget-state.js";

const DEFAULT_AGENT_IDS = ["research-agent", "coding-agent", "reviewer-agent"];
const BLOCK_MESSAGE = "Omega rejected this worker run because its enforced tool-call budget was missing or invalid.";

export default definePluginEntry({
  id: "omega-tool-budget",
  name: "Omega Tool Budget Enforcer",
  description: "Blocks OpenClaw worker tool calls after Omega's per-run limit.",
  register(api) {
    const configured = api.pluginConfig?.agentIds;
    const agentIds = Array.isArray(configured) && configured.length
      ? configured.filter((value) => typeof value === "string" && value.length)
      : DEFAULT_AGENT_IDS;
    const budgets = new ToolBudgetRegistry(agentIds);

    api.on("before_agent_run", (event, ctx) => {
      const result = budgets.begin(event.prompt, ctx);
      if (result.managed && result.error) {
        return { outcome: "block", reason: result.error, message: BLOCK_MESSAGE };
      }
    });

    api.on("before_tool_call", (event, ctx) => budgets.beforeToolCall(event, ctx));
    api.on("agent_end", (event, ctx) => budgets.end(event, ctx));
    api.on("run_stopped", (event) => budgets.stopRunIds(event.runIds));

    api.registerHttpRoute({
      path: "/plugins/omega-tool-budget/health",
      auth: "gateway",
      match: "exact",
      handler: async (req, res) => {
        if (req.method !== "GET") {
          res.statusCode = 405;
          res.setHeader("Allow", "GET");
          res.end("method not allowed");
          return true;
        }
        res.statusCode = 200;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({
          ok: true,
          id: "omega-tool-budget",
          protocol: 1,
          enforcement: "before_tool_call",
        }));
        return true;
      },
    });
  },
});
