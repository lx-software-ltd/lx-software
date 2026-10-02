/** TanStack Query keys for the admin SPA. Prefixes stay stable so invalidation matches. */
export const keys = {
  board: {
    all: ["board"] as const,
    tasks: () => ["board", "tasks"] as const,
  },
  finance: ["finance"] as const,
  book: (bookKey: string) => [bookKey] as const,
  banking: ["banking"] as const,
  frankfurter: ["frankfurter"] as const,
  admin: ["admin"] as const,
};

export const BOARD_QUERY_KEY = keys.board.all;
export const BOARD_TASKS_KEY = keys.board.tasks();
