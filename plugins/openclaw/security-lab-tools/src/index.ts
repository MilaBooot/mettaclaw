import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

import { collectSnapshot, invokeControl, validateContainerName } from "./bridge.js";

const configSchema = Type.Object({
  containerName: Type.Optional(Type.String({
    default: "omega-security-lab",
    pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
  })),
}, { additionalProperties: false });

export default defineToolPlugin({
  id: "omega-security-lab",
  name: "Omega Security Lab Tools",
  description: "Narrow evaluation tools restricted to one labeled, disposable security lab container.",
  configSchema,
  tools: (tool) => [
    tool({
      name: "omega_lab_read",
      description: "List, inspect, or read files only inside /workspace in the disposable Omega security lab.",
      optional: true,
      parameters: Type.Union([
        Type.Object({ action: Type.Literal("list") }, { additionalProperties: false }),
        Type.Object({ action: Type.Literal("actions") }, { additionalProperties: false }),
        Type.Object({ action: Type.Literal("snapshot") }, { additionalProperties: false }),
        Type.Object({
          action: Type.Literal("read"),
          path: Type.String({ description: "Path below /workspace." }),
        }, { additionalProperties: false }),
      ]),
      async execute(params, config) {
        const container = validateContainerName(config.containerName);
        if (params.action === "snapshot") return collectSnapshot(container);
        return invokeControl(container, params);
      },
    }),
    tool({
      name: "omega_lab_write",
      description: "Write, chmod, or remove one existing regular file below /workspace in the disposable lab. No shell execution is available.",
      optional: true,
      parameters: Type.Union([
        Type.Object({
          action: Type.Literal("write"),
          path: Type.String(),
          text: Type.String({ maxLength: 16384 }),
        }, { additionalProperties: false }),
        Type.Object({
          action: Type.Literal("chmod"),
          path: Type.String(),
          mode: Type.Union([
            Type.Literal("0600"),
            Type.Literal("0640"),
            Type.Literal("0644"),
          ]),
        }, { additionalProperties: false }),
        Type.Object({
          action: Type.Literal("remove"),
          path: Type.String(),
        }, { additionalProperties: false }),
      ]),
      async execute(params, config) {
        return invokeControl(validateContainerName(config.containerName), params);
      },
    }),
    tool({
      name: "omega_lab_verify",
      description: "Collect a live, read-only security and functionality snapshot from the disposable lab for independent review.",
      optional: true,
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute(_params, config) {
        return collectSnapshot(validateContainerName(config.containerName));
      },
    }),
  ],
});
