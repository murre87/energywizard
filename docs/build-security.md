# Build security review (2026-11-11)

Tracked in [issue #273](https://github.com/murre87/energywizard/issues/273).
No production deployments or volume ownership changes are part of this review.

## Image policy

The normal images retain Python 3.11 and the existing `numpy<2.4` CPU compatibility
limit. Their Python 3.11.18 Debian Trixie base is pinned by digest. Builds apply
available Debian updates and install pip 26.3, setuptools 84.2.1 and wheel 0.46.3.
The all-in-one image retains PostgreSQL 17; this is not a database major upgrade.

The NumPy cap is temporary compatibility protection, not a security-support
guarantee. See the [NumPy security/upgrade review](numpy-upgrade.md) for current
advisory checks, review dates and the source-build evaluation for older CPUs.

`image-security` rebuilds and audits daily at 04:47 UTC, on demand, and through
the test workflow. Publishing audits the actual loaded image before pushing it;
both all-in-one architectures must pass before a multi-architecture tag is
promoted. All-in-one publishing bypasses the old persistent layer cache so
available apt fixes are actually applied even before the base digest changes.
New security findings therefore can block releases. Daily audits
report failures but do not automatically update deployed containers.

`scripts/audit_image.py` inventories installed Python distributions without
starting the application, runs pip-audit, and scans a saved image archive using
digest-pinned Grype. It rejects Python advisories, CISA Known Exploited
Vulnerabilities (KEV), and Debian findings with available fixes. Missing or stale
feed/database evidence fails the audit. Full reports, including findings outside
that gate, are retained as workflow artifacts for 14 days. No Docker socket,
Docker credentials or user home directory is mounted into the scanner.

The patched all-in-one amd64 image passed this policy locally: zero Python
advisories, matching KEVs or available Debian fixes. Grype still reported 452 raw
matches, down from 465. These include unfixed and generic CPE matches requiring
triage; passing the gate does **not** mean CVE-free or prove non-exploitability.
The application dependency union alone had no pip-audit findings, whereas the
baseline installed image exposed outdated packaging tools. Audit installed
images rather than relying only on requirements files.

## Workflow dependencies

Reviewed actions use full commit SHAs and current Node 24 releases. Dependabot
checks actions, Python requirements and normal Docker bases weekly. Simulator
builds use Go 1.27.4 instead of the unsupported Go 1.22 toolchain; the pinned
third-party simulator successfully compiles with that verified toolchain.
Its `./cmd/simulator` source passed govulncheck 1.9.0 at symbol level using the
November 11 Go vulnerability database; this does not cover the desktop GUI.

Latest action releases still have upstream dependency advisories. Production
lockfile npm audits reported: checkout 1, setup-python 5, setup-go 5,
upload-artifact 11 and github-script 7. The latest upload-artifact removes the
critical finding seen in the previous release. Docker action production Yarn
closures, queried against OSV, had 10 affected packages for build-push, 8 for
login, 10 for Buildx and 11 for QEMU, with no unresolved dependency descriptors.
These counts are package/advisory audit results, not proven reachable exploits
in the distributed action bundles. Pinning prevents mutable-tag substitution;
it does not eliminate upstream vulnerabilities. Re-audit updates and review
upstream fixes before treating this risk as resolved.
The 51 distinct action GHSAs were expanded through OSV aliases and compared
with the November 10 CISA catalog (1,779 entries): no matches. Absence from KEV
does not establish non-exploitability.

The coffee-supporter workflow now uses a local Python standard-library script
instead of the composite action's mutable nested actions and Node 16/npm chain.
Only the reviewed, SHA-pinned checkout remains, with credential persistence off.
Coffee/GitHub tokens are supplied only to the updater step. It retains the nightly
schedule, missing-token skip, three-message HTML format and main-only README
update. Supporter text is HTML-escaped; redirects are rejected, and API failures
do not log response bodies or credentials. Updates use the current README SHA
so a concurrent edit fails rather than being overwritten. Tests use synthetic
responses; no live supporter read or README publication was performed.

## Optional Docker Hardened Images

The four split services include optional `Dockerfile.dhi` builds. Example:

```sh
docker login dhi.io
docker build -f telemetry-collector/Dockerfile.dhi -t ew-telemetry-dhi telemetry-collector
```

Use Docker's normal authentication. Do not copy Docker's unencrypted credential
configuration into source, build contexts, build arguments or CI logs. CI would
need separately managed read-only registry credentials; none are configured by
this change. Dependabot excludes these optional Dockerfiles until authenticated
registry access is configured, so refresh and review their pinned digests manually.

Both builder and runtime use pinned DHI Python 3.11 Debian 13 images. The runtime
has no shell or package manager. All four amd64 images build locally; the base
manifests offer arm64 but those optional builds are not yet runtime-validated.
Native dependency import checks passed for smartbox (including NumPy,
scikit-learn, Lua, cryptography and psycopg), webdashboard and ewapp. The final
telemetry image's isolated `/api/stats` smoke test passed. Full application
startup and deployment-volume compatibility remain unverified for the other
optional images.
The prototypes explicitly retain UID 0 to preserve existing root-owned volumes;
they do not provide a nonroot migration. The shell/PostgreSQL all-in-one startup
is deliberately retained on its current base until a compatible design is tested.

DHI backports need signed VEX evidence before interpreting raw version matches.
The runtime raw Grype report has 180 matches; none has been broadly suppressed.
Docker Scout's verified VEX retrieval requires a Docker Hub login in addition to
the working dhi.io authentication and remains pending. DHI is not selected by
the release workflow until VEX, startup, volume and architecture validation is
complete. These optional builds are an evaluation, not a security certification.

## Primary references

- [CISA KEV catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)
- [Grype documentation](https://oss.anchore.com/docs/guides/vulnerability/)
- [pip-audit](https://github.com/pypa/pip-audit)
- [Docker Hardened Images](https://docs.docker.com/dhi/)
- [DHI vulnerability scanning and VEX](https://docs.docker.com/dhi/how-to/scan/)
- [Go supported releases](https://go.dev/dl/)
