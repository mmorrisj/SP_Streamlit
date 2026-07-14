# Quick Start

> This page is a pointer — the canonical quick start lives in the
> [main README](../README.md#quick-start), and every deployment scenario is routed by
> [DEPLOYMENT.md](../DEPLOYMENT.md).

The zero-prerequisite path (full stack from a fresh checkout):

```bash
cp .env.example .env                    # add credentials
docker compose up -d --build            # default docker-compose.yml
docker compose --profile migrate up     # run DB migrations
```

- React app + API: http://localhost:8000
- Streamlit dashboard: http://localhost:8501

Full demo walkthrough (including data): [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md).

| You want… | Go to |
|---|---|
| Any other deployment scenario | [DEPLOYMENT.md](../DEPLOYMENT.md) (decision tree) |
| Development with hot-reload | [DOCKER_WORKFLOW.md](../DOCKER_WORKFLOW.md) |
| Enterprise / hardened daemon | [PRODUCTION_DOCKER_RUN.md](../PRODUCTION_DOCKER_RUN.md) |
| The published image | [DOCKERHUB_README.md](DOCKERHUB_README.md) |
| Pipeline commands | [CLAUDE.md](../CLAUDE.md) |
