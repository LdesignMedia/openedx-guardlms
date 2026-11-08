"""Isolated Studio security evaluation, without importing CMS into the LMS process."""
if __name__ == '__main__':
    import json
    import django
    django.setup()
    from .inventory import security_checks
    print('GUARDLMS_CHECKS=' + json.dumps(security_checks()))
