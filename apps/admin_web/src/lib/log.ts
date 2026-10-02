function emit(level: "info" | "error", args: readonly unknown[]): void {
  if (!import.meta.env.DEV) return;
  if (level === "info") console.info(...args);
  else console.error(...args);
}

/** Development-only diagnostics. Production builds drop the calls. */
export const log = {
  info: (...args: readonly unknown[]): void => emit("info", args),
  error: (...args: readonly unknown[]): void => emit("error", args),
};
