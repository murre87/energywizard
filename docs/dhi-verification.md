# DHI verification — 2026-11-11

Follow-up to [#273](https://github.com/murre87/energywizard/issues/273).
The [machine-readable evidence](dhi-verification-evidence.json) records pinned
image/platform digests, public-key and VEX hashes, local image IDs and scan dates.
These checks qualify the optional builds; they do not select DHI for deployment.

## GitHub Actions

The `dhi-verification` workflow uses the Actions secret `DHI_IO` and repository
variable `DHI_USERNAME`. A free Docker account with a read-public-only PAT is
sufficient; no paid organization token is required. The PAT is supplied only to
the pinned Docker login action, never build arguments, application containers or
artifacts. Both `dhi.io` and Docker Hub login are used because Scout also needs
Hub authentication. Replace the secret and username variable when moving to a
separate CI account; do not put the token in source or chat.

Run manually or through a same-repository PR changing the DHI inputs. Fork PRs
are excluded from credential-bearing jobs, and `pull_request_target` is not used.
The workflow verifies the base signatures first, then runs the existing isolated
probe on native AMD64 and ARM64 runners. Only the public verification documents
and synthetic runtime reports/logs are uploaded, with 14-day retention. Missing
or invalid credentials fail the workflow. This workflow does not publish images
or replace the standard-image release security gates.

## Signed VEX

Scout 1.29.0 verified the pinned Python 3.11 builder/runtime attestations against
a saved copy of Docker's HTTPS-published signing key. All VEX statements were
checked for the selected platform digest. The key's SHA256 is
`1d02bbccf149283ae6288d96264dcad3fb23ee1911d90324a48eab28e4cb8a5f`.

| Base | Platform | Signature result | Public transparency log |
| --- | --- | --- | --- |
| Builder | amd64 | Docker key verified | Entry missing |
| Builder | arm64 | Docker key verified | Entry missing |
| Runtime | amd64 | Docker key verified | Entry missing |
| Runtime | arm64 | Docker key verified | Verified |

For the three missing entries, verification used Docker's documented
[key-only method](https://docs.docker.com/dhi/how-to/verify/#handle-missing-transparency-log-entries).
This verifies the signature without proving public-log inclusion. The helper
tries full verification first and permits that fallback only for the specific
missing-log-entry error. Authentication, network and signature failures do not
trigger it. Both attempt logs and the verification mode are retained.

Each runtime document contains 184 `not_affected` statements and two
`under_investigation` statements: CVE-2025-12781 and CVE-2026-3446. Each builder
document has 1,010 `not_affected` and 16 `under_investigation` statements covering
five distinct CVEs. Investigations are retained, never treated as unaffected.

Reproduce using normal Docker authentication; no credential files are read or
mounted by the verification scripts:

```sh
python3 scripts/verify_dhi_vex.py --scout /path/to/docker-scout --output /tmp/ew-dhi-vex
python3 scripts/verify_dhi_runtime.py --output /tmp/ew-dhi-runtime/amd64.json
```

## AMD64 application and volume checks

All four actual optional images built and passed isolated checks. The engine
completed database bootstrap and reached its unconfigured installation-wait
state. Dashboard and mobile passed owner login and authenticated health requests;
telemetry passed its stats endpoint. Synthetic root-owned mode-0600 files could
be read/written, and application settings updates succeeded. Existing UID 0 is
preserved; this does not validate a nonroot migration.

The probe uses a disposable PostgreSQL 17 instance on an internal network with
no published ports, synthetic settings and no HA/device configuration. The UI
probe forwards its synthetic secure session cookie as the TLS-terminating proxy
would. Authentication and cookie safeguards in the application are unchanged.
Containers, networks and synthetic volumes were removed after the checks. The
four `ew-dhi-verify-*-amd64` image tags remain until scanning is complete; remove
only those evaluation tags after use.

## Actual installed packages and VEX-aware scans

All four installed-Python inventories passed pip-audit 2.10.1 with no known
advisories. Digest-pinned Grype 0.121.3 used its November 11 database and the
verified AMD64 runtime VEX. Each final image had 150 VEX-ignored matches and 30
remaining matches across five OpenSSL CVEs:

- CVE-2026-107496
- CVE-2026-88822
- CVE-2026-88823
- CVE-2026-95691
- CVE-2026-95692

The [November 10 OpenSSL advisory](https://openssl-library.org/news/secadv/20261110.txt)
rates these five Low and schedules releases containing their fixes for December
1. Grype reports no available Debian fixes; no newer DHI tag digest was available
at review time. These matches are retained, without a reachability exemption or
blanket suppression. Comparison with the November 10 CISA feed (1,779 entries)
found no matching KEVs and no findings blocked by the existing image policy.
That policy result does not mean CVE-free or establish non-exploitability.

## Remaining adoption limits

ARM64 base manifests and signatures are verified, but ARM64 application execution
is not: this local Docker host lacks ARM64 emulation and returned an exec-format
error. No privileged emulator registration or host reconfiguration was performed.
Use a native ARM64 test host, or an already emulation-capable host, with the
probe's `--platform linux/arm64` option before adoption.

Configured engine/device behavior, real deployment volumes, nonroot ownership
migration and all-in-one shell/PostgreSQL compatibility remain outside these
isolated checks. Production images, release gates and deployments are unchanged.
