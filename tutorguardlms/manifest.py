"""Combine manifests extracted from the exact MFE image; fail on missing data."""
import json
from pathlib import Path
import sys
import tarfile

archive, target = map(Path, sys.argv[1:])
items = {}
with tarfile.open(archive, 'r:gz') as tar:
    files = [member for member in tar if member.isfile() and member.name.endswith('/guardlms-npm.json')]
    if not files:
        raise SystemExit('No MFE manifests found. Build the MFE image with the GuardLMS Tutor plugin enabled.')
    for member in files:
        if member.size > 8 * 1024 * 1024:
            raise SystemExit('Oversized MFE manifest')
        for dep in json.load(tar.extractfile(member)):
            key = (dep['name'], dep['version'])
            # A package shipped by any MFE is not merely a development dependency.
            if key in items:
                dep['dev'] = bool(dep.get('dev')) and bool(items[key].get('dev'))
            items[key] = dep
if len(items) > 10000:
    raise SystemExit('Complete MFE inventory exceeds receiver limits')
target.write_text(json.dumps(list(items.values()), separators=(',', ':')))
print(f'Exported {len(items)} resolved npm dependencies from {len(files)} MFE build manifests.')
