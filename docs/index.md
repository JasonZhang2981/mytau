---
title: Tau
description: An educational Python project for learning how coding agents are built.
hide:
  - navigation
  - toc
  - edit
---

<div class="tau-landing">
<div class="wrap">
  <nav>
    <div class="brand">
      <span class="glyph">&#964;</span>
      <span class="name">tau</span>
      <span class="ver">v0.1</span>
    </div>
    <div class="navlinks">
      <a href="getting-started/">Docs</a>
      <a href="architecture/">Lessons</a>
      <a href="https://github.com/alejandro-ao/tau/issues/1">Roadmap</a>
      <a class="gh" href="https://github.com/alejandro-ao/tau">GitHub &#8599;</a>
    </div>
  </nav>

  <header>
    <div class="hero-grid">
      <div>
        <p class="eyebrow">An educational coding-agent project</p>
        <h1>Learn how coding agents are <em>built.</em></h1>
        <p class="lede">
          <strong>Tau</strong> is a teaching project: a small Python coding agent
          designed to show, piece by piece, how agents stream model output,
          call tools, manage sessions, render events, and grow into a terminal UI.
        </p>
        <p class="lede small-lede">
          It is intentionally readable. The goal is not to hide the machinery;
          the goal is to make the machinery understandable.
        </p>
        <div class="cta-row">
          <span class="install">
            <span><span class="dollar">$</span> uv tool install git+https://github.com/alejandro-ao/tau.git</span>
            <button class="copy" id="copyBtn" type="button" aria-label="Copy install command">copy</button>
          </span>
          <a class="ghost" href="architecture/">Start with the architecture <span class="arr">&rarr;</span></a>
        </div>
      </div>

      <figure class="figure">
        <span class="figlabel">&#952; sweeps 0 &rarr; &#964;</span>
        <canvas id="tauCanvas" width="520" height="380" role="img"
          aria-label="A radius sweeping a unit circle through one full turn, tracing one period of a sine wave on notebook paper."></canvas>
        <span class="figval" id="thetaVal">&#952; = 0.00</span>
      </figure>
    </div>

    <div class="strip arch-strip">
      <div class="cellitem"><span class="num">learn</span><span class="cap">agent architecture</span></div>
      <div class="cellitem"><span class="num">read</span><span class="cap">small Python layers</span></div>
      <div class="cellitem"><span class="num">run</span><span class="cap">a real terminal agent</span></div>
    </div>
  </header>
</div>

<div class="wrap">
  <section id="start">
    <div class="sec-head">
      <span class="mark">01</span>
      <h2>A coding agent as a curriculum</h2>
    </div>
    <div class="layers">
      <div class="layer">
        <span class="idx">&#8544;</span>
        <span class="pkg">tau_ai</span>
        <h3>How models become streams</h3>
        <p>Start with provider adapters. Learn how model responses become provider-neutral events that the rest of the agent can consume.</p>
      </div>
      <div class="layer">
        <span class="idx">&#8545;</span>
        <span class="pkg">tau_agent</span>
        <h3>How the agent loop works</h3>
        <p>Study the reusable harness: messages, tools, transcript state, tool calls, cancellation, queued prompts, and session primitives.</p>
      </div>
      <div class="layer">
        <span class="idx">&#8546;</span>
        <span class="pkg">tau_coding</span>
        <h3>How it becomes useful</h3>
        <p>Add the coding environment: files, shell commands, durable sessions, skills, slash commands, renderers, and a Textual TUI.</p>
      </div>
    </div>
  </section>

  <section>
    <div class="two">
      <div>
        <p class="eyebrow">The lesson</p>
        <h2>Every moving part is visible.</h2>
        <p>Tau is built to answer practical questions: What is an agent loop? Where do tool calls come from? How does the transcript grow? What should the UI know? How do sessions survive after the process exits?</p>
      </div>
      <div class="event-flow" aria-label="Tau event flow">
        <div class="flow-node"><span>model stream</span><small>tokens, tool requests, thinking deltas</small></div>
        <div class="flow-arrow">&darr;</div>
        <div class="flow-node"><span>event stream</span><small>the contract between layers</small></div>
        <div class="flow-arrow">&darr;</div>
        <div class="flow-node"><span>agent loop</span><small>decide, call tools, update transcript</small></div>
        <div class="flow-arrow">&darr;</div>
        <div class="flow-split">
          <div class="flow-node"><span>session</span><small>inspectable JSONL history</small></div>
          <div class="flow-node"><span>frontend</span><small>print, Rich, or TUI</small></div>
        </div>
      </div>
    </div>
  </section>

  <section>
    <div class="two boundary-two">
      <div>
        <p class="eyebrow">The core idea</p>
        <h2>Separate the brain, the environment, and the face.</h2>
        <p>The most important lesson is the boundary. A reusable harness should not depend on a terminal UI, local file paths, Rich rendering, or app-specific resources. Those belong around the harness, not inside it.</p>
      </div>
      <div class="terminal" aria-hidden="true">
        <div class="bar"><span></span><span></span><span></span><span class="t">tau &mdash; design split</span></div>
        <pre><span class="key">AgentHarness</span> = reusable agent brain
<span class="key">AgentSession</span> = coding-agent environment
<span class="key">TUI</span>          = one possible frontend

<span class="out">dependency direction</span>
<span class="cmd">tau_coding</span> &rarr; <span class="cmd">tau_agent</span> &rarr; <span class="cmd">tau_ai</span></pre>
      </div>
    </div>
  </section>

  <section>
    <div class="sec-head">
      <span class="mark">02</span>
      <h2>What you can learn from Tau</h2>
    </div>
    <div class="capabilities">
      <div>Provider-neutral streaming interfaces</div>
      <div>Agent loops that request and execute tools</div>
      <div>Typed local tools for read, write, edit, and bash</div>
      <div>Durable sessions under <code>~/.tau/sessions</code></div>
      <div>Session resume, branching, JSONL export, and HTML export</div>
      <div>Project instructions, skills, and prompt templates</div>
      <div>Slash commands and model/provider selection</div>
      <div>Context accounting, compaction, and thinking controls</div>
      <div>How to keep Textual behind a UI adapter boundary</div>
    </div>
  </section>

  <section>
    <div class="sec-head">
      <span class="mark">03</span>
      <h2>Educational principles</h2>
    </div>
    <div class="principles">
      <div class="pr">
        <h3>Small layers beat magic</h3>
        <p>Each package has one job. You can study the provider layer, harness, and coding app independently.</p>
      </div>
      <div class="pr">
        <h3>Events make agents teachable</h3>
        <p>The agent emits a stream you can render, test, export, and reason about instead of hiding control flow in callbacks.</p>
      </div>
      <div class="pr">
        <h3>Real enough to matter</h3>
        <p>Tau is educational, but not a toy. You can run it as a terminal coding agent while reading the code that powers it.</p>
      </div>
      <div class="pr">
        <h3>Documentation follows implementation</h3>
        <p>The project is developed phase by phase, with notes explaining what was added, why it exists, and how it fits.</p>
      </div>
    </div>
  </section>

  <section>
    <div class="two">
      <div>
        <p class="eyebrow">The inspiration</p>
        <h2>Inspired by Pi, written as a Python learning path.</h2>
        <p>Tau borrows Pi's architectural lesson: keep the reusable agent harness separate from the coding-agent environment and from the UI. It is not a line-by-line port. It is an educational Python implementation of the same core ideas.</p>
      </div>
      <div class="terminal" aria-hidden="true">
        <div class="bar"><span></span><span></span><span></span><span class="t">tau &mdash; session</span></div>
        <pre><span class="pmt">&#964; &rsaquo;</span> <span class="cmd">explain the agent loop</span>

<span class="out">  stream   </span><span class="key">model events</span>
<span class="out">  request  </span><span class="key">tool call</span>
<span class="out">  execute  </span><span class="key">read / edit / bash</span>
<span class="out">  append   </span><span class="key">transcript entries</span>
<span class="out">  render   </span><span class="key">print mode or TUI</span></pre>
      </div>
    </div>
  </section>

  <section class="closing">
    <span class="turn">&#964;</span>
    <p>Use Tau as a map for building your own coding agent: start with events, add a loop, wrap it in a harness, then give it tools and a UI.</p>
    <div class="cta-row">
      <span class="install">
        <span><span class="dollar">$</span> uv tool install git+https://github.com/alejandro-ao/tau.git</span>
        <button class="copy" id="copyBtn2" type="button" aria-label="Copy install command">copy</button>
      </span>
      <a class="ghost" href="getting-started/">Get started <span class="arr">&rarr;</span></a>
      <a class="ghost" href="00-roadmap/">Follow the roadmap <span class="arr">&rarr;</span></a>
    </div>
  </section>

  <footer>
    <div class="brand">
      <span class="glyph" style="font-size:20px;">&#964;</span>
      <span class="name">tau</span>
    </div>
    <div class="l">
      <a href="getting-started/">Docs</a>
      <a href="architecture/">Architecture</a>
      <a href="https://github.com/alejandro-ao/tau">GitHub</a>
      <a href="https://github.com/alejandro-ao/tau/issues/1">Roadmap</a>
    </div>
    <span>An educational project &middot; inspired by Pi</span>
  </footer>
</div>
</div>
