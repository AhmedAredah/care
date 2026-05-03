# CodeQL configuration for CARE

This directory holds the **advanced setup** for CodeQL on this repository.

## Layout

| Path | Purpose |
|------|---------|
| `../workflows/codeql.yml` | Workflow that runs the analysis on push, PR, and weekly cron. |
| `codeql-config.yml` | Query suite (`security-extended`) and path filters. |

## Why advanced setup

GitHub's default CodeQL setup is fine as a starter but does not let us:

- pin a non-default query suite (`security-extended` catches taint classes the default suite skips),
- exclude generated/test paths from extraction,
- keep the configuration under code review with the rest of the repo.

## What the advanced setup does *not* do

- It does not scan YAML, HTML, or CSS — CodeQL has no first-party analyzer for these.
- It does not register internal sanitizers via Models-as-Data. CodeQL's Python `py/path-injection` query uses a QL `PathSanitizer` class hierarchy for sanitizers; there is no MaD `extensible:` predicate that affects it in CodeQL 2.25. An earlier attempt to register `safe_join` and `normalize_input_path` via `summaryModel` rows was removed because the extensible was wrong for the goal — `summaryModel` declares flow propagation, not sanitization.

## How path-injection alerts are handled

Every open `py/path-injection` alert routes its input through one of:

- `care.core.security.safe_join(base, *parts)` — `Path.resolve()` on both base and candidate, then `relative_to(base)` raises `PathTraversalError` on escape, **or**
- `care.core.paths.normalize_input_path(path_str)` — strips quotes, asserts `is_absolute_cross_platform`, raises `ValueError` on relative input, translates Windows-style paths to WSL on Linux.

CodeQL doesn't see these as sanitizers, so it flags every site that passes user-controlled paths through them as if no sanitization had happened. The professional response is:

1. **Dismiss each alert with rationale** via the code-scanning API or the Security tab UI. Use dismissal reason **"won't fix"** with a short note: *"sanitized by `care.core.security.safe_join`"* or *"sanitized by `care.core.paths.normalize_input_path`"*. The dismissal sticks across re-scans.
2. **For new code**, route any user-supplied filesystem input through one of those two helpers. New `py/path-injection` alerts that reach unsanitized callsites should be fixed in code, not dismissed.
3. **Revisit when CodeQL adds a Models-as-Data hook for `PathSanitizer`** (open feature request upstream). At that point the dismissals can be replaced with a model file in this directory.

A helper script is provided at `scripts/codeql_dismiss_path_injection.sh` that walks every open `py/path-injection` alert, inspects the source file at the alert's line, and dismisses it with the appropriate sanitizer rationale. It dry-runs by default; pass `--apply` to actually dismiss.

## Disabling the default setup

GitHub's *default* CodeQL setup must be disabled in repository settings before this advanced workflow can run, otherwise GitHub reports a duplicate-configuration error on the upload step.

`Settings -> Code security -> Code scanning -> CodeQL analysis -> Switch to advanced` (or *Disable*, if shown).

## Verifying alert closure after changes

After merging a config change, the next scheduled or push run rewrites the alert set. To force an immediate refresh:

1. Re-run the workflow from `Actions -> CodeQL -> Run workflow`.
2. Wait for the run to finish.
3. Open `Security -> Code scanning` and filter by `Tool: CodeQL`. Closed alerts move to the *Closed* tab automatically.

## Local iteration

```bash
# Build a database
codeql database create ./codeql-db --language=python --source-root=.

# Run analysis with the same config CI uses
codeql database analyze ./codeql-db \
  --format=sarifv2.1.0 \
  --output=results.sarif \
  --config-file=./.github/codeql/codeql-config.yml \
  codeql/python-queries:codeql-suites/python-security-extended.qls
```
