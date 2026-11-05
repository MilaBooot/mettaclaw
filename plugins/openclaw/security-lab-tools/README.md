# Omega Security Lab Tools

Evaluation-only OpenClaw tools for the disposable container-hardening scenario
in `evals/container_security`. The plugin exposes bounded read, file mutation,
and snapshot operations only for the exact labeled lab container. It does not
expose a shell or general Docker interface.

Build and validate before installation:

```bash
npm install
npm run plugin:build
npm run plugin:validate
npm test
```

See `evals/container_security/README.md` for isolation, installation, agent
allowlists, tracing, execution, and independent verification instructions.
