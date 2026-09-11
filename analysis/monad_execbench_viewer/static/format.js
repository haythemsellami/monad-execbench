// Formatting rules for exported values. Counters and integers past 2^53-1
// arrive as decimal strings and stay strings: BigInt is used only to compare.

const GROUP = /\B(?=(\d{3})+(?!\d))/g;
const INTEGER_STRING = /^(?:0|[1-9][0-9]*)$/;

export const isUnavailable = (value) => value === null || value === undefined;

export const isIntegerString = (value) =>
  typeof value === "string" && INTEGER_STRING.test(value);

export function toBigInt(value) {
  if (typeof value === "bigint") return value;
  // The exporter already turns anything past 2^53-1 into a decimal string,
  // so an integer Number is exact; convert it rather than dropping it.
  if (typeof value === "number" && Number.isInteger(value)) return BigInt(value);
  if (isIntegerString(value)) return BigInt(value);
  return null;
}

export function compareBig(left, right) {
  const a = toBigInt(left);
  const b = toBigInt(right);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a < b ? -1 : a > b ? 1 : 0;
}

export function compareNumber(left, right) {
  const a = isUnavailable(left) ? null : Number(left);
  const b = isUnavailable(right) ? null : Number(right);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a < b ? -1 : a > b ? 1 : 0;
}

export function compareText(left, right) {
  return String(left ?? "").localeCompare(String(right ?? ""), "en");
}

function groupDigits(text) {
  const [whole, fraction] = text.split(".");
  const grouped = whole.replace(GROUP, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

/** Exact grouped integer for numbers, decimal strings or BigInt. */
export function formatInt(value) {
  if (isUnavailable(value)) return null;
  const big = toBigInt(value);
  return big === null ? String(value) : groupDigits(big.toString());
}

/** Fixed decimals that never round a tiny nonzero value to zero. */
export function formatDecimal(value, decimals) {
  if (isUnavailable(value)) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  const fixed = number.toFixed(decimals);
  if (Number(fixed) === 0 && number !== 0) return number.toPrecision(2);
  return groupDigits(fixed);
}

/** Microseconds: <10 → 2dp, <100 → 1dp, else grouped integer. Always labelled. */
export function formatUs(value) {
  if (isUnavailable(value)) return null;
  const number = Number(value);
  const magnitude = Math.abs(number);
  let text;
  if (magnitude < 10) text = formatDecimal(number, 2);
  else if (magnitude < 100) text = formatDecimal(number, 1);
  else text = formatInt(Math.round(number));
  return `${text} µs`;
}

/** Fraction → percentage with two decimals. */
export function formatPct(fraction) {
  if (isUnavailable(fraction)) return null;
  return `${formatDecimal(Number(fraction) * 100, 2)}%`;
}

export function formatRatio(ratio) {
  if (isUnavailable(ratio)) return null;
  return `${formatDecimal(ratio, 2)}×`;
}

export function formatChange(ratio) {
  if (isUnavailable(ratio)) return null;
  const change = (Number(ratio) - 1) * 100;
  const text = formatDecimal(change, 2);
  return change > 0 && !text.startsWith("-") ? `+${text}%` : `${text}%`;
}

/** Share of a BigInt-compatible part over a total, as a percentage number. */
export function share(part, total) {
  const a = toBigInt(part);
  const b = toBigInt(total);
  if (a === null || b === null || b === 0n) return 0;
  return Number((a * 100000n) / b) / 1000;
}

export function bigSum(values) {
  let total = 0n;
  for (const value of values) {
    const big = toBigInt(value);
    if (big !== null) total += big;
  }
  return total;
}

export function truncateMiddle(text, head = 18, tail = 8) {
  const value = String(text);
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function plural(count, singular, pluralForm = `${singular}s`) {
  return `${formatInt(count)} ${Number(count) === 1 ? singular : pluralForm}`;
}

const OPCODES = {
  0x00: "STOP",
  0x01: "ADD",
  0x02: "MUL",
  0x03: "SUB",
  0x04: "DIV",
  0x05: "SDIV",
  0x06: "MOD",
  0x07: "SMOD",
  0x08: "ADDMOD",
  0x09: "MULMOD",
  0x0a: "EXP",
  0x0b: "SIGNEXTEND",
  0x10: "LT",
  0x11: "GT",
  0x12: "SLT",
  0x13: "SGT",
  0x14: "EQ",
  0x15: "ISZERO",
  0x16: "AND",
  0x17: "OR",
  0x18: "XOR",
  0x19: "NOT",
  0x1a: "BYTE",
  0x1b: "SHL",
  0x1c: "SHR",
  0x1d: "SAR",
  0x20: "KECCAK256",
  0x30: "ADDRESS",
  0x31: "BALANCE",
  0x32: "ORIGIN",
  0x33: "CALLER",
  0x34: "CALLVALUE",
  0x35: "CALLDATALOAD",
  0x36: "CALLDATASIZE",
  0x37: "CALLDATACOPY",
  0x38: "CODESIZE",
  0x39: "CODECOPY",
  0x3a: "GASPRICE",
  0x3b: "EXTCODESIZE",
  0x3c: "EXTCODECOPY",
  0x3d: "RETURNDATASIZE",
  0x3e: "RETURNDATACOPY",
  0x3f: "EXTCODEHASH",
  0x40: "BLOCKHASH",
  0x41: "COINBASE",
  0x42: "TIMESTAMP",
  0x43: "NUMBER",
  0x44: "PREVRANDAO",
  0x45: "GASLIMIT",
  0x46: "CHAINID",
  0x47: "SELFBALANCE",
  0x48: "BASEFEE",
  0x49: "BLOBHASH",
  0x4a: "BLOBBASEFEE",
  0x50: "POP",
  0x51: "MLOAD",
  0x52: "MSTORE",
  0x53: "MSTORE8",
  0x54: "SLOAD",
  0x55: "SSTORE",
  0x56: "JUMP",
  0x57: "JUMPI",
  0x58: "PC",
  0x59: "MSIZE",
  0x5a: "GAS",
  0x5b: "JUMPDEST",
  0x5c: "TLOAD",
  0x5d: "TSTORE",
  0x5e: "MCOPY",
  0x5f: "PUSH0",
  0xf0: "CREATE",
  0xf1: "CALL",
  0xf2: "CALLCODE",
  0xf3: "RETURN",
  0xf4: "DELEGATECALL",
  0xf5: "CREATE2",
  0xfa: "STATICCALL",
  0xfd: "REVERT",
  0xfe: "INVALID",
  0xff: "SELFDESTRUCT",
};

export function opcodeName(code) {
  const byte = Number(code);
  if (!Number.isInteger(byte) || byte < 0 || byte > 255) return "OP";
  if (OPCODES[byte]) return OPCODES[byte];
  if (byte >= 0x60 && byte <= 0x7f) return `PUSH${byte - 0x5f}`;
  if (byte >= 0x80 && byte <= 0x8f) return `DUP${byte - 0x7f}`;
  if (byte >= 0x90 && byte <= 0x9f) return `SWAP${byte - 0x8f}`;
  if (byte >= 0xa0 && byte <= 0xa4) return `LOG${byte - 0xa0}`;
  return "UNASSIGNED";
}

export function opcodeHex(code) {
  const byte = Number(code);
  if (!Number.isInteger(byte) || byte < 0 || byte > 255) return "0x??";
  return `0x${byte.toString(16).padStart(2, "0")}`;
}
