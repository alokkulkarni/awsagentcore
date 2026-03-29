# ADR-007: AgentCore Runtime — Docker Container in ECR (Not ZIP Upload)

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

AgentCore Runtime supports two deployment modes:

1. **ZIP upload** — upload a zip of Python code; AgentCore provides the Python runtime
2. **Docker container** — build a Docker image, push to ECR, AgentCore runs the container

ARIA has significant runtime dependencies (boto3, strands-agents, and other packages), runs on ARM64/Graviton as required by the AgentCore Runtime, and must exclude audio I/O libraries (PyAudio) that are present in the local development environment. A deployment model that provides full dependency control, reproducible builds, and avoids cross-architecture issues on developer machines is required.

## Decision

All ARIA deployments to AgentCore Runtime use a Docker container image pushed to Amazon ECR, built via AWS CodeBuild (arm64).

The build and deployment pipeline is:

```
Developer machine
    ↓  git push
CodeBuild (arm64)
    ↓  docker build --platform linux/arm64
    ↓  docker push → ECR
    ↓  agentcore launch (reads .bedrock_agentcore.yaml)
AgentCore Runtime (eu-west-2, Graviton)
```

**Key reasons for this decision:**

- **No ZIP size limits** — ARIA has significant dependencies (boto3, strands-agents, etc.). ZIP-based deployment has practical size limits that constrain what can be included.
- **Full dependency control** — `Dockerfile` pins every system-level and Python dependency; `requirements-docker.txt` excludes PyAudio (no mic/speaker in a cloud container).
- **ARM64 requirement** — AgentCore Runtime requires ARM64/Graviton architecture. Docker + CodeBuild handles cross-compilation transparently without requiring ARM toolchains on developer machines.
- **Reproducible builds** — the `Dockerfile` is source-controlled; every build produces the same image, eliminating "works on my machine" issues.
- **CodeBuild avoids local Docker need** — developers do not need Docker Desktop or ARM64 cross-compilation tools locally; CodeBuild handles all image construction.
- **Production standard** — containerisation aligns with how production banking services are deployed (ECS/EKS), making this model familiar to operations teams.

**Deployment artifacts:**

| Artifact | Purpose |
|---|---|
| `Dockerfile` | Python 3.12 slim base; installs `requirements-docker.txt`; sets entrypoint |
| `requirements-docker.txt` | Production deps **without** PyAudio (no audio I/O in cloud container) |
| `.bedrock_agentcore.yaml` | Container image URI, execution role ARN, region, environment variable declarations |
| `buildspec.yml` | CodeBuild spec: ECR login → `docker build` → `docker push` → `agentcore launch` |

**`agentcore launch`** reads `.bedrock_agentcore.yaml` and registers the container image URI with AgentCore Runtime in `eu-west-2`.

Example `buildspec.yml` structure:

```yaml
phases:
  pre_build:
    commands:
      - aws ecr get-login-password --region $AWS_REGION | docker login ...
  build:
    commands:
      - docker build --platform linux/arm64 -t $IMAGE_URI .
      - docker push $IMAGE_URI
  post_build:
    commands:
      - agentcore launch --config .bedrock_agentcore.yaml
```

## Consequences

### What this enables

- Full control over the Python version, system libraries, and dependency set in production.
- PyAudio and other audio I/O libraries are cleanly excluded from the cloud image without affecting the local development environment (`requirements.txt` retains them).
- ARM64/Graviton compatibility is handled at build time; no developer action required.
- Image immutability: each ECR push produces a tagged, immutable image that can be rolled back.

### Trade-offs and limitations

- Developers need access to CodeBuild (or a CI/CD pipeline) to produce deployable images; they cannot `agentcore launch` from a laptop without a pre-built ECR image.
- Docker image build times are longer than ZIP packaging (typically 3–6 minutes in CodeBuild vs. seconds for a ZIP).
- ECR storage costs apply (minor; lifecycle policies prune old images automatically).
- `requirements-docker.txt` must be kept in sync with `requirements.txt` manually — a divergence would cause production to behave differently from local development.

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| ZIP upload | ZIP size limits constrain dependency set; no system-level dependency control; Python runtime version tied to AgentCore platform choice |
| Lambda container image | Lambda is stateless by design — incompatible with ARIA's session-state model (conversation history, PII vault) |
| ECS/Fargate directly | Bypasses AgentCore Runtime session management and Memory API; requires building session lifecycle management from scratch |
| Local ZIP without CodeBuild | ARM64 cross-compilation from x86 developer machines is complex and error-prone; requires Docker Desktop with buildx configured |

## Implementation reference

| File | Role |
|---|---|
| `Dockerfile` | Container image definition; Python 3.12 slim; installs `requirements-docker.txt` |
| `requirements-docker.txt` | Production Python dependencies (PyAudio excluded) |
| `requirements.txt` | Local development dependencies (includes PyAudio for voice input) |
| `.bedrock_agentcore.yaml` | AgentCore Runtime configuration: image URI, role ARN, region, env vars |
| `buildspec.yml` | AWS CodeBuild pipeline: build → push → launch |

## Related documents

- [docs/agentcore-deployment-guide.md](../agentcore-deployment-guide.md) — step-by-step deployment instructions
- [ADR-009](ADR-009-cross-region-model-access.md) — region selection for AgentCore Runtime (eu-west-2)
