# Branching Strategy

This repository uses a strict review workflow.

## Branch Roles

```text
feature/* or docs/*
  -> PR
  -> main
  -> stabilization
  -> PR
  -> R2
```

`main` is the primary integration branch. It contains reviewed work that is ready for normal development and validation.

`R2` is the stable branch. It receives changes only after `main` has been validated and the team agrees the changes are stable enough.

## Required Workflow

All changes must go through pull requests.

Rules for both `main` and `R2`:

- Direct pushes are not allowed.
- Pull requests require at least one approval.
- The approval should come from someone other than the PR author.
- Stale approvals are dismissed when new commits are pushed.
- Open conversations must be resolved before merge.
- Force pushes are not allowed.
- Branch deletion is not allowed.
- Admins are also subject to the same protection rules.

## Normal Development

Use short-lived branches:

```text
feature/<short-topic>
fix/<short-topic>
docs/<short-topic>
test/<short-topic>
chore/<short-topic>
```

Open PRs into `main` for normal work.

Examples:

```text
docs/branching-strategy -> main
feature/feishu-bot-demo -> main
fix/context-pack-ranking -> main
```

## Stable Promotion

Promote stable work from `main` into `R2` with a PR.

The `main -> R2` PR should contain:

- Summary of included changes.
- Validation result.
- Known risks or rollback notes.
- Confirmation that no confidential raw documents are included.

Do not merge experimental or incomplete work into `R2`.

## Approval Ownership

Recommended practice:

- If `PanXingdong` opens a PR, `xydcp` or `lixiang093` reviews it.
- If `xydcp` or `lixiang093` opens a PR, `PanXingdong` reviews it.

The rule is simple: the author should not be the only approver of their own change.

## Emergency Changes

If an urgent fix is needed, still use a PR.

Recommended emergency path:

```text
hotfix/<short-topic> -> PR -> main -> PR -> R2
```

Keep the PR small and document the reason clearly.
