/**
 * Convert JSON keys at the HTTP boundary.
 *
 * This file is byte-identical in findingalpha and lx-software. Do not edit one copy.
 * Handlers and TypeScript stay camelCase. Only keys are converted.
 */

export type WireContract = {
  readonly renames: Readonly<Record<string, string>>;
  readonly verbatimKeys: readonly string[];
  readonly mapFields: Readonly<Record<string, number>>;
  readonly opaqueFields: readonly string[];
  readonly rootMaps: Readonly<Record<string, number>>;
  readonly excludedRoutes: readonly string[];
};

const CAMEL = /^[a-z][a-zA-Z0-9]*$/;
const SNAKE = /^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)+$/;

export function excluded(path: string, contract: WireContract): boolean {
  const bare = path.split("?")[0] ?? path;
  return contract.excludedRoutes.some((prefix) => bare === prefix || bare.startsWith(prefix));
}

export function toWire(value: unknown, contract: WireContract, route = ""): unknown {
  return walk(value, contract, false, rootLevels(contract, route));
}

export function fromWire(value: unknown, contract: WireContract, route = ""): unknown {
  return walk(value, contract, true, rootLevels(contract, route));
}

function rootLevels(contract: WireContract, route: string): number {
  return contract.rootMaps[route] ?? 0;
}

function walk(value: unknown, contract: WireContract, inbound: boolean, dataLevels: number): unknown {
  if (dataLevels > 0) {
    if (isRecord(value)) {
      return mapRecord(value, (key, child) => [key, walk(child, contract, inbound, dataLevels - 1)]);
    }
    if (Array.isArray(value)) {
      return value.map((child) => walk(child, contract, inbound, dataLevels));
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((child) => walk(child, contract, inbound, 0));
  }
  if (!isRecord(value)) {
    return value;
  }
  const opaque = new Set(contract.opaqueFields);
  return mapRecord(value, (key, child) => {
    const verbatim = contract.verbatimKeys.includes(key);
    const internal = verbatim ? key : inbound ? keyFromWire(key, contract) : key;
    const renamed = verbatim ? key : inbound ? internal : keyToWire(key, contract);
    if (opaque.has(internal) || opaque.has(key)) {
      return [renamed, child];
    }
    const levels = contract.mapFields[internal] ?? 0;
    return [renamed, walk(child, contract, inbound, levels)];
  });
}

function keyToWire(key: string, contract: WireContract): string {
  if (contract.verbatimKeys.includes(key)) {
    return key;
  }
  const renamed = contract.renames[key];
  if (renamed !== undefined) {
    return renamed;
  }
  if (isCamel(key)) {
    return [...key].map((char) => (char >= "A" && char <= "Z" ? `_${char.toLowerCase()}` : char)).join("");
  }
  return key;
}

function keyFromWire(key: string, contract: WireContract): string {
  if (contract.verbatimKeys.includes(key)) {
    return key;
  }
  for (const [internal, wire] of Object.entries(contract.renames)) {
    if (wire === key) {
      return internal;
    }
  }
  if (SNAKE.test(key)) {
    let out = "";
    for (let index = 0; index < key.length; index += 1) {
      if (key[index] === "_" && index + 1 < key.length) {
        out += key[index + 1].toUpperCase();
        index += 1;
      } else {
        out += key[index];
      }
    }
    return out;
  }
  return key;
}

function isCamel(key: string): boolean {
  return CAMEL.test(key) && [...key].some((char) => char >= "A" && char <= "Z");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mapRecord(
  value: Record<string, unknown>,
  convert: (key: string, child: unknown) => readonly [string, unknown],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    const [renamed, next] = convert(key, child);
    out[renamed] = next;
  }
  return out;
}
