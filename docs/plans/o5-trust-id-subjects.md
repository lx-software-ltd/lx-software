# Plan: Use the ID-form trust subjects

**Status**: Draft
**Zone**: yellow

## Goal

The four product tokens use the ID-form subject. The name-form subjects merged in #670 match none of them. This document lists the four ID-form subjects and nothing else. The account id stays the placeholder `ACCOUNT_ID`.

## Non-goals

Do not apply this to `GitHubActionsRole` until this pull request is merged. Keep the policy that is on the role now, so it can be pasted back. Do not dispatch a deploy from this pull request.

## Files

`docs/architecture/github-actions-trust-policy.json`, this plan.

## Invariants this change preserves

The federated principal and the audience stay as they are. No account id is written. `actions` and `ai-cxo` are not trusted subjects.

## Done when

The `sub` condition is the four `repo:lx-software-ltd@321652495/<name>@<id>:*` values.

## Rollback

Paste back the policy that is on the role today. The document before #670, which is the one to restore if this document is applied and a repository can no longer assume the role, is the wildcard pair `repo:lx-software-ltd/*` and `repo:lx-software-ltd@321652495/*`.

## Open questions

None.
