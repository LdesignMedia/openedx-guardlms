"""Bounded, opt-in diagnostics. No exception values, SQL text, locals or requests."""
import os
import threading
import traceback
from pathlib import Path
from celery.signals import task_failure
from django.core.cache import cache
from django.db import DatabaseError
from django.dispatch import receiver
from django.utils import timezone
from .models import Connection
from .state import decrypt
from .transport import send, site_url

_local = threading.local()


def report_exception(error):
    if getattr(_local, "reporting", False):
        return
    _local.reporting = True
    try:
        state = Connection.objects.filter(pk=1, server_errors=True).first()
        if not state or not state.credentials or state.site_url != site_url():
            return
        sdk = decrypt(state.credentials).get("sdk") or {}
        if not sdk.get("key") or not sdk.get("enabled") or not sdk.get("subscription_active"):
            return
        # A shared bounded rate limit; Django's Redis cache add is atomic.
        minute = int(timezone.now().timestamp() // 60)
        throttle = f"guardlms:server-errors:{minute}"
        cache.add(throttle, 0, 120)
        if cache.incr(throttle) > 25:
            return
        frames = traceback.extract_tb(error.__traceback__)[-30:]
        # Exception strings and source lines can contain learner data or SQL literals.
        # Report the exception class and basename/line/function only.
        name = type(error).__name__[:100]
        stack = "\n".join(f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}" for frame in frames)[:10000]
        send("/api/sdk/errors/collect", {"errors": [{
            "type": "sql" if isinstance(error, DatabaseError) else "python",
            "message": name, "errorClass": name, "stackTrace": stack,
            "pageUrl": site_url() + "/", "timestamp": timezone.now().isoformat(),
            "severity": "error", "handled": False,
            "context": "Open edX " + ("Studio" if os.environ.get("SERVICE_VARIANT") == "cms" else "LMS"),
        }]}, sdk["key"], sdk=True)
    except Exception:
        pass  # Never recursively log/report a failed telemetry request.
    finally:
        _local.reporting = False


@receiver(task_failure, dispatch_uid="guardlms.celery.failure", weak=False)
def celery_failure(sender=None, exception=None, **kwargs):
    if exception is not None and not getattr(sender, "name", "").startswith("guardlms_openedx."):
        report_exception(exception)
