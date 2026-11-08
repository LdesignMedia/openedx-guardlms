"""Allowlisted installed-software inventory; no user/course queries or config dumps."""
import json
import platform
import os
import subprocess
import sys
import re
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit
import django
from django.apps import apps
from django.conf import settings
from django.core import checks
from django.db import connection
from django.utils import timezone
from .transport import site_url

MAX_ITEMS = 2000


def normalized_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def security_checks():
    def verdict(safe):
        return "ok" if safe else "warning"
    cors_all = getattr(settings, "CORS_ALLOW_ALL_ORIGINS", getattr(settings, "CORS_ORIGIN_ALLOW_ALL", False))
    cors_origins = getattr(settings, "CORS_ALLOWED_ORIGINS", getattr(settings, "CORS_ORIGIN_WHITELIST", []))
    cors_regexes = getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", getattr(settings, "CORS_ORIGIN_REGEX_WHITELIST", []))
    cors = verdict(not cors_all and all(v.startswith("https://") and "*" not in v for v in cors_origins))
    if cors_regexes and cors != "warning":
        # Arbitrary regular expressions cannot establish explicit-origin safety.
        cors = "warning" if any(v in (".*", "^.*$", ".+") for v in cors_regexes) else "unknown"
    result = {
        "debug": verdict(not settings.DEBUG),
        "https": verdict(bool(getattr(settings, "SECURE_SSL_REDIRECT", False)) or urlsplit(getattr(settings, "LMS_ROOT_URL", "")).scheme == "https"),
        "session_cookie": verdict(bool(settings.SESSION_COOKIE_SECURE)),
        "csrf_cookie": verdict(bool(settings.CSRF_COOKIE_SECURE)),
        "allowed_hosts": verdict(bool(settings.ALLOWED_HOSTS) and "*" not in settings.ALLOWED_HOSTS),
        "cors": cors,
        "csrf_origins": verdict(all(v.startswith("https://") and "*" not in v for v in getattr(settings, "CSRF_TRUSTED_ORIGINS", []))),
    }
    try:
        failures = checks.run_checks(tags=[checks.Tags.security], include_deployment_checks=True)
        result["deployment"] = verdict(not any(c.level >= checks.WARNING for c in failures))
    except Exception:
        result["deployment"] = "unknown"
    return result


def deployment_security_checks():
    """A warning in either service wins; missing CMS evidence remains unknown."""
    local = security_checks()
    module = getattr(settings, "GUARDLMS_STUDIO_SETTINGS_MODULE", "")
    if not module:
        return local
    studio = {}
    try:
        env = dict(os.environ, DJANGO_SETTINGS_MODULE=module, SERVICE_VARIANT="cms")
        result = subprocess.run([sys.executable, "-m", "guardlms_openedx.security_report"],
                                env=env, capture_output=True, text=True, timeout=90, check=True)
        for line in result.stdout.splitlines():
            if line.startswith("GUARDLMS_CHECKS="):
                studio = json.loads(line.split("=", 1)[1])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return {key: ("warning" if "warning" in (value, studio.get(key)) else
                  "ok" if value == studio.get(key) == "ok" else "unknown")
            for key, value in local.items()}


def npm_dependencies():
    manifest = Path(settings.GUARDLMS_MFE_MANIFEST)
    # Missing is not the same as a complete empty dependency set.
    if not manifest.is_file() or manifest.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("MFE build inventory is missing or oversized")
    value = json.loads(manifest.read_text())
    if not isinstance(value, list):
        raise RuntimeError("Invalid MFE build inventory")
    output = []
    for item in value:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not isinstance(item.get("version"), str)):
            raise RuntimeError("Incomplete MFE build inventory")
        output.append({"ecosystem": "npm", "name": item["name"], "version": item["version"], "dev": bool(item.get("dev", False))})
    return output


def collect():
    packages = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name and dist.version:
            packages[normalized_name(name)] = dist.version
    owners = metadata.packages_distributions()
    plugins = []
    for app in apps.get_app_configs():
        versions = {packages.get(normalized_name(name)) for name in owners.get(app.name.split(".")[0], [])}
        versions.discard(None)
        plugins.append({"id": "django:" + app.name, "kind": "django", "version": next(iter(versions)) if len(versions) == 1 else None, "enabled": True})
    for ep in metadata.entry_points(group="xblock.v1"):
        plugins.append({"id": "xblock:" + ep.name, "kind": "xblock", "version": ep.dist.version if ep.dist else None, "enabled": True})
    plugins = list({p["id"].lower(): p for p in plugins}.values())
    deps = [{"ecosystem": "pypi", "name": name, "version": version, "dev": False} for name, version in sorted(packages.items())]
    deps += npm_dependencies()
    deps = list({(p["ecosystem"], p["name"], p["version"]): p for p in deps}.values())
    if len(plugins) > MAX_ITEMS or len(deps) > 10000:
        raise RuntimeError("Complete inventory exceeds receiver limits")
    for item in plugins:
        if len(item["id"]) > 120:
            raise RuntimeError("Plugin identifier exceeds receiver limits")
    # Tutor supplies the exact edx-platform revision used to build the image.
    release = getattr(settings, "GUARDLMS_OPENEDX_VERSION", None)
    payload = {
        "siteurl": site_url(), "generatedtime": int(timezone.now().timestamp()),
        "openedx": {"version": release, "plugins": plugins},
        "python": {"version": platform.python_version()}, "django": {"version": django.get_version()},
        "dependencies": deps, "security_checks": deployment_security_checks(),
        "server": {"os_family": platform.system(), "arch": platform.machine()},
    }
    try:
        os_release = platform.freedesktop_os_release()
        for key, field in (("NAME", "os_name"), ("ID", "os_id"), ("VERSION_ID", "os_version"), ("PRETTY_NAME", "os_pretty")):
            if os_release.get(key):
                payload["server"][field] = os_release[key]
    except OSError:
        pass
    if connection.vendor == "mysql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = str(cursor.fetchone()[0])
        payload["database"] = {"name": "MariaDB" if "mariadb" in version.lower() else "MySQL", "version": version}
    elif connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            version = str(cursor.fetchone()[0])
        payload["database"] = {"name": "PostgreSQL", "version": version}
    elif connection.vendor == "sqlite":
        import sqlite3
        payload["database"] = {"name": "SQLite", "version": sqlite3.sqlite_version}
    return payload
