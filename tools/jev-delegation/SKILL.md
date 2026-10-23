---
name: jev-delegation
description: Classify every submitted input with Jev, dispatch simple work to an independent Luna codex exec, and return uncertain or failed work to the current session.
---

# Jev input dispatch

Every text input is classified once before execution, including greetings and complex
questions. The `UserPromptSubmit` hook asks Jev two questions: `simple_request` (is the request clear, bounded, and suitable for a lightweight model?)
and `coding_task` (does it need code, files, or tools?). It selects independent Luna when
`simple_request >= .8` and (`coding_task <= .2` or `coding_task >= .8`); otherwise it
selects `current`. Invalid or unavailable Jev results conservatively select current.
The hook requires manual trust confirmation in `/hooks` and does not force the host to
invoke the dispatcher.

Classification is idempotent by `session_id`/`turn_id` and persists state under
`~/.local/state/jev-router`. State records prompt, cwd, probabilities, executor,
result, and checks; output must not print input context. The hook prints the state path
and the explicit command `jev-dispatch STATE.json` in routing context.
Judgment diagnostics default on; JEV_PRINT_JUDGMENTS=0 hides them without disabling
routing. Hook flags --print-judgments / --no-print-judgments override that environment
setting. Errors remain visible. Do not reproduce hidden diagnostics in the final reply.

## Dispatcher protocol

For a simple request, invoke:

```bash
jev-dispatch /path/to/STATE.json
```

The dispatcher uses an atomic file lock and states `luna_ready`, `luna_running`,
`done`, or `failed`; `current_required` returns the current-session decision only.
Calling a `done` state returns its saved result without starting Luna again. An
interrupted `luna_running` state is not automatically retried; the parent handles it.

The Luna worker is an independent `codex exec -m gpt-5.6-luna`, with read-only,
no-tools reply instructions. It returns the completed simple answer directly. There is
no post-hoc Jev verification and no parent review on this accepted path. Worker failure
sets failed and returns responsibility to the current session. This worker is not a native subagent; complex tasks may still be
planned and delegated by the current model using native Luna subagents.

For a coding task, the current session first adds scope, context, and actual checks to
a task file, then reuses the already-classified state without rerouting:

```bash
jev-dispatch /path/to/STATE.json --task-file /tmp/task.json \
  --sandbox workspace-write
```

Task fields are non-empty `task`, `context`, `acceptance_criteria`, `allowed_paths`,
and `checks`; checks are argv arrays with no shell parsing. Checks run against the
actual worktree, and any failed check makes the state `failed` and returns current.
The default sandbox is `read-only`; `workspace-write` requires explicit task authority.
Simple chat does not require Git or a task JSON. The dispatcher also supports coding
tasks in non-Git directories; the legacy jev-execute manifest entry still requires Git HEAD.

## Existing manifest entry

`jev-execute` remains available for existing complete manifest code tasks. It performs
entry Jev routing and actual checks with conservative fallback, but does not perform a
post-hoc model review. It does not replace the per-input hook classification.

The parent current session owns architecture, decomposition, integration, and the final
decision. A child result never waives parent integration validation. Do not alter global
model settings, native UI, startup commands, permissions, or hook trust, and do not
proactively spawn another strong model. The old `jev-chat` path is legacy and is not
recommended. No UI verification is implied.

For script workers (JEV_SCRIPT_WORKER=1), do not invoke this entry workflow again.
Executable checks run under the parent tool environment; only use user-authorized
commands. The worker sandbox is not a separate sandbox for those parent checks.

## Live controls and delegated review

Use `jev status` in a terminal to see all switches. `jev-hook status` reports whether
the Codex UserPromptSubmit hook is physically installed; `jev-hook off` removes only
that hook and `jev-hook on` restores it. Use `jev on/off` for the master switch,
`jev entry on/off` for entry classification, and `jev print on/off` for diagnostics.
Settings live in ~/.config/jev-router/settings.json and override environment defaults.
If the hook says entry is disabled, handle input here without reclassifying. If the
master switch is off, handle work normally and do not invoke Jev or its
dispatch/execute/register/check/verify pipeline. The current model decides task
execution, checks, delegation and review under ordinary task rules.

The no-review rule applies only to simple work selected at entry. When the current
model delegates a decomposed subtask to native Luna, first register the bounded
manifest with `jev-run register TASK.json --repo REPO` (Git HEAD required; no entry
classification), then after execution use `jev-run check RUN_DIR --report REPORT.json`
and `jev-run verify RUN_DIR`. Reports have status, summary and unresolved fields.
Jev determines whether parent review is needed. Missing or stale evidence, failed
checks, unavailable/disabled Jev return current_review. Non-Git delegated work without
this evidence protocol remains with the current model for review. The parent's final
integration responsibility remains. `jev-execute --parent-run` also retains this gate.
