import { Icon } from "./icons";

/** What a run turns one sentence into: the generated project (a real run's file tree and
 * a line of its code) and its result. Static: it describes the system, not a live run. */
export function InputOutput() {
  return (
    <section className="explain io" aria-label="What you type and what you get">
      <div className="explain-label">You type</div>
      <p className="io-input">
        <span className="io-prompt">❯</span> Build a notes API with create, list and delete
      </p>
      <div className="io-arrow" aria-hidden="true">
        <span />
        about 2 minutes later
        <span />
      </div>
      <div className="explain-label">You get</div>
      <div className="io-output">
        <ul className="io-tree" aria-label="Generated files">
          <li>
            <Icon name="folder" width={13} height={13} /> app
          </li>
          <li className="nested">main.py</li>
          <li className="nested">models.py</li>
          <li>
            <Icon name="folder" width={13} height={13} /> tests
          </li>
          <li className="nested">test_notes.py</li>
          <li>requirements.txt</li>
        </ul>
        <div className="io-code-wrap">
          <pre className="io-code" aria-label="Part of app/main.py">
            <code>
              <span className="tok-decorator">@app.post</span>(
              <span className="tok-string">"/notes"</span>, status_code=
              <span className="tok-number">201</span>)
              {"\n"}
              <span className="tok-keyword">def</span>{" "}
              <span className="tok-function">create_note</span>(note: NoteCreate):
              {"\n    "}
              <span className="tok-keyword">return</span> store.
              <span className="tok-function">add</span>(note)
            </code>
          </pre>
          <p className="io-result">
            <Icon name="check" width={12} height={12} /> 8/8 tests passed · committed
          </p>
        </div>
      </div>
    </section>
  );
}

/** How the parts connect. Agents only read; workflow code writes, tests and commits. */
export function Architecture() {
  return (
    <figure className="explain arch" aria-label="Architecture">
      <div className="explain-label">Under the hood</div>
      <div className="arch-row arch-top">
        <div className="arch-box">
          <b>Browser</b>
          <span>React dashboard</span>
        </div>
        <div className="arch-link" aria-label="connected by Server-Sent Events">
          <span>⇄</span>
          <small>SSE</small>
        </div>
        <div className="arch-box">
          <b>FastAPI</b>
          <span>runs · SQLite</span>
        </div>
      </div>
      <div className="arch-down" aria-hidden="true" />
      <div className="arch-box arch-core">
        <b>LangGraph workflow</b>
        <span className="arch-agents" aria-label="agents: Planner, Developer, Reviewer, Tester">
          <i style={{ ["--agent" as string]: "var(--planner)" }}>P</i>
          <i style={{ ["--agent" as string]: "var(--developer)" }}>D</i>
          <i style={{ ["--agent" as string]: "var(--reviewer)" }}>R</i>
          <i style={{ ["--agent" as string]: "var(--tester)" }}>T</i>
          <span>→ Groq LLM</span>
        </span>
      </div>
      <div className="arch-down arch-split" aria-hidden="true" />
      <div className="arch-row arch-tools">
        <div className="arch-box">
          <b>Filesystem</b>
          <span>MCP server</span>
        </div>
        <div className="arch-box">
          <b>Git</b>
          <span>MCP server</span>
        </div>
        <div className="arch-box arch-sandbox">
          <b>E2B</b>
          <span>sandbox · no internet</span>
        </div>
      </div>
      <figcaption>Agents only read. Workflow code writes, tests and commits, and you approve the risky steps.</figcaption>
    </figure>
  );
}
