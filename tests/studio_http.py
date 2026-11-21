"""Serve a studio on a private loopback port for browser tests."""

import socket
import threading
import time
from contextlib import contextmanager

from meocosub2.cli import studio_http_server


@contextmanager
def running_studio(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        app._allowed_origins = {url}
        server = studio_http_server(app)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            yield url
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
            assert not server.server_state.connections
            assert not server.server_state.tasks
