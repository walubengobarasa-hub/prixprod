"""Build GitHub Release ZIP from validated LFS-backed model folders.

Usage: python scripts/build_github_models_release.py /tmp/prix-models.zip
"""
import sys
import zipfile
from pathlib import Path

from prepare_github_models import prepare

ROOT = Path(__file__).resolve().parent.parent
if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/build_github_models_release.py OUTPUT.zip')
    from prepare_github_models import main as _unused
    manifest = prepare()
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
        for relative in sorted(manifest['files']):
            source = ROOT / 'deploy_models' / 'models' / relative
            archive.write(source, f'models/{relative}')
    print(f'Wrote {output} ({output.stat().st_size} bytes)')
