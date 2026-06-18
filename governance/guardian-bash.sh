#!/bin/bash
# Guardian Bash Hook — system-enforced safety for agent-driven development.
#
# This is the SANITIZED, portable version of the hook that runs on my real
# multi-project operator stack. It is wired as a Claude Code PreToolUse hook,
# so it runs on EVERY shell command an agent tries to execute and DENIES
# destructive or irreversible operations BEFORE they run. The agent cannot
# opt out — the block happens in the harness, not in the model.
#
# Why this exists: an agent that can write code can also `rm -rf` your repo,
# force-push over main, or `cat .env` into a log. Tests catch bad code after
# the fact; this catches catastrophic *actions* before the fact. It is the
# difference between "uses agents" and "can be trusted to run agents on prod."
#
# Install:  add to ~/.claude/settings.json under hooks.PreToolUse (matcher "Bash")
#           pointing at this script.
# Test:     bash governance/prove_guardian.sh
#
# Contract: read JSON from stdin, emit a PreToolUse decision as JSON, exit 0.
set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null) || {
  jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:"GUARDIAN BLOCK: hook parse error (jq failed). Command blocked for safety."}}'
  exit 0
}
[ -z "$COMMAND" ] && exit 0

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# ===========================================================================
# TIER 1 — HARD BLOCK: destructive / irreversible operations
# ===========================================================================

# rm -rf targeting root, home, parent dirs, or broad paths
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(\/\s|\/\*|\/\b|~|\.\.|\$HOME|\$\{HOME\})'; then
  deny "GUARDIAN BLOCK: Destructive rm -rf targeting root/home/parent. Use a specific subdirectory path instead."
fi

# pipe-to-shell (curl|bash, wget|sh, ...) — the classic supply-chain footgun
if echo "$COMMAND" | grep -qE '(curl|wget|fetch)\s+[^|;&]*\|\s*(bash|sh|zsh|fish|source|eval)\b'; then
  deny "GUARDIAN BLOCK: Pipe-to-shell detected. Download first, inspect, then execute."
fi

# chmod 777 (world-writable)
if echo "$COMMAND" | grep -qE 'chmod\s+(-[a-zA-Z]*\s+)?777(\s|$)'; then
  deny "GUARDIAN BLOCK: chmod 777 creates world-writable files. Use 755 or 644 instead."
fi

# git push --force to main/master
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force.*\s+(main|master)\b|git\s+push\s+-f\s+.*\s+(main|master)\b'; then
  deny "GUARDIAN BLOCK: Force push to main/master is blocked. This can destroy shared history."
fi

# git reset --hard (loses uncommitted work)
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  deny "GUARDIAN BLOCK: git reset --hard destroys uncommitted changes. Stash first or use --soft."
fi

# git clean -f (deletes untracked files permanently)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+(-[a-zA-Z]*f|-f)'; then
  deny "GUARDIAN BLOCK: git clean -f permanently deletes untracked files. Review with git clean -n first."
fi

# direct credential / key file access via cat/echo/export/printf
if echo "$COMMAND" | grep -qE '(cat|echo|export|printf).*(\.env\b|credentials|secret[s]?\.|\.pem\b|id_rsa|id_ed25519|\.age\b)'; then
  deny "GUARDIAN BLOCK: Direct access to a credential/key file detected. Handle secrets manually outside the agent."
fi

# eval with variable expansion (code-injection vector)
if echo "$COMMAND" | grep -qE '\beval\s+"\$'; then
  deny "GUARDIAN BLOCK: eval with variable expansion is a code-injection risk."
fi

# ===========================================================================
# TIER 2 — WARN: allow, but append to an audit log (does not block)
# ===========================================================================
LOG="${GUARDIAN_LOG:-$(dirname "$0")/guardian-audit.log}"
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

if echo "$COMMAND" | grep -qE 'find\s+.*-delete|xargs\s+rm'; then
  echo "[$(ts)] WARN bulk-delete: $COMMAND" >> "$LOG" 2>/dev/null || true
fi
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f'; then
  echo "[$(ts)] WARN force-push (non-main): $COMMAND" >> "$LOG" 2>/dev/null || true
fi
if echo "$COMMAND" | grep -qE '(pip3?\s+install|npm\s+install)\s+'; then
  echo "[$(ts)] INFO package-install: $COMMAND" >> "$LOG" 2>/dev/null || true
fi

# Passed every check — allow.
exit 0
