# Security Policy

## Reporting a vulnerability

**Please don't open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting for this repo: go to the
**Security** tab → **Advisories** → **Report a vulnerability**. That opens a
private thread with the maintainers only, and doesn't need an email address
or any other setup on your end.

If you can't use that for some reason, open a regular issue asking for a
private channel and describe nothing about the vulnerability itself there —
just that you have one to report.

Please include, as far as you can:

- What you found and where (file/endpoint/component).
- Steps to reproduce, or a proof of concept.
- What you think the impact is (what an attacker could actually do with it).

There's no bug bounty — this is an open-source project, not a hosted
service — but reports are taken seriously and credited unless you'd rather
stay anonymous.

## Supported versions

Firsthand is pre-1.0 and doesn't yet have tagged releases; `main` is the only
supported line. Once releases start, this section will list which ones still
get security fixes.

## Scope and known limitations

A few things worth knowing before you rely on this in production, so a
report isn't needed for something already documented as a limitation:

- **PII redaction is best-effort, not a DLP guarantee** (§1, §7). It's a
  deterministic pattern pass plus an optional Presidio/spaCy NER layer for
  names and places — deliberately conservative, so it leaves alone anything
  it isn't confident about rather than risk destroying the reporter's meaning
  with a false redaction. `raw_text` is retained (for human review of
  escalations) alongside the redacted copy — anyone with access to the
  `StateStore`/database can read it. Don't point this at a stream of text you
  can't afford to have imperfectly redacted.
- **The Jira/Git/Docs connector credentials** are encrypted at rest with a
  key from `FIRSTHAND_SECRET_KEY`, which must live only in the deployment
  environment (§8.7) — anyone with that key and database access can decrypt
  every stored credential. Rotate it like you would any other master key.
- **The web chat is intentionally unauthenticated** — that's a product
  decision (reporting a request should have no friction), not an oversight.
  Everything that reads aggregated data — the dashboard, the configuration
  page — is behind the admin login.
- This project calls an external LLM API for generation (§7). Only redacted
  text is ever sent — see the redaction caveat above for what that guarantees
  and what it doesn't.

If you're deploying this somewhere sensitive, read [CLAUDE.md](CLAUDE.md)'s
non-negotiables and treat anything that seems to violate one of them as worth
a report even if you're not sure it's exploitable.
