import html
from django.conf import settings
from .transport import site_url


class MonitoringMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # External bootstrap respects the site's CSP and fetches uncached preferences.
        # Do not modify streaming/compressed responses, redirects, or connector pages.
        if (response.status_code == 200 and not response.streaming
                and "text/html" in response.get("Content-Type", "")
                and not response.get("Content-Encoding") and not request.path.startswith("/guardlms/")):
            try:
                tag = ('<script defer src="' + html.escape(site_url() + "/guardlms/bootstrap.js", quote=True) + '"></script>').encode()
                if b"</head>" in response.content:
                    response.content = response.content.replace(b"</head>", tag + b"</head>", 1)
                    if response.has_header("Content-Length"):
                        response["Content-Length"] = str(len(response.content))
            except Exception:
                pass  # Telemetry cannot make an LMS page unavailable.
        return response

    def process_exception(self, request, exception):
        from .telemetry import report_exception
        report_exception(exception)
        return None
