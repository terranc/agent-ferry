# Git Workflow

## Branches

Develop and commit directly on `master` by default, as requested by the owner.
Do not create a feature branch, worktree, or pull request automatically. Use an
alternative workflow only when the user explicitly requests it.

Check the current branch and working tree before making changes. Preserve
unrelated work; never use a hard reset, force push, or history rewrite to align
branches.

## Local Files Must Survive Branch Changes

Only `.trellis/spec/` is tracked inside `.trellis/`. Other Trellis data and
project-local AI directories remain on disk and are ignored.

An older branch can still track these files. Switching to it and then merging
the cleanup commit can overwrite or delete the local copies, even though the
current ignore rules exclude them. Inspect both revisions and create a private
backup of affected local files before such a transition. Verify file existence
and content after the switch. Never assume `git rm --cached` protects files
from later branch checkouts or merges.

## Commits and Pushes

Use Simplified Chinese commit messages with English Conventional Commit prefixes.
Commit only the requested work after relevant checks pass. Keep ignored local
files out of commits; deleting them from the repository must preserve them on
the owner's machine.

A commit request authorizes a local commit. Push `master` to `origin/master`
when the user requests a push, after fetching and checking for remote changes.
Use normal fast-forward pushes. Do not fabricate a branch or PR merely to fit
generic task-helper examples.
