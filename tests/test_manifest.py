import ast
import json
from pathlib import Path
import subprocess


def test_duplicate_npm_package_keeps_production_usage(tmp_path):
    plugin = Path(__file__).parents[1] / 'tutorguardlms/plugin.py'
    tree = ast.parse(plugin.read_text())
    script = next(ast.literal_eval(item.value) for item in tree.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'manifest_js' for target in item.targets))
    (tmp_path/'manifest.cjs').write_text(script)
    (tmp_path/'package-lock.json').write_text(json.dumps({'packages': {
        'node_modules/example': {'version': '1.0.0', 'dev': False},
        'node_modules/dev-tool/node_modules/example': {'version': '1.0.0', 'dev': True},
    }}))
    subprocess.run(['node', str(tmp_path/'manifest.cjs')], cwd=tmp_path, check=True)
    result = json.loads((tmp_path/'dist/guardlms-npm.json').read_text())
    assert result == [{'name': 'example', 'version': '1.0.0', 'dev': False}]
