# Governance layer

This is the part most "I use agents" portfolios leave out: **the layer that makes
agent-written code safe to ship.**

An agent that can write code can also delete your repo, force-push over `main`, or
read your `.env` into a log. Tests catch bad *code* after the fact. This catches
catastrophic *actions* before the fact — in the harness, where the model cannot
opt out.

## What's here

| File | What it is |
|---|---|
| [`guardian-bash.sh`](./guardian-bash.sh) | Sanitized, portable copy of the `PreToolUse` hook that runs on my real multi-project stack. Runs on **every** shell command an agent attempts and denies destructive ones. |
| [`prove_guardian.sh`](./prove_guardian.sh) | Self-checking proof: feeds dangerous commands to the hook and shows each is denied; includes safe controls to prove it isn't just denying everything. |

## Run the proof

```bash
bash governance/prove_guardian.sh
```

Expected: every dangerous command (`rm -rf ~`, `git push --force main`,
`git reset --hard`, `chmod 777`, `cat .env`, `curl … | bash`) returns `⛔ deny`
with a human-readable reason; the safe controls (`ls -la`, `pytest`) return
`✅ allow`. Exit code `0` means the layer behaves correctly.

## How it's wired in real life

In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "~/.claude/hooks/guardian-bash.sh" }] }
    ]
  }
}
```

Claude Code calls the hook before running any Bash command. The hook reads the
command from stdin, and a `permissionDecision: "deny"` stops it cold — the agent
sees the reason and has to find a safe path. Tier-2 patterns (bulk deletes,
non-main force-pushes, package installs) are allowed but appended to an audit log,
so there's a paper trail of everything sensitive an agent did.

The production version adds project-specific deny rules (protecting client data
files and operator config) and an out-of-band alert. Those are stripped here —
this is the portable, generic core.
