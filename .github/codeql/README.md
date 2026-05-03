# CodeQL configuration for CARE

This directory holds the **advanced setup** for CodeQL on this repository.

## Why advanced setup

GitHub's default CodeQL setup is a fine starting point but does not let you:

- pin a non-default query suite (`security-extended`),
- exclude generated/test paths from analysis,
- register internal sanitizers via Models-as-Data so taint queries close at their root cause.

CARE handles user-supplied filesystem paths everywhere (CLI, API, plugin config), so accurate path-injection modelling is critical. The advanced setup here teaches CodeQL about our two internal guards (`care.core.security.safe_join`, `care.core.paths.normalize_input_path`) so the Python `py/path-injection` query stops flagging code that has already been validated.

## Layout

| Path | Purpose |
|------|---------|
| `../workflows/codeql.yml` | Workflow that runs the analysis on push, PR, and weekly cron. |
| `codeql-config.yml` | Query suite, path filters, and pointers to extension packs. |
| `extensions/sanitizers.model.yml` | Models-as-Data: registers internal sanitizers for the Python taint queries. |

## Adding a new sanitizer

1. Edit `extensions/sanitizers.model.yml` and add a row under the `summaryModel` block.
2. Columns (positional): `[package, type, subtypes, name, signature, input, output, kind, provenance]`.
3. For a free function, leave `type` empty and use `kind: value` to declare that data passes through unchanged (i.e. without taint).
4. Open a PR. The next CodeQL run will pick up the model on push to the PR branch.

## Adding a new sink or source

Use `extensible: sinkModel` or `extensible: sourceModel` instead of `summaryModel`, with the kind set to the relevant query (`path-injection`, `command-injection`, etc.). See the [Python pack reference](https://github.com/github/codeql/tree/main/python/ql/lib/semmle/python/frameworks).

## Disabling the default setup

GitHub's *default* CodeQL setup must be disabled in repository settings before this advanced workflow can run, otherwise GitHub reports a duplicate-configuration error.

`Settings -> Code security -> Code scanning -> CodeQL analysis -> ... -> Switch to advanced` (or disable, if the option is presented).

## Verifying alert closure after changes

After merging a sanitizer change, the next scheduled or push run rewrites the alert set. To force an immediate refresh:

1. Re-run the workflow from `Actions -> CodeQL -> Run workflow`.
2. Wait for the run to finish.
3. Open `Security -> Code scanning` and filter by `Tool: CodeQL`. Closed alerts move to the *Closed* tab automatically.

Existing alerts that are *not* closed after a sanitizer model is added likely indicate either (a) the sanitizer model is not being picked up (check the `Initialize CodeQL` step's log for "Loaded extension pack"), or (b) the alert flows through a different code path that bypasses the sanitizer — investigate the alert's source-to-sink path before dismissing.

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

## What the advanced setup does *not* do

- It does not scan YAML, HTML, or CSS — CodeQL has no first-party analyzer for these.
- It does not enforce policy in untracked / `paths-ignore`'d files. Use `scripts/governance_check.py` for those checks.
- It does not replace `tests/offline/` and `tests/contract/` — those are CARE-specific contract checks, not CWE coverage.
