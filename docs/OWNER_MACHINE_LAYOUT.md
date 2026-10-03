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

Task workspaces are disposable after delivery. They may be removed only after the workspace-cleanup contract proves there is no dirty/untracked content, unique local work or private/runtime material and the task is old enough for cleanup.

The automatic janitor being completed under #256 is allowed to delete only task children under the four `workspaces` client roots. It must never treat `main`, `stable`, `uat` or `ops` as cleanup roots.

Do not manually drag active Git worktrees between roots. Let an active task finish in its assigned location, then retire/recreate it safely.

## Legacy paths

`D:\Garmin`, `D:\Codex\Garmin`, old OpenCode/Grok/Hermes Health-Check roots and historical UAT/promotion folders are legacy locations. Do not assign new work there.

Legacy directories are deleted only through the #256 inventory/cleanup decisions; an old path existing on disk does not make it canonical.

## When paths change

Update this page first, then update the small set of operational consumers that actually encode the path (for example Ops/Scheduler or client defaults). Do not copy the complete absolute-path table into AGENTS, client adapters or task prompts.
