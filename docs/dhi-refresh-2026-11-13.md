# DHI candidate refresh — 2026-11-13

Follow-up to #273. Registry metadata now resolves the existing Python 3.11 tags
to new immutable image indexes. The four optional `Dockerfile.dhi` files use
the same updated builder/runtime pair; default Dockerfiles are unchanged.

## Qualification results

[Run 43363817998](https://github.com/murre87/energywizard/actions/runs/43363817998)
passed all three jobs for commit `c32f8b3`: signatures plus native AMD64/ARM64
startup, authenticated UI health, dependency integrity (`pip check`), settings
and synthetic root-owned volumes for all four services. The subsequent evidence
commit changes documentation only; the qualified Dockerfile inputs are identical.
The [machine-readable report](dhi-refresh-evidence-2026-11-13.json) retains exact
CI/artifact identifiers, platform manifests, VEX hashes and eight service results.

All four signed-VEX documents required the existing narrow fallback for an exact
missing-public-log-entry error: Docker-key verification succeeded, but public
transparency-log inclusion was not established. Each builder document contains
1,016 `not_affected` and 16 `under_investigation` statements across five distinct
investigated CVEs. Each runtime document contains 190 `not_affected` and two
`under_investigation` statements. Investigations remain unresolved, not exempted.
This run did not repeat a full-image vulnerability audit; it does not establish
resolution of the earlier OpenSSL findings or qualify production adoption.

## Immutable candidates

| Base | Index digest | amd64 manifest | arm64 manifest |
| --- | --- | --- | --- |
| `dhi.io/python:3.11-debian13-dev` | `5718cc9f67bccbb0b54c9badc50988b8617292aa4e730d38854d1b81cdb9121a` | `e8cf20fd5706b0074173be2bf97b51e2dee3d551072fbda29ae7538eaf932253` | `765a0d54bc2114057aaa3f8776847e1c8fe820c967ebbc1cd3d050854d605c5e` |
| `dhi.io/python:3.11-debian13` | `1bb857892e25f7df5c34a6bd5f8695a450e85c8ab8511c02f98ad9282943435e` | `b09f7c3e5be003ad27b5749b3dd0138e9c1bb22c41c10a302c708092575f22cc` | `7b961d13820ffb234f15944bcf9ebbfd6f07dbdd433981343ae72893deb4da39` |

All digests above are SHA256. Metadata was read through Docker's existing
authentication; no authentication files or token values were read or copied.

Qualification uses the existing DHI workflow: Docker-signed VEX verification
for both bases/platforms, followed by native AMD64/ARM64 startup, dependency
integrity and synthetic root-owned-volume checks for all four services.
The read-only CI credentials and fork guard are unchanged.

The [previous evidence](dhi-verification-evidence.json) remains a historical
record of the older pins; it must not be attributed to these new digests.
New signature/runtime results and any new vulnerability assessment must be
recorded separately, as above. A tag change alone does not establish resolution of the
five previously recorded OpenSSL findings. No default-image adoption,
publishing, deployment or vulnerability-gate exemption is included.
