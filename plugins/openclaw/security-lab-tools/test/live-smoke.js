import assert from "node:assert/strict";

import { collectSnapshot, invokeControl } from "../dist/bridge.js";

const container = process.env.OMEGA_SECURITY_LAB_CONTAINER || "omega-security-lab";

const appFile = await invokeControl(container, {
  action: "read",
  path: "/workspace/config/app.json",
});
const app = JSON.parse(appFile.text);
app.debug = false;
await invokeControl(container, {
  action: "write",
  path: "/workspace/config/app.json",
  text: `${JSON.stringify(app, null, 2)}\n`,
});
await invokeControl(container, {
  action: "chmod",
  path: "/workspace/config/app.json",
  mode: "0640",
});

const servicesFile = await invokeControl(container, {
  action: "read",
  path: "/workspace/config/services.json",
});
const services = JSON.parse(servicesFile.text);
services.enable_test_file_service = false;
await invokeControl(container, {
  action: "write",
  path: "/workspace/config/services.json",
  text: `${JSON.stringify(services, null, 2)}\n`,
});
await invokeControl(container, {
  action: "chmod",
  path: "/workspace/config/services.json",
  mode: "0640",
});
await invokeControl(container, {
  action: "write",
  path: "/workspace/public/test-credentials.txt",
  text: "# synthetic credential removed\n",
});
await invokeControl(container, {
  action: "chmod",
  path: "/workspace/public/test-credentials.txt",
  mode: "0600",
});

await new Promise((resolve) => setTimeout(resolve, 750));
const snapshot = await collectSnapshot(container);
assert.equal(snapshot.health.status, 200);
assert.equal(snapshot.echo.status, 200);
assert.equal(snapshot.app_config.debug, false);
assert.deepEqual(snapshot.file_modes, {
  "app.json": 0o640,
  "services.json": 0o640,
  "test-credentials.txt": 0o600,
});
assert.deepEqual(snapshot.exposed_secret_files, []);
assert.equal(snapshot.services_config.enable_test_file_service, false);
assert.equal(snapshot.test_port_open, false);
console.log(JSON.stringify({ ok: true, container, snapshot }, null, 2));
