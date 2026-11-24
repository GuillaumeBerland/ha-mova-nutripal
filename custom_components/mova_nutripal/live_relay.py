"""Single-reader, loopback-only FLV relay for HA's native stream integration."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import secrets
from threading import Event, Lock, Thread

from .cloud_video import VideoError
from .video import iter_enhanced_flv

_LOGGER = logging.getLogger(__name__)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Do not log request paths or native stream details.
        _LOGGER.debug("NutriPal relay client disconnected")


class _Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(8)
        super().setup()

    def log_message(self, *args):
        pass  # The local capability URL must not be logged.

    def do_GET(self):
        self.server.relay.serve(self)


class LiveRelay:
    """Keep a stable URL; open XP2P only when HA actually reads it.

    A shared gate prevents a standalone snapshot from opening a second native
    session. The HA stream component shares its one decode worker among viewers.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._path = "/" + secrets.token_urlsafe(24) + "/live.flv"
        self._state = Lock()
        self._gate = Lock()
        self._active = Event()
        self._stopped = None
        self._enabled = False
        self._closed = False
        self._server = None
        self._thread = None

    @property
    def active(self):
        return self._active.is_set()

    def set_enabled(self, enabled):
        with self._state:
            self._enabled = bool(enabled) and not self._closed
            if not self._enabled and self._stopped is not None:
                self._stopped.set()

    def start(self):
        """Bind only the loopback interface; no device requests here."""
        with self._state:
            if self._closed or not self._enabled:
                return None
            if self._server is None:
                server = _Server(("127.0.0.1", 0), _Handler)
                server.relay = self
                thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                name="nutripal-flv-relay", daemon=True)
                try:
                    thread.start()
                except Exception:
                    server.server_close()
                    raise
                self._server, self._thread = server, thread
            return f"http://127.0.0.1:{self._server.server_port}{self._path}"

    def capture(self, fn):
        """Run the existing snapshot path only when no other reader owns XP2P."""
        if not self._gate.acquire(blocking=False):
            raise VideoError("video_busy")
        try:
            with self._state:
                if not self._enabled or self._closed:
                    raise VideoError("camera_off_or_unknown")
            return fn()
        finally:
            self._gate.release()

    def serve(self, handler):
        if not secrets.compare_digest(handler.path, self._path):
            handler.send_error(404)
            return
        if not self._gate.acquire(blocking=False):
            handler.send_error(503)
            return
        stopped = Event()
        started = False
        try:
            with self._state:
                enabled = self._enabled and not self._closed
                if enabled:
                    self._stopped = stopped
                    self._active.set()
            if not enabled:
                handler.send_error(503)
                return
            with self._session_factory() as stream_url:
                if stopped.is_set():
                    return
                with closing(iter_enhanced_flv(stream_url, stopped)) as packets:
                    # Send headers only after the FLV header is validated.
                    header = next(packets)
                    if stopped.is_set():
                        return
                    handler.send_response(200)
                    handler.send_header("Content-Type", "video/x-flv")
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    started = True
                    handler.wfile.write(header)
                    for packet in packets:
                        if stopped.is_set():
                            break
                        handler.wfile.write(packet)
        except (OSError, EOFError, StopIteration):
            _LOGGER.debug("NutriPal live stream ended or disconnected")
        except VideoError as exc:
            _LOGGER.warning("NutriPal live stream failed (%s)", str(exc))
            if not started and not stopped.is_set():
                try:
                    handler.send_error(503)
                except OSError:
                    pass
        except Exception:
            _LOGGER.warning("NutriPal live stream failed (unexpected error)")
            if not started and not stopped.is_set():
                try:
                    handler.send_error(503)
                except OSError:
                    pass
        finally:
            stopped.set()
            with self._state:
                self._stopped = None
                self._active.clear()
            self._gate.release()
            handler.close_connection = True

    def close(self):
        """Reject new work and wait for the current native session to clean up."""
        with self._state:
            self._closed = True
            self._enabled = False
            if self._stopped is not None:
                self._stopped.set()
            server, thread = self._server, self._thread
            self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join()
        # An in-flight native startup may take time; do not abandon its cleanup.
        with self._gate:
            pass
