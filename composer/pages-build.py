"""Fixed Pages entry: no source interpolation into shell commands or user hooks."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

COMPILER_URL = 'https://github.com/Myriad-Dreamin/tinymist/releases/download/v0.15.8/tinymist-x86_64-unknown-linux-gnu.tar.gz'
COMPILER_SHA256 = '2428932e8d8b593ebc1ac4eed41fb9d3584166e1044bbcdef740b7296c348295'


def validate_identity(source, workflow, operation, actual):
    if not re.fullmatch(r'[0-9a-f]{40}', source) or source != workflow or source != actual:
        raise ValueError('Source or workflow changed after publication review; review and publish again')
    if not re.fullmatch(r'[a-zA-Z0-9-]{16,128}', operation):
        raise ValueError('Invalid publication identity')


def release_marker(report, source, operation):
    return {'schemaVersion': 1, 'siteId': report['siteId'], 'sourceSha': source,
            'operationId': operation, 'files': report['files']}


def main():
    root = Path(__file__).resolve().parent.parent
    source, workflow, operation = (os.environ[k] for k in ('COMPOSER_SOURCE_SHA', 'COMPOSER_WORKFLOW_SHA', 'COMPOSER_OPERATION_ID'))
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    validate_identity(source, workflow, operation, actual)
    with tempfile.TemporaryDirectory(prefix='composer-compiler-') as temporary:
        archive = Path(temporary) / 'compiler.tar.gz'
        with urllib.request.urlopen(COMPILER_URL, timeout=60) as response, archive.open('wb') as output:
            total = 0
            while data := response.read(1024 * 1024):
                total += len(data)
                if total > 128 * 1024 * 1024: raise ValueError('Compiler archive exceeds expected size')
                output.write(data)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != COMPILER_SHA256:
            raise ValueError('Compiler checksum does not match the pinned release')
        # Only the verified compiler executable is extracted; no package scripts.
        compiler = Path(temporary) / 'tinymist'
        with tarfile.open(archive, 'r:gz') as package:
            candidates = [m for m in package.getmembers() if m.isfile() and Path(m.name).name == 'tinymist']
            if len(candidates) != 1: raise ValueError('Compiler archive layout changed')
            with package.extractfile(candidates[0]) as stream: compiler.write_bytes(stream.read())
        compiler.chmod(0o700)
        spec = importlib.util.spec_from_file_location('composer_builder', Path(__file__).with_name('build-composer.py'))
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        website = root.parent / 'composer-public-site'
        report = builder.build(root, website, compiler, 'public')
        marker = website / 'composer-release.json'
        if marker.exists(): raise ValueError('Reserved release identity file is already present')
        marker.write_text(json.dumps(release_marker(report, source, operation), ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
