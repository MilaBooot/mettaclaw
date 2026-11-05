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
  action: "remove",
  path: "/workspace/public/test-credentials.txt",
});

await new Promise((resolve) => setTimeout(resolve, 750));
const snapshot = await collectSnapshot(container);
assert.equal(snapshot.health.status, 200);
assert.equal(snapshot.echo.status, 200);
assert.equal(snapshot.app_config.debug, false);
assert.equal(snapshot.app_config_mode, 0o640);
assert.deepEqual(snapshot.exposed_secret_files, []);
assert.equal(snapshot.services_config.enable_test_file_service, false);
assert.equal(snapshot.test_port_open, false);
console.log(JSON.stringify({ ok: true, container, snapshot }, null, 2));
