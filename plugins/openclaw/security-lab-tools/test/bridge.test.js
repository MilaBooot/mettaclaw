import assert from "node:assert/strict";
import test from "node:test";

import { collectorArgs, controlArgs, inspectArgs, validateContainerName } from "../dist/bridge.js";

test("accepts only a bounded Docker container identifier", () => {
  assert.equal(validateContainerName("omega-security-lab"), "omega-security-lab");
  for (const value of ["", "../host", "lab;whoami", "lab name", "a".repeat(65)]) {
    if (value === "") {
      assert.equal(validateContainerName(value), "omega-security-lab");
    } else {
      assert.throws(() => validateContainerName(value), /invalid/);
    }
  }
});

test("builds fixed docker exec argument arrays without a shell", () => {
  assert.deepEqual(controlArgs("omega-security-lab"), [
    "exec", "-i", "omega-security-lab", "python", "/opt/security-lab/bin/control.py",
  ]);
  assert.deepEqual(collectorArgs("omega-security-lab"), [
    "exec", "omega-security-lab", "python", "/opt/security-lab/bin/collector.py",
  ]);
  assert.deepEqual(inspectArgs("omega-security-lab"), [
    "inspect", "omega-security-lab",
  ]);
});
