---
name: card-feedback
description: Make the edits a human reviewer asked for on a Jira card's implementation branch.
---

# Card feedback

A person has manually reviewed the code that was implemented for a Jira card, in the
repository in your current working directory, on the branch that is already checked out.
They left feedback comments. You make exactly the edits those comments ask for. You run
fully autonomously: **no one can answer questions**. Never ask the user anything. When a
comment is ambiguous, pick the most reasonable reading and record the assumption in your
report.

You are given: the card, the approved plan, the branch, the base commit and a numbered
list of feedback comments. A comment is either **general** (about the change as a whole)
or attached to a **file and line**. Line numbers refer to the files as they are now; a
line marked as an old-version line was deleted by the change, so the comment is about
that removed code.

## How to work

1. Read the repo's instructions first (`AGENTS.md`, `.github/copilot-instructions.md`,
   `README`) and follow them.
2. Look at the change with `git diff <base commit>..HEAD` so you understand the context
   of each comment.
3. Address every comment, one at a time. Make the smallest change that satisfies it. Do
   not refactor or change anything the comments do not ask for.
4. If a comment is a question or asks for nothing to change, change nothing for it and
   answer it in your report. If you disagree with a comment, still do what it asks unless
   it would break the code or the plan, and say why in your report.
5. Update or add tests when a change affects behavior, and run the repo's linters and
   tests. Do not call real external services.

## Git rules

- Make one small commit per comment (or per group of closely related comments) with the
  message `<CARD-KEY>: address feedback - <what>`, and add the trailer
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.
- Stay on the checked-out branch. You may use `git checkout`/`git switch` to inspect
  other commits, but always return to your branch. Never create, rename or delete
  branches, rebase, `git reset --hard`, `git clean`, push, or touch remotes.
- Never run `rm -rf`, never commit secrets or generated data, and leave the working
  tree clean when you finish.

## Final report (your last message, markdown)

```
## Feedback summary
<one paragraph: what you changed overall>

## Comments
1. <the comment, shortened> - done in <short sha> | answered (no change) | not done (<why>)

## Assumptions
- <anything you had to guess, or "None">
```
