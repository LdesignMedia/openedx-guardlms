import json
import secrets
import time
import uuid
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import InvalidToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from .models import Connection
from .state import decrypt, encrypt
from .tasks import refresh_sdk
from .transport import DeliveryError, https_origin, send, site_url


def superuser(user):
    if not user.is_authenticated or not user.is_active or not user.is_superuser:
        raise PermissionDenied
    return True


admin_required = user_passes_test(superuser)


@admin_required
@require_GET
def index(request):
    connection = Connection.current()
    try:
        credentials = decrypt(connection.credentials) if connection.credentials else {}
    except (InvalidToken, ValueError):
        credentials = {}
        connection.last_error = _("Stored credentials cannot be decrypted. Restore the deployment encryption key or reconnect.")
    expiry = credentials.get("expires_at")
    expired = False
    if expiry:
        try:
            expired = datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= timezone.now()
        except ValueError:
            expired = True
    status = _("Not connected") if not connection.credentials else _("Reconnect required") if not credentials or connection.first_refused or expired or connection.site_url != site_url() else _("Connected")
    website_id = credentials.get("website_id")
    return render(request, "guardlms/settings.html", {
        "connection": connection, "status": status, "expiry": expiry,
        "dashboard": https_origin(settings.GUARDLMS_DASHBOARD_URL) + "/websites/" + str(int(website_id)) if website_id else None,
        "verification_token": credentials.get("verification_token"),
        "lms_url": site_url(),
    })


@admin_required
@require_POST
def connect(request):
    # Start on the canonical LMS, never Studio's different session cookie.
    if request.get_host() != urlsplit(site_url()).netloc:
        return redirect(site_url() + "/guardlms/")
    generation = uuid.uuid4()
    Connection.current()
    Connection.objects.filter(pk=1).update(generation=generation)
    state = secrets.token_urlsafe(48)
    request.session["guardlms_connect"] = {"state": state, "created": time.time(), "generation": str(generation)}
    url = https_origin(settings.GUARDLMS_DASHBOARD_URL) + "/connect/openedx?" + urlencode({
        "siteurl": site_url(), "callback": site_url() + "/guardlms/callback", "state": state,
    })
    return redirect(url)


@admin_required
@require_GET
def callback(request):
    if request.get_host() != urlsplit(site_url()).netloc:
        raise PermissionDenied
    pending = request.session.get("guardlms_connect")
    state = request.GET.get("state", "")
    if (not pending or not secrets.compare_digest(pending["state"], state)
            or not 0 <= time.time() - pending["created"] <= 600):
        raise PermissionDenied
    del request.session["guardlms_connect"]
    try:
        # Serialize with disconnect, reconnect and reporting. Keep the generation check
        # inside the same transaction as the install; HTTP failures leave no credentials.
        with transaction.atomic():
            connection = Connection.objects.select_for_update().get(pk=1)
            if str(connection.generation) != pending["generation"]:
                raise PermissionDenied
            result = send("/api/integrations/exchange", {"code": request.GET.get("code", ""), "state": state, "siteurl": site_url()})
            data = result.get("data", result)
            if data.get("siteurl", "").rstrip("/") != site_url() or data.get("pushpath") != "/api/externalpush/openedx" or not data.get("token"):
                raise DeliveryError()
            # An inventory outage must not prevent Studio/MFE monitoring from starting.
            try:
                refresh_sdk(data)
            except (DeliveryError, KeyError):
                pass
            connection.credentials = encrypt(data)
            connection.site_url = site_url()
            connection.first_refused = None
            connection.last_error = ""
            connection.next_attempt = timezone.now()
            connection.save()
        from .tasks import push
        accepted = push(force=True)
        messages.success(request, _("Connected. First inventory accepted.") if accepted else _("Connected. Inventory delivery will retry automatically."))
    except (DeliveryError, ValueError):
        messages.error(request, _("Connection could not be completed. Start a new connection attempt."))
    return redirect("guardlms:index")


@admin_required
@require_POST
def disconnect(request):
    Connection.current()
    Connection.objects.filter(pk=1).update(credentials="", site_url="", generation=uuid.uuid4(), next_attempt=None, first_refused=None, last_error="")
    request.session.pop("guardlms_connect", None)
    messages.success(request, _("Disconnected. Reporting has stopped. The website remains in GuardLMS."))
    return redirect("guardlms:index")


@admin_required
@require_POST
def push_now(request):
    from .tasks import push
    messages.info(request, _("Inventory accepted.") if push(force=True) else _("Inventory was not accepted. Check connection health."))
    return redirect("guardlms:index")


@admin_required
@require_POST
def preferences(request):
    Connection.current()
    Connection.objects.filter(pk=1).update(**{key: request.POST.get(key) == "on" for key in ("browser_errors", "server_errors", "analytics")})
    return redirect("guardlms:index")


@admin_required
@require_GET
def preview(request):
    from .inventory import collect
    try:
        response = JsonResponse(collect(), json_dumps_params={"indent": 2})
    except (RuntimeError, ValueError):
        response = JsonResponse({"error": "Inventory collection failed. Check the build manifest and configuration."}, status=503)
    response["Cache-Control"] = "no-store"
    return response


def browser_options():
    connection = Connection.objects.filter(pk=1).first()
    if not connection or not connection.credentials or connection.site_url != site_url():
        return None
    try:
        credentials = decrypt(connection.credentials)
    except (InvalidToken, ValueError):
        return None
    sdk = credentials.get("sdk") or {}
    key = sdk.get("key")
    if not key or not sdk.get("enabled") or not sdk.get("subscription_active"):
        return None
    if not connection.browser_errors and not (connection.analytics and sdk.get("analytics_allowed")):
        return None
    return {
        "sdkUrl": sdk["sdk_url"], "apiKey": key, "endpoint": sdk["errors_endpoint"],
        "analyticsEndpoint": sdk["analytics_endpoint"], "appVersion": getattr(settings, "GUARDLMS_OPENEDX_VERSION", "unknown"),
        "autoDetectErrors": connection.browser_errors,
        "analytics": {"enabled": connection.analytics and bool(sdk.get("analytics_allowed")), "analyticsEndpoint": sdk["analytics_endpoint"], "sampleRate": sdk.get("analytics_sample_rate", 1)},
        "sampleRate": sdk.get("sample_rate", 1), "analyticsSampleRate": sdk.get("analytics_sample_rate", 1),
        "maxBreadcrumbs": sdk.get("max_breadcrumbs", 40), "maxErrorsPerMinute": sdk.get("max_errors_per_minute", 100),
        "collectUserIp": False,
    }


@require_GET
def browser_config(request):
    origin = request.headers.get("Origin")
    origins = [https_origin(value) for value in settings.GUARDLMS_BROWSER_ORIGINS] + [site_url()]
    if origin and origin not in origins:
        return JsonResponse({"error": "Origin not allowed"}, status=403)
    response = JsonResponse(browser_options() or {})
    response["Cache-Control"] = "no-store"
    response["Vary"] = "Origin"
    if origin:
        response["Access-Control-Allow-Origin"] = origin
    return response


@require_GET
def bootstrap(request):
    from importlib.resources import files
    response = HttpResponse(files("guardlms_openedx").joinpath("static/guardlms/bootstrap.js").read_bytes(), content_type="application/javascript")
    response["Cache-Control"] = "public, max-age=3600"
    return response
