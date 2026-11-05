export declare function validateContainerName(value?: string): string;
export declare function controlArgs(containerName: string): string[];
export declare function collectorArgs(containerName: string): string[];
export declare function inspectArgs(containerName: string): string[];
export declare function runDocker(args: string[], input?: string, timeoutMs?: number): Promise<string>;
export declare function assertLabContainer(containerName: string): Promise<void>;
export declare function invokeControl(containerName: string, payload: Record<string, unknown>): Promise<unknown>;
export declare function collectSnapshot(containerName: string): Promise<unknown>;
