"""Isolated photo library for the multiplayer browser test."""
import os
import socket
from argparse import ArgumentParser
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from PIL import Image, ImageDraw


def serve(port=0):
    with TemporaryDirectory(dir='/tmp/gallery-faces', prefix='room-') as directory:
        os.environ.update(DATA_DIR=directory, IMPORT_DIR=str(Path(directory) / 'imports'), ADMIN_PASSWORD='test-password')
        from app import db
        from app.main import app
        from test_face_game import seed
        from test_photo_draw import photo

        db.init()
        with db.connect(True) as conn:
            identifier = seed(conn)
            images = [identifier]
            if os.environ.get('FIXTURE_DATE_RANGE') == '1':
                images.append(photo(conn, date='2026-01-10T12:00:00Z'))
                conn.execute('UPDATE faces SET person_id=1')
            conn.execute("UPDATE faces SET box='[10,10,40,30]'")
        image = Image.new('RGB', (100, 100), '#dfdfdf')
        ImageDraw.Draw(image).rectangle((10, 10, 49, 39), fill='#3167aa')
        for identifier in images:
            image.save(db.DATA / 'images' / f'{identifier}.jpg')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
            print(f'ROOM_ORIGIN=http://127.0.0.1:{listener.getsockname()[1]}', flush=True)
            uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='error')).run(sockets=[listener])


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    serve(parser.parse_args().port)
