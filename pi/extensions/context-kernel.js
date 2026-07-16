import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  formatSize,
  truncateHead,
  withFileMutationQueue,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const BRIDGE = join(ROOT, "pi/runtime/pi_bridge.py");
const SLICE = join(ROOT, "claude-context-kernel/skills/kernel-slice/scripts/slice.py");
const REPO_SLICE = join(ROOT, "claude-context-kernel/skills/kernel-repo-slice/scripts/repo_slice.py");
const AGENTS = join(ROOT, "pi/agents");
const DEFAULT_TOOLS = new Set(
  (process.env.CK_TOOLS ?? "bash,grep,read,find,webfetch")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean),
);
const AGENT_ROLES = new Set(["kernel-scout", "kernel-extractor", "kernel-verifier"]);

function textFromContent(content) {
  return (content ?? [])
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

function runProcess(command, args, { cwd, input, signal, env, timeoutMs = 60_000 } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: { ...process.env, ...env },
      shell: false,
      stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolvePromise(result);
    };
    const abort = () => child.kill("SIGTERM");
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      finish(new Error(`${basename(command)} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", (error) => finish(error));
    child.on("close", (code) => {
      if (signal?.aborted) return finish(new Error("operation cancelled"));
      finish(null, { code: code ?? 1, stdout, stderr });
    });
    if (input !== undefined) {
      child.stdin.end(input);
    }
  });
}

let bridgeTail = Promise.resolve();

async function bridge(payload, signal) {
  // Pi can finalize sibling tools concurrently. Serialize access to the shared
  // read-delta and savings files used by the common Python implementation.
  const operation = bridgeTail.catch(() => {}).then(async () => {
    const result = await runProcess("python3", [BRIDGE], {
      input: JSON.stringify(payload),
      signal,
      timeoutMs: 10_000,
    });
    if (result.code !== 0) throw new Error(result.stderr || "context-kernel bridge failed");
    const line = result.stdout.trim().split("\n").at(-1);
    if (!line) return { error: "empty bridge output" };
    return JSON.parse(line);
  });
  bridgeTail = operation.catch(() => {});
  return operation;
}

function contextBudget(ctx) {
  const usage = ctx.getContextUsage?.();
  const used = Number(usage?.tokens ?? 0);
  const window = Number(ctx.model?.contextWindow ?? usage?.contextWindow ?? 200_000);
  const headroom = Math.max(0, window - used);
  const budget = Math.max(8_000, Math.min(80_000, Math.floor(headroom * 0.4)));
  return { budget, used, window, headroom };
}

async function truncateResult(text) {
  const truncation = truncateHead(text, {
    maxLines: DEFAULT_MAX_LINES,
    maxBytes: DEFAULT_MAX_BYTES,
  });
  if (!truncation.truncated) return { text: truncation.content, details: { truncation } };
  const dir = await mkdtemp(join(tmpdir(), "context-kernel-pi-"));
  const path = join(dir, "output.txt");
  await withFileMutationQueue(path, () => writeFile(path, text, "utf8"));
  const notice = `\n\n[Output truncated to ${truncation.outputLines} lines / ${formatSize(truncation.outputBytes)}. Full output: ${path}]`;
  return { text: truncation.content + notice, details: { truncation, fullOutputPath: path } };
}

async function runSlicer(script, args, ctx, signal, timeoutMs) {
  const result = await runProcess("python3", [script, ...args], {
    cwd: ctx.cwd,
    signal,
    timeoutMs,
  });
  if (result.code !== 0) throw new Error(result.stderr.trim() || `${basename(script)} failed`);
  const combined = result.stderr.trim()
    ? `${result.stderr.trim()}\n\n${result.stdout}`
    : result.stdout;
  return truncateResult(combined);
}

function piInvocation(args) {
  const script = process.argv[1];
  if (script && !script.startsWith("/$bunfs/root/")) {
    return { command: process.execPath, args: [script, ...args] };
  }
  const executable = basename(process.execPath).toLowerCase();
  if (!/^(node|bun)(\.exe)?$/.test(executable)) {
    return { command: process.execPath, args };
  }
  return { command: "pi", args };
}

async function runAgent(role, task, ctx, signal, onUpdate) {
  const prompt = join(AGENTS, `${role}.md`);
  const invocation = piInvocation([
    "--mode", "json",
    "-p",
    "--no-session",
    "--tools", "read,grep,find,bash",
    "--append-system-prompt", prompt,
    `Task: ${task}\n\nContext-kernel package root: ${ROOT}`,
  ]);
  const child = spawn(invocation.command, invocation.args, {
    cwd: ctx.cwd,
    env: { ...process.env, CK_PI_AGENT_ROLE: role },
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let buffer = "";
  let stderr = "";
  let final = "";
  let turns = 0;
  const abort = () => child.kill("SIGTERM");
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
  child.stdout.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      try {
        const event = JSON.parse(line);
        if (event.type === "message_end" && event.message?.role === "assistant") {
          turns += 1;
          final = textFromContent(event.message.content);
          onUpdate?.({
            content: [{ type: "text", text: final || `${role}: running` }],
            details: { role, turns, running: true },
          });
        }
      } catch {
        // Ignore non-JSON diagnostics from nested Pi processes.
      }
    }
  });
  const code = await new Promise((resolvePromise, reject) => {
    child.on("error", reject);
    child.on("close", (value) => resolvePromise(value ?? 1));
  });
  signal?.removeEventListener("abort", abort);
  if (signal?.aborted) throw new Error(`${role} cancelled`);
  if (code !== 0) throw new Error(stderr.trim() || `${role} exited ${code}`);
  const truncated = await truncateResult(final || "(agent returned no text)");
  return {
    content: [{ type: "text", text: truncated.text }],
    details: { ...truncated.details, role, turns, stderr: stderr.trim() || undefined },
  };
}

const sliceParameters = Type.Object({
  file: Type.String({ description: "Python file path, relative to the current project or absolute" }),
  symbols: Type.Array(Type.String(), { minItems: 1, description: "Target function or class names" }),
});

const repoParameters = Type.Object({
  repo: Type.Optional(Type.String({ description: "Repository root; defaults to the current directory" })),
  symptom: Type.String({ description: "Stack trace, error message, or description containing an implicated path" }),
  seeds: Type.Optional(Type.Array(Type.String())),
  budget: Type.Optional(Type.Integer({ minimum: 1, description: "Estimated token budget; automatic when omitted" })),
  importersDepth: Type.Optional(Type.Integer({ minimum: 0, maximum: 10 })),
  depsDepth: Type.Optional(Type.Integer({ minimum: 0, maximum: 10 })),
  json: Type.Optional(Type.Boolean()),
});

function registerAgent(pi, role, description) {
  pi.registerTool({
    name: role.replaceAll("-", "_"),
    label: role,
    description,
    parameters: Type.Object({ task: Type.String({ description: "Complete task and all required source context" }) }),
    async execute(_id, params, signal, onUpdate, ctx) {
      return runAgent(role, params.task, ctx, signal, onUpdate);
    },
  });
}

export default function contextKernel(pi) {
  const stats = { compressions: 0, before: 0, after: 0, canaryOk: 0, canaryFailed: 0 };
  const pending = new Map();

  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "bash" || process.env.CK_PRETOOL === "0") return;
    const command = event.input?.command;
    if (typeof command !== "string" || !command) return;
    const result = await bridge({ mode: "rewrite", command }, ctx.signal);
    if (!result.changed) return;
    const budget = contextBudget(ctx).budget;
    event.input.command = String(result.command).replace(/--budget\s+auto\b/g, `--budget ${budget}`);
  });

  pi.on("tool_result", async (event, ctx) => {
    const tool = String(event.toolName ?? "").toLowerCase();
    if (!DEFAULT_TOOLS.has(tool)) return;
    if (tool === "read" && AGENT_ROLES.has(process.env.CK_PI_AGENT_ROLE ?? "")) return;
    const session = ctx.sessionManager.getSessionId?.() ?? "pi-session";
    let changed = false;
    let before = 0;
    let after = 0;
    let footer;
    const content = [];
    for (const part of event.content ?? []) {
      if (part?.type !== "text" || typeof part.text !== "string") {
        content.push(part);
        continue;
      }
      const result = await bridge({
        mode: "compress",
        tool,
        text: part.text,
        input: event.input,
        session,
      }, ctx.signal);
      if (result.changed) {
        changed = true;
        before += Number(result.before ?? 0);
        after += Number(result.after ?? 0);
        footer = result.footer;
        content.push({ ...part, text: result.text });
      } else {
        content.push(part);
      }
    }
    if (!changed) return;
    stats.compressions += 1;
    stats.before += before;
    stats.after += after;
    pending.set(event.toolCallId, footer);
    pi.appendEntry("context-kernel-compression", { tool, before, after, footer });
    return { content };
  });

  pi.on("tool_execution_end", (event, ctx) => {
    const footer = pending.get(event.toolCallId);
    if (!footer) return;
    pending.delete(event.toolCallId);
    if (textFromContent(event.result?.content).includes(footer)) {
      stats.canaryOk += 1;
    } else {
      stats.canaryFailed += 1;
      ctx.ui.notify("context-kernel canary: Pi did not retain the projected tool result", "error");
    }
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.setStatus("context-kernel", "kernel: active");
  });

  pi.on("session_shutdown", (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.setStatus("context-kernel", undefined);
  });

  pi.registerTool({
    name: "kernel_slice",
    label: "Kernel Slice",
    description: "Extract the minimal Python def-use slice for target symbols. Use instead of reading a large Python file in full when only specific symbols matter.",
    promptSnippet: "Extract a task-relevant Python symbol slice",
    parameters: sliceParameters,
    async execute(_id, params, signal, _onUpdate, ctx) {
      const file = resolve(ctx.cwd, params.file.replace(/^@/, ""));
      const result = await runSlicer(SLICE, [file, ...params.symbols], ctx, signal, 20_000);
      return { content: [{ type: "text", text: result.text }], details: result.details };
    },
  });

  pi.registerTool({
    name: "kernel_repo_slice",
    label: "Kernel Repo Slice",
    description: "Project a repository onto the working set induced by a concrete bug symptom. Returns seeds, dependencies, nearby importers, tests, exclusions, and T2b symbol slices when needed.",
    promptSnippet: "Build a task-induced repository working set from a bug symptom",
    parameters: repoParameters,
    async execute(_id, params, signal, _onUpdate, ctx) {
      const repo = resolve(ctx.cwd, (params.repo ?? ".").replace(/^@/, ""));
      const auto = contextBudget(ctx);
      const args = [repo, "--symptom", params.symptom, "--budget", String(params.budget ?? auto.budget)];
      for (const seed of params.seeds ?? []) args.push("--seed", seed);
      if (params.importersDepth !== undefined) args.push("--importers-depth", String(params.importersDepth));
      if (params.depsDepth !== undefined) args.push("--deps-depth", String(params.depsDepth));
      if (params.json) args.push("--json");
      const result = await runSlicer(REPO_SLICE, args, ctx, signal, 90_000);
      return {
        content: [{ type: "text", text: result.text }],
        details: { ...result.details, budget: params.budget ?? auto.budget, context: auto },
      };
    },
  });

  registerAgent(pi, "kernel-scout", "Run the isolated, read-only T2 scout and return a sanity-checked repository slice manifest.");
  registerAgent(pi, "kernel-extractor", "Run the isolated, read-only T3 extractor and return at most ten source-cited task invariants.");
  registerAgent(pi, "kernel-verifier", "Run the isolated, adversarial T4 verifier for a fix/task charter or answer-invariance comparison.");

  pi.registerCommand("kernel-status", {
    description: "Show context-kernel savings and native canary status",
    handler: async (_args, ctx) => {
      const saved = stats.before - stats.after;
      const percent = stats.before ? Math.round((saved / stats.before) * 100) : 0;
      const usage = contextBudget(ctx);
      ctx.ui.notify(
        `context-kernel: ${stats.compressions} projections, ${saved} tokens saved (-${percent}%), canary ${stats.canaryOk} ok/${stats.canaryFailed} failed, budget ${usage.budget}`,
        stats.canaryFailed ? "warning" : "info",
      );
    },
  });
}

export const __test = { contextBudget, textFromContent };
