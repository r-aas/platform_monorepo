---
name: security-audit
version: 1.0.0
description: Scan code and infrastructure for vulnerabilities and generate remediation
  reports
tags:
- security
- audit
- vulnerability
operations:
- gitlab_browse_files
- gitlab_browse_commits
- kubectl_get
- kubectl_describe
---

When performing security audits:
- Prioritize by severity: critical (RCE, auth bypass) > high (data exposure) > medium > low
- Check OWASP Top 10 categories systematically: injection, broken auth, sensitive data, XXE, IDOR, misconfiguration, XSS, deserialization, known vulnerabilities, logging gaps
- For infrastructure: check RBAC permissions, network policies, secret management, image provenance
- Report findings with: severity, location, description, and a concrete remediation step
- Never report theoretical issues without evidence from the scanned artifacts
- Distinguish between vulnerabilities (exploitable now) and hardening recommendations (reduce attack surface)

