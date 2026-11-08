import uuid
from django.db import models


class Connection(models.Model):
    """Shared LMS/Studio state; only encrypted credentials are stored in SQL."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    generation = models.UUIDField(default=uuid.uuid4)
    credentials = models.TextField(blank=True)
    site_url = models.URLField(blank=True)
    browser_errors = models.BooleanField(default=True)
    server_errors = models.BooleanField(default=False)
    analytics = models.BooleanField(default=False)
    last_success = models.DateTimeField(null=True)
    next_attempt = models.DateTimeField(null=True)
    first_refused = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=255, blank=True)
    failures = models.PositiveIntegerField(default=0)
    component_count = models.PositiveIntegerField(default=0)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]
