# Commenting standard

Every file in this repository that a person might read is commented the way a careful engineer comments for a
colleague: enough to understand *why* the code is the way it is, never a narration of *what* it already says.
The rules below are distilled from PEP 8, PEP 257, the Google Python Style Guide (§3.8), Google's code-review
guide, and Ellen Spertus's "Best practices for writing code comments" (Stack Overflow, 2021). They apply to
Python, shell, YAML, SQL, JSON-with-comments-in-docs, and GitHub workflow files alike.

## The ten rules

1. **Explain why, not what.** A comment that restates the next line (`i += 1  # add one to i`) has negative
   value: it clutters, it goes stale, and it trains readers to skip comments. Assume the reader knows the
   language better than you do (Google §3.8). Comment the decision, the constraint, the surprise.
2. **A comment never excuses unclear code.** If a name needs a comment to make sense, rename it. If a block
   needs a paragraph to be followed, split it. Kernighan's law: debugging is twice as hard as writing, so
   code you had to explain at length is code you cannot debug.
3. **Comment the tricky parts before they start.** A short block comment above a non-obvious section says what
   approach is taken and why the obvious approach was rejected (Google: "comment tricky parts of the code
   before the operation"). End-of-line comments are for single non-obvious facts: `if i & (i - 1) == 0:  # 0 or a power of two`.
4. **Explain unidiomatic code.** Every workaround, every `noqa`, every odd-looking guard carries the reason and,
   where one exists, a link to the bug or the documentation that forces it. Readers should never wonder
   "was this a mistake?".
5. **Link the source** of any copied or adapted snippet, and link the external reference (RFC, vendor doc,
   spec section) at the point where it answers the reader's question. In this repository that usually means
   the `SPEC_AMENDMENTS.md` section (`AM-31`), the requirement ID (`R086`), or the review round that caused
   the change (`docs/reviews/plan-review-r8-…`).
6. **Record bug fixes and measured facts.** When a line exists because something broke, say what broke and
   how to see it again ("Keycloak 26.8 answers the password grant for a deleted user with 400, measured
   2026-10-08"). A future reader can then tell whether the line is still needed.
7. **Mark incomplete work explicitly** with `TODO(<task id>): …` naming the task that finishes it; never leave
   an unlabeled stub. A stub that silently looks finished is a lie to the next reader.
8. **Dispel confusion, don't create it.** No in-jokes, no abbreviations the next reader cannot expand, no
   comments that contradict the code. When the code changes, the comment changes in the same edit.
9. **Docstrings for every public module, class and function** (PEP 257 / Google §3.8): a one-line summary
   that ends with a period, then — when the signature does not say it all — a blank line and *Args*,
   *Returns*, *Raises*. A docstring must let the reader call the function without reading its body. Test
   modules need a module docstring that says what the tests protect; individual test functions are named
   so well that they need none, unless the setup is subtle.
10. **Write prose.** Comments are sentences: capitalised, punctuated, spelled correctly, in the same register
    as the surrounding code. Keep inline comments at least two spaces from the code (`PEP 8`), and never let a
    comment push a line past the formatter's limit — move it above the line instead.

## What this looks like here

- **Module docstring** — what the file is for, who calls it, and the spec section it serves. For scripts, the
  usage lines. Example (`scripts/bootstrap_dev.py`): purpose, the four sub-commands, where secrets live, and
  the sentence "Nothing here prints a secret."
- **Function docstring** — one line, imperative or descriptive but consistent within a file; *Returns*/*Raises*
  only when they add information the annotations do not.
- **Block comment** — above a non-obvious decision: why the entrypoint re-exports secrets as `OPS_KC_*`
  rather than `KC_*`, why the healthcheck reads the status line instead of grepping the body.
- **Inline comment** — one fact: `assert status in (400, 401), status  # 400 invalid_grant on Keycloak 26.8 (measured)`.
- **YAML / shell / SQL** — the same rules with `#`/`--`: a header comment stating the file's role and the
  constraint it enforces ("every published port binds to 127.0.0.1"), block comments above surprising lines.
- **Tests** — the module docstring names the behaviour under protection and the failure it would catch; a
  comment on a non-obvious assertion says which real-world mistake it detects (`# mcp-read never gets
  incident-sim, and vice versa`).

## What not to write

- `# import json` above `import json`; `# loop over users` above `for user in users:`.
- Commented-out code. Delete it; git remembers.
- A comment that explains a bad name instead of fixing it.
- "Should work", "probably", "hack" without the reason and the exit condition.
- Changelogs inside files. History lives in git and in `docs/PROJECT_HISTORY.md`.

## Review checklist (applied by every task and final review)

- [ ] Every new module, class and public function has a docstring that says why it exists.
- [ ] Every workaround, `noqa`, guard and magic value has a reason beside it.
- [ ] No comment restates its code; no comment contradicts its code.
- [ ] Every `TODO` names the task that resolves it.
- [ ] Comments are complete sentences a new colleague could read without the author.
