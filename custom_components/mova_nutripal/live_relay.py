"""Single-reader, loopback-only FLV relay for HA's native stream integration."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import secrets
from threading import Event, Lock, Thread
from time import monotonic

from .cloud_video import VideoError
from .video import iter_enhanced_flv
from .transcode import iter_h264_flv

START_WAIT = 12
FAILURE_BACKOFF = 60

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

    def __init__(self, session_factory, codec="hevc"):
        self._codec = codec
        self._retry_after = 0.0
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

    def set_codec(self, codec):
        codec = codec if codec in ("h264", "hevc") else "h264"
        with self._state:
            if codec != self._codec:
                self._codec = codec
                if self._stopped is not None:
                    self._stopped.set()

    def _backoff(self):
        with self._state:
            self._retry_after = monotonic() + FAILURE_BACKOFF

    def capture(self, fn):
        """Do not start a snapshot while a live reader is waiting or active."""
        with self._state:
            if not self._enabled or self._closed:
                raise VideoError("camera_off_or_unknown")
            if monotonic() < self._retry_after:
                raise VideoError("video_backoff")
            if self._active.is_set() or not self._gate.acquire(blocking=False):
                raise VideoError("video_busy")
        try:
            return fn()
        except Exception:
            self._backoff()
            raise
        finally:
            self._gate.release()

    def serve(self, handler):
        if not secrets.compare_digest(handler.path, self._path):
            handler.send_error(404)
            return
        stopped = Event()
        with self._state:
            if not self._enabled or self._closed:
                refusal = "disabled"
            elif monotonic() < self._retry_after:
                refusal = "backoff"
            elif self._active.is_set():
                refusal = "already_live"
            else:
                refusal = None
                self._stopped = stopped
                self._active.set()  # Reserve before waiting on an existing snapshot.
        if refusal:
            _LOGGER.debug("NutriPal live request refused (%s)", refusal)
            handler.send_error(503)
            return
        acquired = started = False
        try:
            acquired = self._gate.acquire(timeout=START_WAIT)
            if not acquired:
                _LOGGER.debug("NutriPal live request waiting for snapshot timed out")
                handler.send_error(503)
                return
            with self._state:
                enabled = (self._enabled and not self._closed and not stopped.is_set()
                           and monotonic() >= self._retry_after)
                codec = self._codec
            if not enabled:
                handler.send_error(503)
                return
            with self._session_factory() as stream_url:
                if stopped.is_set():
                    return
                iterator = iter_h264_flv if codec == "h264" else iter_enhanced_flv
                with closing(iterator(stream_url, stopped)) as packets:
                    header = next(packets)
                    if stopped.is_set():
                        return
                    handler.send_response(200)
                    handler.send_header("Content-Type", "video/x-flv")
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    started = True
                    _LOGGER.debug("NutriPal live relay streaming (%s)", codec)
                    handler.wfile.write(header)
                    for packet in packets:
                        if stopped.is_set():
                            break
                        handler.wfile.write(packet)
        except (OSError, EOFError, StopIteration):
            if not started and not stopped.is_set():
                self._backoff()
            _LOGGER.debug("NutriPal live stream ended or disconnected")
        except VideoError as exc:
            if not stopped.is_set():
                self._backoff()
            _LOGGER.warning("NutriPal live stream failed (%s)", str(exc))
            if not started and not stopped.is_set():
                try:
                    handler.send_error(503)
                except OSError:
                    pass
        except Exception:
            if not stopped.is_set():
                self._backoff()
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
                if acquired:
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
