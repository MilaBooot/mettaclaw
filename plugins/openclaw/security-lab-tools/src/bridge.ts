import { spawn } from "node:child_process";

const CONTROL_PATH = "/opt/security-lab/bin/control.py";
const COLLECTOR_PATH = "/opt/security-lab/bin/collector.py";
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const MAX_OUTPUT_BYTES = 64 * 1024;

export function validateContainerName(value?: string): string {
  const name = String(value || "omega-security-lab");
  if (!NAME_PATTERN.test(name)) {
    throw new Error("invalid security lab container name");
  }
  return name;
}

export function controlArgs(containerName: string): string[] {
  return [
    "exec", "-i", validateContainerName(containerName),
    "python", CONTROL_PATH,
  ];
}

export function collectorArgs(containerName: string): string[] {
  return [
    "exec", validateContainerName(containerName),
    "python", COLLECTOR_PATH,
  ];
}

export function inspectArgs(containerName: string): string[] {
  return ["inspect", validateContainerName(containerName)];
}

export function runDocker(
  args: string[],
  input = "",
  timeoutMs = 10_000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("docker", args, {
      shell: false,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let exceeded = false;
    const collect = (target: string, chunk: Buffer): string => {
      const next = target + chunk.toString("utf8");
      if (Buffer.byteLength(next, "utf8") > MAX_OUTPUT_BYTES) {
        exceeded = true;
        child.kill();
        return target;
      }
      return next;
    };
    child.stdout.on("data", (chunk: Buffer) => { stdout = collect(stdout, chunk); });
    child.stderr.on("data", (chunk: Buffer) => { stderr = collect(stderr, chunk); });
    child.on("error", reject);
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("security lab Docker operation timed out"));
    }, timeoutMs);
    child.on("close", (code) => {
      clearTimeout(timer);
      if (exceeded) {
        reject(new Error("security lab Docker output exceeded its limit"));
      } else if (code !== 0) {
        reject(new Error(stderr.trim() || `security lab Docker operation failed (${code})`));
      } else {
        resolve(stdout.trim());
      }
    });
    child.stdin.end(input);
  });
}

export async function assertLabContainer(containerName: string): Promise<void> {
  const raw = await runDocker(inspectArgs(containerName));
  const inspected = JSON.parse(raw)?.[0];
  const label = inspected?.Config?.Labels?.["omega.security-lab"];
  if (label !== "container-hardening-v1") {
    throw new Error("refusing Docker access: target lacks the Omega security-lab label");
  }
}

export async function invokeControl(
  containerName: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  await assertLabContainer(containerName);
  const raw = await runDocker(controlArgs(containerName), JSON.stringify(payload));
  const parsed = JSON.parse(raw);
  if (parsed?.ok !== true) {
    throw new Error(parsed?.error || "security lab operation failed");
  }
  return parsed.result;
}

export async function collectSnapshot(containerName: string): Promise<unknown> {
  await assertLabContainer(containerName);
  return JSON.parse(await runDocker(collectorArgs(containerName)));
}
