import uuid
from contextlib import contextmanager
from datetime import timedelta
from celery import shared_task
from cryptography.fernet import InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Connection
from .state import decrypt, encrypt
from .transport import DeliveryError, send, site_url


@contextmanager
def report_lock():
    # Held under a SQL row lock for the entire operation: safe across LMS/Studio/workers.
    # MySQL/PostgreSQL release this lock on process death; no lease can expire mid-report.
    with transaction.atomic():
        connection = Connection.objects.select_for_update().get(pk=Connection.current().pk)
        yield connection


def refresh_sdk(credentials):
    """Authorize all configured browser origins independently of inventory delivery."""
    previous = credentials.get("sdk") or {}
    payload = {"siteurl": site_url(), "platform": "openedx", "origins": settings.GUARDLMS_BROWSER_ORIGINS,
               "action": "fetch" if previous.get("key") else "rotate"}
    sdk = send("/api/integrations/sdk-key", payload, credentials["token"])["data"]
    if (not sdk.get("key") and sdk.get("key_prefix") and previous.get("key")
            and sdk["key_prefix"] != previous["key"][:8]):
        sdk = send("/api/integrations/sdk-key", dict(payload, action="rotate"), credentials["token"])["data"]
    if not sdk.get("key") and previous.get("key"):
        sdk["key"] = previous["key"]
    credentials["sdk"] = sdk


def push(force=False):
    from .inventory import collect
    with report_lock() as connection:
        if not connection.credentials or connection.site_url != site_url():
            return False
        if not force and connection.next_attempt and connection.next_attempt > timezone.now():
            return False
        try:
            credentials = decrypt(connection.credentials)
            payload = collect()
            result = send("/api/externalpush/openedx", payload, credentials["token"])
            if result.get("data", {}).get("stale"):
                raise DeliveryError(409)
            try:
                refresh_sdk(credentials)
                connection.credentials = encrypt(credentials)
            except (DeliveryError, KeyError):
                pass
            connection.last_success = timezone.now()
            connection.next_attempt = timezone.now() + timedelta(days=1)
            connection.failures = 0
            connection.last_error = ""
            connection.first_refused = None
            connection.component_count = result.get("data", {}).get("components_upserted", 0)
            connection.save()
            return True
        except (DeliveryError, ValueError, RuntimeError, InvalidToken) as error:
            connection.failures += 1
            connection.next_attempt = timezone.now() + timedelta(seconds=min(3600, 60 * 2 ** min(connection.failures - 1, 6)))
            connection.last_error = str(error)[:255] if isinstance(error, DeliveryError) else "Inventory collection failed; inspect server configuration."
            if isinstance(error, DeliveryError) and error.status in (401, 403):
                connection.first_refused = connection.first_refused or timezone.now()
            connection.save()
            return False


@shared_task(name="guardlms_openedx.tasks.report_due", ignore_result=True)
def report_due():
    push()
