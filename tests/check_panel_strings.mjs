// Panel i18n static regression (F-333/F-340 panel face, lightest honest
// option — the repo has no jsdom/Playwright dependency, so DOM interaction
// regression stays out of scope here; see the R2 report finding 6).
//
// Checks, all structural (no behavior simulation):
//   1. no duplicate keys inside either LANG segment (F-337 regression:
//      ES object literals silently take the last duplicate)
//   2. zh-Hans / en key sets are identical (R2 scan criterion)
//   3. no CJK characters inside string literals OUTSIDE the LANG
//      dictionary (F-338 regression: hardcoded client copy leaks into the
//      en UI; comments are ignored)
//
// Usage: node tests/check_panel_strings.mjs   (exit 0 = pass, 1 = fail)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(
  ROOT,
  "custom_components",
  "sensor_switch_controller",
  "static",
  "panel.js",
);
const text = readFileSync(SRC, "utf-8");
const lines = text.split("\n");

// ---------------------------------------------------------------- LANG
const iStart = lines.findIndex((l) => l.startsWith("const LANG = {"));
if (iStart < 0) throw new Error("LANG dictionary not found");
const iZh = lines.findIndex((l) => l.trim() === '"zh-Hans": {');
const iEn = lines.findIndex((l) => l.trim() === "en: {");
// first top-level `};` closing LANG (2-space indent `};` at column 0)
const iEnd = lines.findIndex((l, i) => i > iStart && l === "};");
if (!(iStart < iZh && iZh < iEn && iEn < iEnd)) {
  throw new Error(`LANG segment boundaries moved: ${iStart}/${iZh}/${iEn}/${iEnd}`);
}

const KEY_RE = /^\s{4}([A-Za-z_][A-Za-z0-9_]*):/;

function collectKeys(from, to, label, dupes) {
  const seen = new Map();
  const keys = [];
  for (let i = from; i < to; i++) {
    const m = lines[i].match(KEY_RE);
    if (!m) continue;
    const key = m[1];
    keys.push(key);
    if (seen.has(key)) dupes.push(`${label}:${i + 1} duplicate key "${key}" (first at ${seen.get(key) + 1})`);
    else seen.set(key, i);
  }
  return new Set(keys);
}

const dupes = [];
const zhKeys = collectKeys(iZh + 1, iEn, "zh", dupes);
const enKeys = collectKeys(iEn + 1, iEnd, "en", dupes);

const errors = [...dupes];

const zhOnly = [...zhKeys].filter((k) => !enKeys.has(k));
const enOnly = [...enKeys].filter((k) => !zhKeys.has(k));
if (zhOnly.length) errors.push(`keys missing in en: ${zhOnly.join(", ")}`);
if (enOnly.length) errors.push(`keys missing in zh-Hans: ${enOnly.join(", ")}`);

// --------------------------------------------- CJK outside the LANG dict
// Minimal scanner: skips // and /* */ comments, walks ' " ` strings and
// template literals (with ${expr} nesting), collects CJK-bearing literals.
function scanCjk(src) {
  const hits = [];
  let i = 0;
  const n = src.length;
  const isCjk = (c) => /[\u3400-\u9fff\uf900-\ufaff]/.test(c);
  const lineOf = (idx) => src.slice(0, idx).split("\n").length;
  while (i < n) {
    const c = src[i];
    const nx = src[i + 1];
    if (c === "/" && nx === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (c === "/" && nx === "*") {
      i += 2;
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
      i += 2;
      continue;
    }
    // regex literal (e.g. esc's /[&<>"']/g): its quotes must not open a
    // string scan. Heuristic: a "/" whose previous non-whitespace char
    // cannot end an expression is a regex start, not division.
    if (c === "/" && nx !== "/" && nx !== "*" && isRegexStart(src, i)) {
      i = skipRegex(src, i);
      continue;
    }
    if (c === "'" || c === '"' || c === "`") {
      const quote = c;
      const start = i;
      i++;
      let body = "";
      let sawCjk = false;
      while (i < n) {
        const ch = src[i];
        if (ch === "\\") {
          body += src.slice(i, i + 2);
          i += 2;
          continue;
        }
        if (quote === "`" && ch === "$" && src[i + 1] === "{") {
          // template expression: code, not copy — skip it whole (comments
          // and nested strings inside are NOT checked; a hardcoded CJK
          // string inside ${expr} would be missed, which is acceptable:
          // display copy lives in the literal text segments)
          i = skipTemplateExpr(src, i + 2);
          continue;
        }
        if (isCjk(ch)) sawCjk = true;
        body += ch;
        i++;
        if (ch === quote) break;
      }
      if (sawCjk) hits.push({ line: lineOf(start), literal: body.slice(0, 80) });
      continue;
    }
    i++;
  }
  return hits;
}

// A "/" starts a regex literal when the previous non-whitespace char
// cannot terminate an expression (identifier, number, ")", "]", quote...).
function isRegexStart(src, i) {
  let j = i - 1;
  while (j >= 0 && /\s/.test(src[j])) j--;
  if (j < 0) return true;
  const c = src[j];
  if (/[A-Za-z0-9_$)\]}"'`]/.test(c)) return false;
  // keyword ends (return, typeof, case...) also allow a regex; the chars
  // above cover the identifier/paren cases — a preceding word char is the
  // common divider case, everything else ( ( , = : [ ! & | ? { } ; + - *
  // % < > ^ ~ ) is a regex context
  return true;
}

// Skip a regex literal starting AT the "/" — handles escapes and character
// classes ([...] may contain an unescaped "/").
function skipRegex(src, i) {
  i++;
  let inClass = false;
  while (i < src.length) {
    const ch = src[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === "[") inClass = true;
    else if (ch === "]") inClass = false;
    else if (ch === "/" && !inClass) return i + 1;
    i++;
  }
  return i;
}

// Skip a ${...} template expression starting AT the char after "${".
// Tracks brace depth, strings and nested templates inside so the closing
// brace is matched correctly. Returns the index just past the "}".
function skipTemplateExpr(src, i) {
  let depth = 1;
  const n = src.length;
  while (i < n && depth > 0) {
    const ch = src[i];
    const nx = src[i + 1];
    if (ch === "/" && nx === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (ch === "/" && nx === "*") {
      i += 2;
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
      i += 2;
      continue;
    }
    if (ch === "'" || ch === '"') {
      const quote = ch;
      i++;
      while (i < n) {
        if (src[i] === "\\") {
          i += 2;
          continue;
        }
        if (src[i] === quote) {
          i++;
          break;
        }
        i++;
      }
      continue;
    }
    if (ch === "/" && src[i + 1] !== "/" && src[i + 1] !== "*" && isRegexStart(src, i)) {
      i = skipRegex(src, i);
      continue;
    }
    if (ch === "`") {
      // nested template literal — recurse on its text/expressions
      i++;
      while (i < n) {
        if (src[i] === "\\") {
          i += 2;
          continue;
        }
        if (src[i] === "$" && src[i + 1] === "{") {
          i = skipTemplateExpr(src, i + 2);
          continue;
        }
        if (src[i] === "`") {
          i++;
          break;
        }
        i++;
      }
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i + 1;
    }
    i++;
  }
  return i;
}

const before = lines.slice(0, iStart).join("\n");
const after = lines.slice(iEnd + 1).join("\n");
for (const [seg, src] of [["pre-LANG", before], ["post-LANG", after]]) {
  for (const hit of scanCjk(src)) {
    errors.push(
      `${seg} line ${hit.line}: CJK inside a string literal (${hit.literal}) — move it into LANG via tr() (F-338)`,
    );
  }
}

if (errors.length) {
  console.error(`panel strings check FAILED (${errors.length}):`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log(
  `panel strings OK: zh=${zhKeys.size} keys, en=${enKeys.size} keys, sets equal, no dupes, no CJK outside LANG`,
);
