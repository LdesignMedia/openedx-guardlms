# GuardLMS for Open edX

Connect self-hosted Open edX to GuardLMS for daily software inventory, security
configuration checks, browser errors, and optional Python/SQL errors and analytics.
This alpha targets **Tutor 22.0.4, tutor-mfe 22.1.2, Open edX Verawood.2,
Python 3.12 and Django 5.2**. Consult VERIFICATION.md for actual test results.
Other releases and custom MFEs are not a tested support matrix.

## Features and defaults

- Connect, reconnect and disconnect through native LMS superuser controls.
  No inventory API key needs to be copied from GuardLMS.
- Complete daily installed Django app/XBlock and Python/npm dependency inventories,
  runtime metadata, payload preview and manual push. Installation is not course usage.
- Derived security checks for Django deployment settings, DEBUG, HTTPS, secure
  session/CSRF cookies, allowed hosts, CORS and CSRF trusted origins. Checks reflect
  both LMS and Studio; unavailable Studio evidence remains unknown.
- Browser errors are **enabled after connecting**, across Django LMS/Studio pages
  and bundled MFEs. Browser SDK loading respects your CSP.
- Python and SQL error reporting is a **separate opt-in, off by default**.
  Reports contain exception class and filename/line/function frames, never the
  exception value, SQL text/parameters, source lines, locals or request bodies.
- Page views and scroll-depth analytics are **off by default**, require an eligible
  GuardLMS plan, and use the existing GuardLMS SDK.

## Install from source

Requires Docker Compose, server access, outbound HTTPS, and a GuardLMS account.
Deploy GuardLMS receiver support before enabling this connector. Build a wheel
from the exact connector revision you intend to install:

```sh
python -m pip install build
python -m build --wheel
# In the same virtual environment as the pinned Tutor installation:
python -m pip install '.[tutor]'  # Pins Tutor 22.0.4 and tutor-mfe 22.1.2
tutor plugins enable guardlms mfe
tutor config save --set GUARDLMS_USE_LOCAL_WHEEL=true
mkdir -p "$(tutor config printroot)/env/build/openedx/guardlms"
cp dist/openedx_guardlms-*.whl "$(tutor config printroot)/env/build/openedx/guardlms/"
tutor images build openedx
tutor images build mfe
```

The Tutor plugin creates and persists an independent encryption key in Tutor's
private config. Preserve `GUARDLMS_ENCRYPTION_KEY` and the shared database during
upgrades. LMS, Studio and workers must use the same key. Do not commit Tutor
configuration, private keys, database dumps or inventory credentials.

For a published wheel or package, `GUARDLMS_USE_LOCAL_WHEEL=false` and
`GUARDLMS_PACKAGE` can instead select its pinned package requirement. No PyPI
publication is implied by this source repository.

### Export the exact MFE dependency inventory

The plugin adds a names/versions-only manifest to each built MFE. Export and
combine those manifests from the exact image you deploy:

```sh
mkdir -p /persistent/guardlms-inventory
IMAGE="$(tutor config printvalue MFE_DOCKER_IMAGE)"
docker run --rm --entrypoint sh "$IMAGE" \
  -c 'find /openedx/dist -name guardlms-npm.json | tar -czf - -T -' \
  > /tmp/guardlms-mfe-manifests.tar.gz
python -m tutorguardlms.manifest /tmp/guardlms-mfe-manifests.tar.gz \
  /persistent/guardlms-inventory/npm-inventory.json
tutor mounts add /persistent/guardlms-inventory
tutor config save
tutor local launch
```

`tutor config save` may regenerate the build directory: copy your wheel again
before rebuilding Open edX. Regenerate the manifest after every MFE upgrade;
missing or oversized inventories fail reporting instead of erasing previous data.
The manifest directory is mounted into LMS, Studio, jobs and workers; it contains
software metadata, not credentials. The `guardlms-scheduler` service has its own
Celery Beat schedule and queues reports to the native LMS worker. Keep both running.
For Kubernetes, provide the equivalent shared manifest mount and run
`python -m guardlms_openedx.scheduler` in a single scheduler workload; Kubernetes
installation has not been runtime-tested in this release.

### Connect

1. Sign in to the canonical LMS as an active superuser and open `/guardlms/`.
2. Click **Connect to GuardLMS**, sign in or register, and approve the site.
3. Return to Open edX and confirm the first accepted inventory. Complete DNS or
   HTML ownership verification in GuardLMS if server-based proof is unavailable.
4. Review monitoring preferences. Browser errors start when the connected site's
   GuardLMS subscription and monitoring configuration permit them.

The browser receives only a browser SDK credential. The website-bound inventory
credential is exchanged server-to-server and stored encrypted using Fernet.
Administrators can inspect health, last accepted inventory, next attempt, component
count, key expiry and first refusal. A failed initial push retains a successful
connection and retries. HTTP 401/403 or an expired key requires reconnecting.
Network/5xx failures retain credentials and use exponential backoff up to an hour.

## Configuration and data sharing

Tutor supplies the canonical HTTPS LMS origin, Studio/MFE origins, platform build
revision, and encryption key. Advanced deployments can override Django settings:

- `GUARDLMS_SITE_URL`: canonical LMS HTTPS origin, without a path/query/fragment.
- `GUARDLMS_API_URL` and `GUARDLMS_DASHBOARD_URL`: canonical HTTPS service origins.
- `GUARDLMS_BROWSER_ORIGINS`: explicit HTTPS Studio and MFE origins, including ports.
- `GUARDLMS_MFE_MANIFEST`: complete combined build-manifest file.
- `GUARDLMS_STUDIO_SETTINGS_MODULE`: CMS production settings evaluated in an
  isolated subprocess with a 90-second deadline; Tutor configures this automatically.

All HTTP requests validate certificates/hostnames, refuse redirects carrying
credentials, have deadlines and enforce a response-size limit. Use your normal CA
trust configuration (`REQUESTS_CA_BUNDLE` for an organizational CA); never disable
verification. Add the LMS bootstrap and GuardLMS SDK/API origins to your CSP as
needed. The plugin does not relax CSP or use wildcard CORS. Public browser config
contains only browser credentials/options, has `no-store`, and accepts configured
origins. Open tabs refresh it every minute and stop monitoring after disconnect.

Inventory excludes user, course, grade, membership and enrollment records. Raw
Django settings, credentials, database DSNs and package download URLs stay local.
Unknown versions, advisory availability and update status are not evidence of a
clean or current installation. Python and npm advisory matching requires OSV to
be enabled in GuardLMS; this connector does not invent an Open edX plugin catalog.
Optional browser monitoring/analytics sends page URLs and diagnostic context;
review your site's disclosure/consent requirements before enabling analytics.

## Upgrade and uninstall

Back up the shared database and original Tutor encryption key; deploy the receiver
first, then rebuild both images, export the matching manifest, and run
`tutor local launch` to apply connector migrations. Credentials and preferences
persist in the database. A staging clone must reconnect to its own GuardLMS site;
canonical URL mismatches suppress reporting and browser configuration.

To uninstall, disconnect through the superuser page, revoke the site's old keys in
GuardLMS if required, disable the Tutor plugin, and rebuild/redeploy images without
the package. Disconnect clears local credentials and stops reporting; it does not
delete the GuardLMS website. Do not drop the connector table until you no longer
need its preferences/history. Keep the original encryption key for any backup
that still contains encrypted credentials.

## Development

```sh
python -m pip install -e '.[test,tutor]'
pytest -q
DJANGO_SETTINGS_MODULE=tests.settings python -m django makemigrations --check --dry-run
python -m build
```

Real runtime verification uses the GuardLMS `integrations/openedx/docker` harness,
a real Tutor deployment and isolated GuardLMS receiver/dashboard. Unit tests are
not a substitute for that report. License: GPL-3.0-or-later.
