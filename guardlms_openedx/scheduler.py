"""Dedicated Celery Beat process: never schedules unrelated Open edX jobs."""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lms.envs.tutor.production")
from lms.celery import APP as app

app.conf.beat_schedule = {
    "guardlms-inventory": {"task": "guardlms_openedx.tasks.report_due", "schedule": 60.0,
                           "options": {"queue": "edx.lms.core.default", "expires": 120}},
}
if __name__ == "__main__":
    app.start(["beat", "--loglevel=info", "--schedule=/tmp/guardlms-celerybeat"])
