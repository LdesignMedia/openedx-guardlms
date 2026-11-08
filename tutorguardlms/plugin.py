"""Tutor 22 integration, using deployment/settings/image patches only."""
import base64
import json
import secrets
from pathlib import Path
from tutor import hooks
from tutormfe.hooks import EXTERNAL_SCRIPTS

hooks.Filters.CONFIG_DEFAULTS.add_items([
    ("GUARDLMS_API_URL", "https://api.guardlms.com"),
    ("GUARDLMS_DASHBOARD_URL", "https://dashboard.guardlms.com"),
    ("GUARDLMS_PACKAGE", "openedx-guardlms==0.1.0"),
    ("GUARDLMS_USE_LOCAL_WHEEL", False),
])
hooks.Filters.CONFIG_UNIQUE.add_items([("GUARDLMS_ENCRYPTION_KEY", secrets.token_urlsafe(32) + "=")])
settings_patch = '''
GUARDLMS_SITE_URL = "https://{{ LMS_HOST }}"
GUARDLMS_STUDIO_SETTINGS_MODULE = "cms.envs.tutor.production"
GUARDLMS_API_URL = {{ GUARDLMS_API_URL | tojson }}
GUARDLMS_DASHBOARD_URL = {{ GUARDLMS_DASHBOARD_URL | tojson }}
GUARDLMS_ENCRYPTION_KEY = {{ GUARDLMS_ENCRYPTION_KEY | tojson }}
GUARDLMS_OPENEDX_VERSION = {{ EDX_PLATFORM_VERSION | tojson }}
GUARDLMS_BROWSER_ORIGINS = ["https://{{ CMS_HOST }}", "https://{{ MFE_HOST }}"]
'''
hooks.Filters.ENV_PATCHES.add_items([
    ("openedx-lms-production-settings", settings_patch),
    ("openedx-cms-production-settings", settings_patch),
    ("openedx-dockerfile-post-python-requirements", '''{% if GUARDLMS_USE_LOCAL_WHEEL %}
COPY guardlms/*.whl /tmp/guardlms-wheel/
RUN pip install --no-deps /tmp/guardlms-wheel/*.whl
{% else %}
RUN pip install {{ GUARDLMS_PACKAGE }}
{% endif %}'''),
])
# Tutor's external-script hook takes a loader class, not a script-tag descriptor.
loader = r'''class GuardLMSExternalScript {
  loadScript() {
    return new Promise((resolve) => {
      if (document.querySelector('script[data-guardlms-bootstrap]')) { resolve(); return; }
      const script = document.createElement('script');
      script.src = "https://{{ LMS_HOST }}/guardlms/bootstrap.js";
      script.dataset.guardlmsBootstrap = 'true';
      script.onload = () => resolve();
      script.onerror = () => resolve();
      document.head.appendChild(script);
    });
  }
}'''
hooks.Filters.ENV_PATCHES.add_items([
    ("mfe-env-config-buildtime-definitions", loader),
    ("mfe-site-custom-app-definitions", loader.replace("new Promise(", "new Promise<void>(")),
])
EXTERNAL_SCRIPTS.add_item(("all", "GuardLMSExternalScript"))

# Build-time manifests contain resolved names/versions only, never lockfile URLs.
manifest_js = r'''
const fs = require('fs');
const lock = JSON.parse(fs.readFileSync('package-lock.json', 'utf8'));
if (!lock.packages) throw new Error('A package-lock v2/v3 resolved package inventory is required');
const found = new Map();
for (const [location, pkg] of Object.entries(lock.packages)) {
  if (!location || !pkg.version || pkg.link) continue;
  const name = pkg.name || location.split('node_modules/').pop();
  if (!name || !/^[a-zA-Z0-9@][a-zA-Z0-9@._\/-]*$/.test(name)) throw new Error('Invalid package identity');
  const item = {name, version: pkg.version, dev: !!pkg.dev};
  const key = `${name}@${pkg.version}`;
  if (found.has(key)) item.dev = item.dev && found.get(key).dev;
  found.set(key, item);
}
fs.mkdirSync('dist', {recursive: true});
fs.writeFileSync('dist/guardlms-npm.json', JSON.stringify([...found.values()]));
'''
encoded = base64.b64encode(manifest_js.encode()).decode()
manifest_run = f"RUN echo '{encoded}' | base64 -d > /tmp/guardlms-manifest.cjs && node /tmp/guardlms-manifest.cjs"
hooks.Filters.ENV_PATCHES.add_items([
    ("mfe-dockerfile-post-npm-build", manifest_run),
    ("mfe-dockerfile-post-npm-build-site", manifest_run),
])
# Manifests are available as static assets alongside the exact MFE build.
# The harness/install guide mounts their combined, validated union into LMS/Studio.

@hooks.Filters.COMPOSE_MOUNTS.add()
def mount_manifest(mounts, basename):
    if basename == "guardlms-inventory":
        mounts += [(service, "/openedx/guardlms") for service in ("lms", "cms", "lms-worker", "cms-worker", "lms-job", "cms-job")]
    return mounts

hooks.Filters.CLI_DO_INIT_TASKS.add_item(("lms", "./manage.py lms migrate guardlms_openedx --noinput"))
hooks.Filters.ENV_PATCHES.add_item(("local-docker-compose-services", '''
guardlms-scheduler:
  image: {{ DOCKER_IMAGE_OPENEDX }}
  restart: unless-stopped
  environment:
    DJANGO_SETTINGS_MODULE: lms.envs.tutor.production
    SERVICE_VARIANT: lms
  command: ["python", "-m", "guardlms_openedx.scheduler"]
  volumes:
    - ../apps/openedx/settings/lms:/openedx/edx-platform/lms/envs/tutor:ro
    - ../apps/openedx/settings/cms:/openedx/edx-platform/cms/envs/tutor:ro
    - ../apps/openedx/config:/openedx/config:ro
    {% for mount in iter_mounts(MOUNTS, "openedx", "lms") %}
    - {{ mount }}:ro
    {% endfor %}
  depends_on: [lms]
'''))
