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
      parameters: Type.Object({
        action: Type.Union([
          Type.Literal("list"),
          Type.Literal("read"),
          Type.Literal("actions"),
          Type.Literal("snapshot"),
        ]),
        path: Type.Optional(Type.String({
          description: "Path below /workspace; required for read.",
        })),
      }, { additionalProperties: false }),
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
      parameters: Type.Object({
        action: Type.Union([
          Type.Literal("write"),
          Type.Literal("chmod"),
          Type.Literal("remove"),
        ]),
        path: Type.String(),
        text: Type.Optional(Type.String({ maxLength: 16384 })),
        mode: Type.Optional(Type.Union([
          Type.Literal("0600"),
          Type.Literal("0640"),
          Type.Literal("0644"),
        ])),
      }, { additionalProperties: false }),
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
