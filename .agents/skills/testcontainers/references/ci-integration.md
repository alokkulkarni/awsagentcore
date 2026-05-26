# CI/CD integration guidance for Testcontainers

## GitHub Actions
- GitHub-hosted Ubuntu runners already expose a Docker daemon.
- Prefer `runs-on: ubuntu-latest`.
- Add `permissions: { contents: read }` when missing.
- Self-hosted runners may need `TESTCONTAINERS_HOST_OVERRIDE=localhost`.

## GitLab CI
- Use `docker:dind` in `services`.
- Set `DOCKER_HOST=tcp://docker:2375` and `DOCKER_TLS_CERTDIR=""`.
- Set `TESTCONTAINERS_HOST_OVERRIDE=docker`.

## Jenkins
- Mount `/var/run/docker.sock:/var/run/docker.sock` when running build agents inside Docker.
- Keep the Docker CLI and daemon compatible.

## CircleCI / Bitbucket / Azure DevOps
- Ensure either privileged DinD or a mounted Docker socket.
- Export `TESTCONTAINERS_HOST_OVERRIDE` when the daemon host differs from `localhost`.
- Prefer explicit smoke validation after patching the pipeline.
