# Repository Guidelines

Before pushing, run Gitleaks from the repository root:

```sh
gitleaks git --redact --log-opts='-m HEAD' .
```

Resolve any findings before pushing. To scan all local refs, replace `HEAD` with `--all`.
