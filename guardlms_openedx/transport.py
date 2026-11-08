import json
from urllib.parse import urlsplit
import requests
from django.conf import settings


class DeliveryError(Exception):
    def __init__(self, status=0):
        self.status = status
        super().__init__(f"GuardLMS HTTP {status}" if status else "GuardLMS delivery unavailable")


def https_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Configure a canonical HTTPS origin")
    return value.rstrip("/")


def site_url():
    return https_origin(settings.GUARDLMS_SITE_URL)


def send(path, payload, token=None, sdk=False):
    origin = https_origin(settings.GUARDLMS_API_URL)
    if not path.startswith("/api/") or "?" in path or "#" in path or ".." in path:
        raise DeliveryError()
    headers = {"Accept": "application/json"}
    if sdk:
        headers["Origin"] = site_url()
    if token:
        headers["X-SDK-Key" if sdk else "Authorization"] = token if sdk else "Bearer " + token
    try:
        with requests.post(origin + path, json=payload, headers=headers, timeout=(5, 25),
                           allow_redirects=False, stream=True) as response:
            if response.status_code not in (200, 201, 202):
                raise DeliveryError(response.status_code)
            body = bytearray()
            for chunk in response.iter_content(16384):
                body.extend(chunk)
                if len(body) > 262144:
                    raise DeliveryError()
            result = json.loads(body)
            if not isinstance(result, dict):
                raise DeliveryError()
            return result
    except (requests.RequestException, ValueError) as exc:
        raise DeliveryError() from exc
