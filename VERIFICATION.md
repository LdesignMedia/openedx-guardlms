# Open edX verification

Local acceptance run: **9 November 2026**, macOS/ARM64, isolated Docker deployment.
The source receiver/dashboard is the coordinated
[GuardLMS feature branch](https://github.com/LdesignMedia/guardlms/tree/feature-openedx-connector).
This standalone connector is version **0.1.0 (alpha)**. No production deployment or package publication
is implied. Deploy receiver support before installing the connector in production.

## Exact baseline and artifacts

| Item | Tested value |
| --- | --- |
| Tutor | 22.0.4 |
| tutor-mfe | 22.1.2 |
| Open edX | `release/verawood.2` |
| Python / Django inside Open edX | 3.12.13 / 5.2.13, aarch64 |
| Docker daemon | 29.8.2 |
| MySQL / MongoDB / Redis images | 8.4.11 / 7.0.39 / 7.4.10 |
| GuardLMS test PHP | 8.4.27 |
| Host Node / Chrome | 22.19.0 / 157.0.8103.38 |

The Tutor/MFE pairing follows the
[Tutor 22.0.4 release](https://github.com/overhangio/tutor/releases/tag/v22.0.4).
The official Open edX base is pinned by registry digest; locally built images
have immutable local image IDs rather than published registry digests:

```text
Official overhangio/openedx:22.0.4 registry digest:
sha256:c8d9dff16436564ae59c19c954140d867e3718cbacc4f5112f314796d7a2e510
Final guardlms-openedx:local image ID:
sha256:e9ff9ca7f38a9442c175c5f77718149353bd6f18ed670b57ac7a5d4fd0bb0ad2
Final guardlms-openedx-mfe:local image ID:
sha256:346bc6ac458bef6ad24fc839a11de4b6d772a9eb33e40744a368fd281c7ab3e2
GuardLMS backend test-base image ID:
sha256:3ea3ed429a4a00a07666af1c958584ef8d115e34ab7d8eda7d926574c2ada1f5
openedx_guardlms-0.1.0-py3-none-any.whl SHA256:
af9b66c4297d641dd470d6d284cc8ed8c3c756d3a0f9c1208e5563bf30eaa5b1
Combined MFE dependency manifest SHA256:
5ab487916c3f173e3e9406ef5d561e95f15d4b5d180d198ca13ad2be91733182
```

All **13** production MFE build stages compiled successfully: site (frontend-base),
catalog, profile, ora-grading, learning, learner-dashboard, gradebook, discussions,
communications, account, authoring, authn and admin-console. Their exact resolved
build manifests yielded **3,108** unique npm name/version pairs. Production use
wins over a development-only flag when combining duplicate package coordinates.
The receiver persisted **3,703** software components/dependencies from the real
Open edX installation. Django app/XBlock identities remain separate from PyPI
package coordinates and represent installation, not course usage.

## Real runtime coverage

Run the harness from the GuardLMS checkout. The repeatable acceptance command is `./integrations/openedx/docker/test.sh verify`.
It completed successfully with exit code **0** on the final image; all runtime
checks below passed. It executes `browser-test.cjs`, `receiver-runtime.py` and
`dashboard-test.cjs` in sequence. See the harness [README](https://github.com/LdesignMedia/guardlms/blob/feature-openedx-connector/integrations/openedx/README.md) for setup, stop and cleanup.

| Area | Checks |
| --- | --- |
| Authentication / consent | Native Open edX Authn login; native superuser settings; actual GuardLMS dashboard sign-in and consent; callback, HTTPS exchange and persisted first inventory; anonymous and authenticated learner denial; CSRF refusal; callback replay refusal |
| Connection lifecycle | Encrypted MySQL state; service restart preserves credentials, preferences and session; disconnect while a real consent is pending refuses the returning callback; fresh reconnect replaces inventory/SDK credentials |
| Delivery | Dedicated Celery Beat and native LMS worker deliver a due report; HTTP refusal retains encrypted credentials and first-refusal time; recovery clears refusal; real MySQL locking serializes simultaneous due pushes |
| Inventory | Real Python/Django/plugin/package/runtime metadata and build npm inventory; wrong-site, incomplete and stale snapshots refused; transient component removal; separate scanner-observation fixture preserved |
| Security | Real derived DEBUG and permissive CORS findings created, then resolved by later complete healthy evidence; unavailable checks remain unknown |
| Errors | Uncaught browser errors on native LMS and Studio plus bundled MFEs; Django ValueError, actual SQL ProgrammingError and Celery RuntimeError; new occurrence counts prove fresh delivery and deduplication; exception values/SQL/secret sentinels absent from diagnostics; server errors remain off before opt-in |
| Analytics | Off initially; eligible-plan opt-in; actual MFE events delivered; SPA history navigation retains one SDK session/loader; ineligible-plan configuration suppresses analytics |
| Credentials / transport | Actual expired inventory key refused and recovered; actual SDK key revoked, ingest refused and replacement recovered; actual connector rejects the disposable certificate without its CA bundle |
| Dashboard | Real monitoring tab renders the received browser, Django, Celery and SQL reports with Python/SQL labels and redacted messages |

Browser page coverage:

- `openedx.local.overhang.io/login` → bundled Authn login and native LMS session.
- `openedx.local.overhang.io/guardlms/`, preview, callback and mutation endpoints.
- `openedx.local.overhang.io/admin/` — native LMS bootstrap and error delivery.
- `studio.openedx.local.overhang.io/admin/` — native Studio bootstrap and error delivery.
- LMS `/dashboard` → MFE `/learner-dashboard/` — actual error delivery.
- Studio `/home/` → MFE `/authoring/home` — actual error delivery.
- MFE `/account` — actual error and analytics delivery, SPA navigation.
- MFE `/instructor-dashboard/` — frontend-base loader and error delivery on its
  no-course/404 view. No course or learner records were created for this route.
- GuardLMS sign-in, Open edX consent, website overview and real-time errors tab.

The remaining bundled MFEs were compiled with the same supported external-script
hook and included in dependency inventory; their individual course-specific
workflows were not exercised. Custom MFEs, older releases, Kubernetes and other
CPU architectures require their own compatibility verification.

## Automated checks

| Command / scope | Result |
| --- | --- |
| Connector `pytest -q` in pinned Python 3.12.13 / Django 5.2.13 image | 31 passed |
| Connector `pytest -q` in host tools environment (Python 3.15 / Django 5.2.19) | 31 passed |
| `DJANGO_SETTINGS_MODULE=tests.settings python -m django makemigrations --check --dry-run` | No changes detected |
| `python -m build --wheel` | Built successfully; compiled Dutch translations included |
| `test.sh backend-tests` | 940 tests, 3,677 assertions passed; 78 existing PHPUnit deprecation notices |
| Frontend Vitest: connect callback, consent page, connector catalog, error card | 51 passed |
| Frontend `npm run typecheck` and ESLint on changed TS/TSX | Passed |
| SDK `npm test -- --runInBand` | 326 passed across 8 suites |
| Marketing `npm test` including EN/NL checks | 225 passed |
| PHP Pint on changed PHP files; `git diff --check` | Passed |

The backend filter includes all existing external-push/connect suites, SDK key
and origin validation, lockfile/OSV matching, error processing and platform detail
regressions. Deterministic OSV fixtures cover both npm and PyPI advisories, PyPI
normalization, advisory hydration and outage/incomplete-result preservation.
Connector tests additionally cover expired/session-bound callback state, wrong
callback host, generation races, retry/backoff, telemetry recursion suppression,
redaction, corrupt credentials, disabled options and Dutch monitoring controls.

## Isolation and interpretation

Docker access was obtained for actual execution; mocks alone were not used for
acceptance. The harness owns the `guardlms-openedx` Compose project, separate
MySQL/Mongo/Redis/receiver storage and loopback HTTPS endpoints. Persistent state
and the encryption key survive service restarts. Test CA trust is mounted only
inside this stack. Playwright ignores the disposable certificate only in its test
browser; the connector uses normal certificate validation, tested negatively.

The receiver-only harness provider simulates public DNS for exactly the local LMS
because production SSRF checks correctly refuse loopback/private addresses. It
suppresses scanner/ownership jobs; no production probes or pentest quota are used.
Actual consent, exchange, authentication, inventory and SDK ingestion remain real.
The isolated SQLite receiver executes error jobs synchronously; Open edX uses real
asynchronous Celery. The test receiver raises its scan throttle to 1,000/hour and its SDK-refresh
throttle to 1,000/minute for repeated forced reports; production limits are unchanged. The scanner row in
the preservation test is a deterministic observation fixture, not a network scan.

The SDK normally excludes automated clients from analytics. The test explicitly
opts in its own client after asserting that exclusion, without changing production
SDK defaults. Controlled exception endpoints and Celery task live only in this
harness and are absent from the connector wheel.

Live external advisory services are disabled in the disposable receiver. Matching
uses deterministic fixtures in the backend tests. OSV failures or paginated partial
results preserve existing alerts and cannot establish a clean result. Update and
advisory coverage for unmapped plugin identities remains unknown; no latest-version
catalog is invented for Open edX plugins.

Raw logs, screenshots and disposable configuration remain under
`/tmp/guardlms-openedx/evidence` on the test host. Generated private configuration
and initialization logs can contain disposable deployment secrets and are not
committed. The reviewed source, commands, exact artifact identities and results
above are the portable verification record.
