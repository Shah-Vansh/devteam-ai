/**
 * A small syntax highlighter for the code viewer. It only needs to make generated FastAPI
 * code readable, so it knows Python's keywords, strings (also triple-quoted ones spanning
 * lines), comments, decorators, numbers and well-known names, plus simple text files.
 * React escapes every token, so file contents can never inject markup.
 */

export type TokenKind =
  | "keyword"
  | "builtin"
  | "string"
  | "comment"
  | "decorator"
  | "number"
  | "function"
  | "class"
  | "plain";

export interface Token {
  text: string;
  kind: TokenKind;
}

const KEYWORDS = new Set(
  (
    "False None True and as assert async await break class continue def del elif else " +
    "except finally for from global if import in is lambda nonlocal not or pass raise " +
    "return try while with yield match case"
  ).split(" "),
);

const BUILTINS = new Set(
  (
    "self cls print len range list dict set tuple str int float bool bytes type isinstance " +
    "enumerate zip sorted min max sum any all open super property staticmethod classmethod " +
    "Exception ValueError KeyError TypeError HTTPException FastAPI APIRouter BaseModel Field " +
    "Depends status Optional List Dict"
  ).split(" "),
);

const PYTHON = new RegExp(
  [
    String.raw`(?<string>[rbfuRBFU]{0,2}(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?))`,
    String.raw`(?<comment>#[^\n]*)`,
    String.raw`(?<decorator>@[\w.]+)`,
    String.raw`(?<number>\b\d[\d_]*(?:\.\d+)?\b)`,
    String.raw`(?<word>[A-Za-z_]\w*)`,
  ].join("|"),
  "g",
);

export function tokenizePython(source: string): Token[] {
  const tokens: Token[] = [];
  let last = 0;
  let previousWord = "";
  for (const match of source.matchAll(PYTHON)) {
    const start = match.index ?? 0;
    if (start > last) tokens.push({ text: source.slice(last, start), kind: "plain" });
    const groups = match.groups ?? {};
    const text = match[0];
    let kind: TokenKind = "plain";
    if (groups.string !== undefined) kind = "string";
    else if (groups.comment !== undefined) kind = "comment";
    else if (groups.decorator !== undefined) kind = "decorator";
    else if (groups.number !== undefined) kind = "number";
    else if (groups.word !== undefined) {
      if (previousWord === "def") kind = "function";
      else if (previousWord === "class") kind = "class";
      else if (KEYWORDS.has(text)) kind = "keyword";
      else if (BUILTINS.has(text)) kind = "builtin";
      previousWord = text;
    }
    tokens.push({ text, kind });
    last = start + text.length;
  }
  if (last < source.length) tokens.push({ text: source.slice(last), kind: "plain" });
  return tokens;
}

function tokenizeText(source: string): Token[] {
  // requirements.txt, markdown, config: comments stand out, the rest stays plain.
  return source.split(/(#[^\n]*)/).filter(Boolean).map((text) => ({
    text,
    kind: text.startsWith("#") ? "comment" : "plain",
  }));
}

/** Tokens grouped by line, ready to render with line numbers. */
export function highlightLines(path: string, source: string): Token[][] {
  const tokens = path.endsWith(".py") ? tokenizePython(source) : tokenizeText(source);
  const lines: Token[][] = [[]];
  for (const token of tokens) {
    const parts = token.text.split("\n");
    parts.forEach((part, i) => {
      if (i > 0) lines.push([]);
      if (part) lines[lines.length - 1]!.push({ text: part, kind: token.kind });
    });
  }
  return lines;
}

/** Files as a folder tree for the explorer. */
export interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  isFile: boolean;
}

export function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", children: [], isFile: false };
  for (const path of [...paths].sort()) {
    let node = root;
    const parts = path.split("/");
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      const childPath = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === part && c.isFile === isFile);
      if (!child) {
        child = { name: part, path: childPath, children: [], isFile };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .sort((a, b) => Number(a.isFile) - Number(b.isFile) || a.name.localeCompare(b.name))
      .map((n) => ({ ...n, children: sort(n.children) }));
  return sort(root.children);
}
