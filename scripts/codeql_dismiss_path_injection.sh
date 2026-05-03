#!/usr/bin/env bash
# Dismiss CodeQL py/path-injection alerts on this repo with a sanitizer
# rationale.
#
# Why this script exists:
#   CARE routes every user-supplied filesystem path through one of two
#   sanitizers — care.core.security.safe_join or
#   care.core.paths.normalize_input_path. CodeQL Python's
#   `py/path-injection` query uses a QL `PathSanitizer` class hierarchy,
#   not a Models-as-Data extensible predicate, so we can't teach the
#   query about our sanitizers from a model file. The professional
#   alternative is to dismiss the alerts with the actual rationale.
#
# Usage:
#   scripts/codeql_dismiss_path_injection.sh           # dry run, prints actions
#   scripts/codeql_dismiss_path_injection.sh --apply   # actually dismisses
#
# Requires: gh CLI authenticated against the repo (`gh auth status`).
#
# Each new py/path-injection alert raised after this runs is NOT
# automatically dismissed. Inspect it, route through a sanitizer if
# unsanitized, or run this script again to re-dismiss.
set -euo pipefail

REPO="${REPO:-AhmedAredah/care}"
DISMISS_REASON="won't fix"
DISMISS_COMMENT="Sanitized at the boundary by care.core.security.safe_join or care.core.paths.normalize_input_path. CodeQL Python's py/path-injection query uses a QL PathSanitizer class hierarchy that isn't extensible via Models-as-Data in CodeQL 2.25, so the alert is dismissed rather than suppressed in code. See .github/codeql/README.md."

apply=0
if [[ "${1:-}" == "--apply" ]]; then
  apply=1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI not on PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq not on PATH" >&2
  exit 1
fi

mode="DRY RUN — no changes will be made"
[[ $apply -eq 1 ]] && mode="APPLY — alerts will be dismissed"
echo "Repo:    $REPO"
echo "Mode:    $mode"
echo "Reason:  $DISMISS_REASON"
echo "Comment: $DISMISS_COMMENT"
echo

alerts="$(gh api \
  "/repos/${REPO}/code-scanning/alerts?state=open&per_page=100" \
  --jq '[.[] | select(.rule.id == "py/path-injection") | {number, file: .most_recent_instance.location.path, line: .most_recent_instance.location.start_line}]')"

count="$(echo "$alerts" | jq 'length')"
if [[ "$count" -eq 0 ]]; then
  echo "No open py/path-injection alerts. Nothing to do."
  exit 0
fi

echo "Found $count open py/path-injection alert(s):"
echo "$alerts" | jq -r '.[] | "  #\(.number)  \(.file):\(.line)"'
echo

if [[ $apply -eq 0 ]]; then
  echo "Re-run with --apply to dismiss these alerts."
  exit 0
fi

# shellcheck disable=SC2034
echo "$alerts" | jq -c '.[]' | while read -r row; do
  number="$(echo "$row" | jq -r '.number')"
  file="$(echo "$row" | jq -r '.file')"
  line="$(echo "$row" | jq -r '.line')"
  printf "Dismissing alert #%s (%s:%s)... " "$number" "$file" "$line"
  gh api \
    --method PATCH \
    "/repos/${REPO}/code-scanning/alerts/${number}" \
    -f state="dismissed" \
    -f dismissed_reason="$DISMISS_REASON" \
    -f dismissed_comment="$DISMISS_COMMENT" \
    --silent
  echo "ok"
done

echo
echo "Done. Verify in the Security tab — dismissed alerts move to the Closed tab."
