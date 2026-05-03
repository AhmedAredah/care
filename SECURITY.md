# Security Policy

CARE handles personally identifying information from sensitive
documents. We treat security reports with the same priority as a
production incident.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Instead, use one of these private channels:

- **GitHub Private Vulnerability Reporting** — preferred. Open the
  [Security tab][advisories] on this repo and click *"Report a
  vulnerability"*.
- **Email** — `ahmed.aredah@gmail.com` with subject line starting
  with `[CARE security]`.

We will acknowledge receipt within **3 business days** and aim to
ship a fix or mitigation within **30 days** for high/critical issues.

[advisories]: https://github.com/AhmedAredah/care/security/advisories/new

## What's in scope

CARE is offline-first. We're particularly interested in reports about:

- **PII leakage paths** — any code path where raw, unredacted PII
  could escape the working directory into a public-export artifact,
  log file, telemetry, or network call.
- **Network egress in offline mode** — any code path that reaches the
  internet when `offline.enabled: true` (the default). The offline
  guard (`care/core/offline_guard.py`) is meant to make this
  impossible; report any way around it.
- **Path traversal** — any input that lets a request read or write
  outside the configured `work_dir` / `export_dir` / templates dir.
- **Plugin loading from user paths** — CARE's plugin registry
  rejects unknown names by design. Any way to coerce plugin loading
  from an arbitrary user-controlled path is in scope.
- **Model loading without `local_files_only=True`** — Hugging Face
  providers must never reach the network. Report any provider that
  bypasses this.
- **Fail-closed bypasses** — code paths that allow an export to ship
  with unmapped PII, low-confidence OCR, VLM/OCR conflicts, or
  unknown templates.
- **Loopback-binding bypasses** — the API server must never bind to
  a non-loopback host without explicit operator override.
- **Secrets sidecar leaks** — the API surface must remain write-only
  for secret values; report any way to read a secret back through it.

## What's out of scope

The threat model in [`docs/security.md`](docs/security.md) is
authoritative. In short, CARE does **not** defend against:

- A malicious operator on the same host as the runtime. The host's
  filesystem ACLs are the trust boundary; once an attacker has the
  user's write privileges, they can read/write the same data CARE can.
- Compromise of the workstation kernel, hypervisor, or hardware.
- Side-channel timing or cache attacks.
- Social engineering of operators into enabling cloud LLM providers
  with attacker-controlled API keys.

Reports about these are interesting context but not vulnerabilities
in CARE itself.

## Coordinated disclosure

We follow standard coordinated disclosure:

1. You report privately.
2. We confirm and start work on a fix.
3. We agree on a public-disclosure date — typically the day a fixed
   release ships, or 90 days from initial report, whichever is sooner.
4. We credit you in the release notes (unless you prefer anonymity).

## Bug bounty

CARE is an unfunded open-source project. We can't pay bounties, but
we'll acknowledge security researchers prominently in the release
notes and [`docs/security.md`](docs/security.md) credits section.

## PGP

If you need to encrypt a report, ask via the email channel and we'll
exchange a key.
