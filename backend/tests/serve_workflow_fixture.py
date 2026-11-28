"""Serve an empty, disposable library for the browser workflow tests."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn


if __name__ == '__main__':
    with TemporaryDirectory(dir='/tmp/gallery-faces', prefix='workflows-') as directory:
        os.environ.update(DATA_DIR=directory, IMPORT_DIR=str(Path(directory) / 'imports'),
                          ADMIN_PASSWORD='test-password', COOKIE_SECURE='false')
        uvicorn.run('app.main:app', host='127.0.0.1', port=8013, access_log=False)
