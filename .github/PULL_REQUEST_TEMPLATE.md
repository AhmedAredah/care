<!-- Thanks for the PR! Please fill in the boxes below. -->

## Summary

<!-- One short paragraph: what does this PR change and why? -->

## Type

- [ ] Bug fix (non-breaking)
- [ ] Feature (non-breaking)
- [ ] Breaking change
- [ ] Documentation only
- [ ] Refactor / chore

## Invariants

CARE's privacy and offline guarantees are non-negotiable. Confirm each that applies:

- [ ] **Plugin boundaries** preserved (no hard-coded model classes in core code).
- [ ] **Offline / no-network** behaviour preserved (no new HTTP calls in the default config).
- [ ] **Fail-closed** behaviour preserved (uncertainty still blocks export).
- [ ] **Safe public exports** preserved (no original PDFs, no unredacted text, no raw PII, no debug artifacts).
- [ ] **Logs** still don't carry raw PII.
- [ ] **Frontend** still uses only local assets — no CDN, fonts, or remote scripts.
- [ ] **Optional ML providers** (Piiranha, Kosmos-2.5, LayoutLM, etc.) are still disabled by default.

## Tests

- [ ] `python scripts/governance_check.py` passes.
- [ ] `uv run pytest` passes.
- [ ] New code is covered by tests, or a clear reason is documented in the PR.

## Documentation

- [ ] Docs updated under `docs/` if user-visible behaviour changed.
- [ ] `README.md` updated if quick-start commands changed.

## Linked issues

<!-- Closes #123, Refs #456 -->

## Reviewer notes

<!-- Anything you want the reviewer to look at first, or known
limitations, or follow-ups you've deferred. -->
