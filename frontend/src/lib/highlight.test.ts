import { describe, expect, it } from "vitest";
import { buildTree, highlightLines, tokenizePython } from "./highlight";

const kinds = (source: string) =>
  tokenizePython(source)
    .filter((t) => t.text.trim())
    .map((t) => [t.text.trim(), t.kind]); // plain tokens keep their spaces and newlines

describe("tokenizePython", () => {
  it("recognises the parts of a FastAPI route", () => {
    expect(kinds('@app.get("/items/{id}")\ndef read(id: int) -> Item:  # one\n    return 42')).toEqual([
      ["@app.get", "decorator"],
      ["(", "plain"],
      ['"/items/{id}"', "string"],
      [")", "plain"],
      ["def", "keyword"],
      ["read", "function"],
      ["(", "plain"],
      ["id", "plain"],
      [":", "plain"],
      ["int", "builtin"],
      [") ->", "plain"],
      ["Item", "plain"],
      [":", "plain"],
      ["# one", "comment"],
      ["return", "keyword"],
      ["42", "number"],
    ]);
  });

  it("names classes and keeps keywords inside strings as strings", () => {
    expect(kinds('class Todo(BaseModel):\n    title: str = "if not"')).toEqual([
      ["class", "keyword"],
      ["Todo", "class"],
      ["(", "plain"],
      ["BaseModel", "builtin"],
      ["):", "plain"],
      ["title", "plain"],
      [":", "plain"],
      ["str", "builtin"],
      ["=", "plain"],
      ['"if not"', "string"],
    ]);
  });

  it("loses no characters", () => {
    const source = 'x = f"{a}"\n"""doc\nstring"""\n# end';
    expect(tokenizePython(source).map((t) => t.text).join("")).toBe(source);
  });
});

describe("highlightLines", () => {
  it("splits a multi-line string over its lines", () => {
    const lines = highlightLines("a.py", '"""one\ntwo"""\nx = 1');
    expect(lines).toHaveLength(3);
    expect(lines[0]?.[0]).toEqual({ text: '"""one', kind: "string" });
    expect(lines[1]?.[0]).toEqual({ text: 'two"""', kind: "string" });
  });

  it("highlights only comments in text files", () => {
    const lines = highlightLines("requirements.txt", "fastapi\n# test tools\npytest");
    expect(lines.map((l) => l.map((t) => t.kind))).toEqual([["plain"], ["comment"], ["plain"]]);
  });
});

describe("buildTree", () => {
  it("nests files in folders, folders first", () => {
    const tree = buildTree(["requirements.txt", "app/main.py", "app/routers/todos.py", "tests/test_a.py"]);
    expect(tree.map((n) => n.name)).toEqual(["app", "tests", "requirements.txt"]);
    expect(tree[0]?.children.map((n) => n.name)).toEqual(["routers", "main.py"]);
    expect(tree[0]?.children[0]?.children[0]?.path).toBe("app/routers/todos.py");
  });
});
