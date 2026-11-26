"""Isolated photo library for the multiplayer browser test."""
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from PIL import Image, ImageDraw


def serve():
    with TemporaryDirectory(dir='/tmp/gallery-faces', prefix='room-') as directory:
        os.environ.update(DATA_DIR=directory, IMPORT_DIR=str(Path(directory) / 'imports'), ADMIN_PASSWORD='test-password')
        from app import db
        from app.main import app
        from test_face_game import seed

        db.init()
        with db.connect(True) as conn:
            identifier = seed(conn)
            conn.execute("UPDATE faces SET box='[10,10,40,30]'")
        image = Image.new('RGB', (100, 100), '#dfdfdf')
        ImageDraw.Draw(image).rectangle((10, 10, 49, 39), fill='#3167aa')
        image.save(db.DATA / 'images' / f'{identifier}.jpg')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            print(f'ROOM_ORIGIN=http://127.0.0.1:{listener.getsockname()[1]}', flush=True)
            uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='error')).run(sockets=[listener])


if __name__ == '__main__':
    serve()
