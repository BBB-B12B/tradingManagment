# Security Review Checklist

- Secrets stored via `scripts/setup_secrets.sh` + Vault. No secrets committed.
- Control plane requires auth + logs approvals.
- Cloudflare Workers restricted via API token scope.
- Network egress from orchestrator limited to Binance + monitoring endpoints.
- Review structural SL + breaker logic to avoid abuse.
- Next steps: integrate IAM for config API, run dependency audit.
