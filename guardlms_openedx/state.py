import json
from cryptography.fernet import Fernet
from django.conf import settings


def cipher():
    # Explicit independent secret, shared by LMS, Studio and all workers.
    return Fernet(settings.GUARDLMS_ENCRYPTION_KEY.encode("ascii"))


def encrypt(value):
    return cipher().encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


def decrypt(value):
    return json.loads(cipher().decrypt(value.encode())) if value else {}
