# Image update status (Docker and Kubernetes)

The System page can compare a running image's immutable manifest digest with a
registry tag, independently of Watchtower. Checks fetch manifests only: they never
pull image layers, restart containers, or change deployment pins.

Set these environment variables on the **webdashboard process** (the all-in-one
image also runs this process):

| Variable | Meaning |
| --- | --- |
| `EW_UPDATE_IMAGE` | Fully qualified repository and channel tag, e.g. `ghcr.io/murre87/energywizard:latest`. Use the matching component repository for split installations. |
| `EW_RUNNING_IMAGE_DIGEST` | Actual running image's `sha256:…` manifest or index digest. Required. |
| `EW_UPDATE_PLATFORM` | Optional `os/architecture[/variant]`, e.g. `linux/amd64`, `linux/arm64`, `linux/arm/v7`. Defaults to the dashboard process's OS/architecture. |
| `EW_UPDATE_INTERVAL_SECONDS` | Default `21600` (six hours); clamped to 300–604800 seconds. Invalid values use the default. |
| `EW_UPDATE_REGISTRY_USERNAME` | Optional registry username. |
| `EW_UPDATE_REGISTRY_PASSWORD` | Optional registry password/read-only pull token; inject as a secret. |

The checker runs on dashboard startup and periodically thereafter, independently
of browser visits. Page visits also refresh expired results. **Sök efter
uppdateringar** (Check for updates) requests a fresh lookup, with a 30-second
cooldown shared by manual checks. Failed checks show an error and retain the last
successful check timestamp, never an old green status. Checks are per dashboard
process; multiple replicas each maintain their own cache and schedule.

Missing image metadata displays Not configured. The checker does not discover its
own running digest: neither Docker nor the Kubernetes downward API automatically
exposes it as an environment variable. Deployment tooling must supply the actual
digest and update it together with every image pin. A stale supplied digest will
produce a stale comparison. Never resolve the current `latest` tag to infer what
is already running. Use a registry manifest/index digest, not a Docker image
configuration ID. No Docker socket, service-account token, or cluster RBAC is needed.

## Docker Compose example

For an all-in-one install, merge into the existing service (replace DIGEST with
the actual manifest/index SHA-256 hex value):

```yaml
services:
  energywizard:
    image: ghcr.io/murre87/energywizard@sha256:DIGEST
    environment:
      EW_UPDATE_IMAGE: ghcr.io/murre87/energywizard:latest
      EW_RUNNING_IMAGE_DIGEST: sha256:DIGEST
```

For split services, configure the dashboard with its own running image digest
and `ghcr.io/murre87/energywizard-webdashboard:latest`. This checks the configured
image only, not every service in a stack. Existing Watchtower functionality stays
separate and optional; its configuration controls automatic Docker updates.

## Kubernetes example

Merge into the appropriate container in any standard Deployment/StatefulSet pod
template; no particular cluster, namespace or workload name is required:

```yaml
containers:
  - name: energywizard
    image: ghcr.io/murre87/energywizard@sha256:DIGEST
    env:
      - name: EW_UPDATE_IMAGE
        value: ghcr.io/murre87/energywizard:latest
      - name: EW_RUNNING_IMAGE_DIGEST
        value: sha256:DIGEST
      - name: EW_UPDATE_PLATFORM
        value: linux/amd64
```

Keep the image pin and digest environment value driven by the same Helm value or
deployment input. This configuration works with K3s and other Kubernetes
distributions. Adapt platform selection for mixed-architecture deployments.

## Registries and multi-architecture images

Uses HTTPS Registry V2/OCI manifests and bearer-token challenges. Anonymous
token services may use a different HTTPS host. Configured private credentials are
only sent to a token endpoint on the registry's exact host/port, without redirects;
private registries requiring a separate authentication host or basic-only auth
are currently unsupported. Use a read-only pull credential. Credentials and
registry response bodies are excluded from API errors.

An identical index digest is current. Otherwise, resolve both indexes to the
configured platform before comparing; a platform manifest can match its parent
index's selected entry. Unsupported/ambiguous platforms and unavailable old
manifests report Unable to check rather than guessing.

Protocol reference: [Registry HTTP API V2](https://distribution.github.io/distribution/spec/api/).
