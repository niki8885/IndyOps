# Security Policy

## Supported versions

Only the latest commit on `master` receives security fixes. There are no versioned releases with separate support windows at this time.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.** Public disclosure before a fix is ready puts all users at risk.

Instead, please report privately via GitHub's built-in mechanism:

1. Go to the [IndyOps repository](https://github.com/niki8885/IndyOps).
2. Click **Security → Report a vulnerability**.
3. Fill in the form with as much detail as possible (see below).

Alternatively, you can reach the maintainer directly at **nikita.manaenckov@gmail.com** with the subject line `[IndyOps] Security`.

## What to include in your report

- **Description** — what the vulnerability is and which component is affected.
- **Steps to reproduce** — the minimal sequence of actions or inputs that trigger it.
- **Impact** — what an attacker could achieve (data exposure, privilege escalation, denial of service, etc.).
- **Suggested fix** — optional, but always welcome.
- **Your contact details** — so we can follow up and credit you if you wish.

## Response timeline

| Step | Target time |
|------|-------------|
| Acknowledge receipt | 48 hours |
| Initial assessment | 5 business days |
| Fix or mitigation | Depends on severity — critical issues are prioritised |
| Public disclosure | After a fix is released, coordinated with the reporter |

These are best-effort targets for a solo/small-team project. Complex or critical issues may take longer.

## Scope

The following are **in scope**:

- Authentication or authorisation bypass in the FastAPI backend
- SQL injection or ORM query manipulation
- Exposure of environment variables, secrets, or user data via API responses
- Cross-site scripting (XSS) or cross-site request forgery (CSRF) in the frontend
- Privilege escalation between organisation roles
- Supply-chain issues in direct dependencies

The following are **out of scope**:

- Vulnerabilities in EVE Online itself or CCP's APIs
- Issues that require physical access to the server
- Self-XSS or social-engineering attacks
- Rate-limiting or denial-of-service against a self-hosted instance where the attacker controls the host
- Theoretical vulnerabilities with no realistic exploit path

## Disclosure policy

We follow **coordinated disclosure**: the maintainer and reporter agree on a disclosure date after a fix is available. Credit will be given in the release notes unless you prefer to remain anonymous.

## Third-party dependencies

If you find a vulnerability in a dependency (e.g., FastAPI, SQLAlchemy, a npm package), please report it upstream to that project. You are welcome to notify us as well so we can track and apply updates.
