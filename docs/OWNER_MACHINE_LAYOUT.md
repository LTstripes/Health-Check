# Owner machine layout

Canonical local filesystem layout for the Owner Windows machine. This page owns the concrete Health-Check paths; other process documents should link here instead of duplicating absolute paths.

## Canonical root

```text
D:\HealthCheck\
  main\
  stable\
  uat\
  ops\
  workspaces\
    codex\
    opencode\
    grok\
    hermes\
```

| Path | Role | May agents implement here? |
| --- | --- | --- |
| `D:\HealthCheck\main` | Clean trusted checkout of canonical Git `main`; Owner/control operations | **No** |
| `D:\HealthCheck\stable` | Durable private Owner runtime/data | **Never** |
| `D:\HealthCheck\uat` | Disposable Owner-only UAT/recovery profiles | **No** |
| `D:\HealthCheck\ops` | Owner-local scheduler wrappers and operational files | Only when an explicit ops task authorizes it |
| `D:\HealthCheck\workspaces\codex` | Codex task workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\opencode` | OpenCode task workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\grok` | Grok task/review workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\hermes` | Hermes task/review workspaces | Yes, assigned task child only |

There is no separate top-level review tree. A Reviewer uses its own assigned child under the relevant client workspace root. Private product UAT belongs under `uat`, not under an agent workspace.

## Task workspace convention

New work uses one physical workspace per task:

```text
D:\HealthCheck\workspaces\<client>\<issue-or-task>
```

Examples:

```text
D:\HealthCheck\workspaces\codex\256-workspace-janitor
D:\HealthCheck\workspaces\opencode\240-owner-screenshot-metadata
D:\HealthCheck\workspaces\grok\238-security-review
```

The task assignment must state the exact workspace when writes are authorized. A Worker may create/prepare that assigned child, but must not inspect, move, reuse or delete sibling task directories unless the task explicitly authorizes workspace maintenance.

Do not implement by switching branches in `main`. Never place real Owner health data, backups, credentials or provider state in `workspaces`.

## Owner/runtime rules

- `main` is code/control only. Keep it clean and fast-forward it only through the accepted Owner/Integrator flow.
- `stable` is the canonical private profile. Do not reset, repurpose or attach it to Worker branches.
- `uat` is disposable. Create private UAT/recovery state through supported backup/restore rather than copying or mutating Stable ad hoc.
- `ops` contains local operational wrappers. The Windows task `Health-Check owner refresh` uses this root and targets the canonical `main` + `stable` paths.
- Agent client defaults should point new Health-Check work at their matching `workspaces\<client>` root.

## Workspace lifecycle and cleanup

Task workspaces are disposable after delivery. The accepted #256 janitor is deployed as Windows Scheduled Task `Health-Check workspace cleanup`:

- runs **daily at 12:00 local time** with `StartWhenAvailable` and `IgnoreNew`;
- uses `-Apply -RetentionDays 7`;
- writes the latest bounded sanitized report to `D:\HealthCheck\ops\workspace-cleanup-latest.json`;
- considers only immediate task children under the four canonical `workspaces\<client>` roots;
- deletes only when the workspace is old enough, clean, belongs to the expected repository, has no unique local work/private runtime material and passes the remaining fail-closed guards.

This is a daily sweep with a seven-day minimum retention, not a weekly batch. A task normally becomes eligible on the first daily run after it is at least seven days old.

The janitor must never treat `main`, `stable`, `uat`, `ops` or a path outside the four approved workspace roots as a cleanup root. Unknown, active, young, wrong-origin or otherwise ambiguous task directories are preserved.

Do not manually drag active Git worktrees between roots. Let an active task finish in its assigned location, then let the janitor retire it or recreate it safely.

## Legacy paths

`D:\Garmin`, `D:\Codex\Garmin`, `D:\OpenCode\Health-Check`, old Grok/Hermes Health-Check roots and historical UAT/promotion folders are legacy locations. Do not assign new work there. **The automatic janitor does not inspect or delete these legacy roots.**

#256 Phase B already removed the approved historical checkout/UAT/promotion set and reclaimed about 6.64 GiB. Two legacy cases remain deliberately explicit:

- `D:\Garmin\Garmin-Main` was structurally classified READY TO REMOVE (old checkout, no live references; its tiny DB contained only an empty migration marker). It may be removed manually when no process/client uses it.
- `D:\Garmin\HealthCheck-Owner-Data` was intentionally retained because it is historical private Owner evidence. Do not delete the whole `D:\Garmin` root while this directory remains without a separate disposition.
- `D:\OpenCode\Health-Check` was inventoried as a clean client reference checkout with no unique refs and no runtime DB. After OpenCode is repointed to `D:\HealthCheck\workspaces\opencode` and no active process uses the old checkout, it may be removed manually.
- A task directory under the new OpenCode root that reports `wrong-origin` is preserved by design and needs separate manual inspection; do not equate it with the old reference checkout above.

An old path existing on disk does not make it canonical. Legacy cleanup is explicit and manual unless a future task extends the allowlist deliberately.

## When paths change

Update this page first, then update the small set of operational consumers that actually encode the path (for example Ops/Scheduler or client defaults). Do not copy the complete absolute-path table into AGENTS, client adapters or task prompts.
