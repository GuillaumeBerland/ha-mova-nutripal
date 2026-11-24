"""Bounded, on-demand JPEG capture. No media is retained by this module."""
import http.client
import logging
from contextlib import contextmanager
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from .cloud_video import VideoCancelled, VideoError, provision
from .flv import convert_stream

_LOGGER = logging.getLogger(__name__)


def _local_target(stream_url):
    url = urlsplit(stream_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1", "localhost")
            or url.username or url.password or url.fragment):
        raise VideoError("nonlocal_stream")
    return url.hostname, url.port or 80, (url.path or "/") + ("?" + url.query if url.query else "")


def _check_cancelled(stopped):
    if stopped is not None and stopped.is_set():
        raise VideoCancelled("snapshot_cancelled")


def capture_jpeg(stream_url, ffmpeg, *, seconds=35, stopped=None):
    """Convert in memory and extract one frame; terminate FFmpeg on failure."""
    _check_cancelled(stopped)
    host, port, target = _local_target(stream_url)
    connection = http.client.HTTPConnection(host, port, timeout=8)
    process = None
    deadline = time.monotonic() + seconds
    with tempfile.TemporaryDirectory(prefix="nutripal-camera-") as directory:
        destination = Path(directory) / "frame.jpg"
        try:
            connection.request("GET", target)
            response = connection.getresponse()
            _check_cancelled(stopped)
            if response.status != 200:
                raise VideoError("video_http_status")

            def read_exact(size):
                data = bytearray()
                while len(data) < size:
                    _check_cancelled(stopped)
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    chunk = response.read1(size - len(data))
                    _check_cancelled(stopped)
                    if not chunk:
                        raise EOFError()
                    data.extend(chunk)
                return bytes(data)

            process = subprocess.Popen([
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "flv", "-i", "pipe:0", "-map", "0:v:0", "-frames:v", "1",
                "-update", "1", "-y", str(destination),
            ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, bufsize=0)
            fd = process.stdin.fileno()
            os.set_blocking(fd, False)
            try:
                for packet in convert_stream(read_exact):
                    _check_cancelled(stopped)
                    if process.poll() is not None:
                        break
                    remaining = memoryview(packet)
                    while remaining:
                        _check_cancelled(stopped)
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        if process.poll() is not None:
                            raise BrokenPipeError()
                        if select.select([], [fd], [], 0.5)[1]:
                            try:
                                remaining = remaining[os.write(fd, remaining):]
                            except BlockingIOError:
                                continue
            except (BrokenPipeError, EOFError, TimeoutError):
                pass  # EOF lets FFmpeg flush any already received frame.
        finally:
            connection.close()
            if process is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
                # Flush normally, but do not spend ten seconds waiting for a
                # discarded JPEG. The native session is closed by its owner.
                flush_deadline = time.monotonic() + 10
                while process.poll() is None:
                    if ((stopped is not None and stopped.is_set())
                            or time.monotonic() >= flush_deadline):
                        process.kill()
                        process.wait()
                        break
                    try:
                        process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        continue
        _check_cancelled(stopped)
        if process is None or process.returncode != 0 or not destination.is_file():
            raise VideoError("jpeg_capture_failed")
        if destination.stat().st_size > 8 * 1024 * 1024:
            raise VideoError("jpeg_size")
        image = destination.read_bytes()
        if not image.startswith(b"\xff\xd8\xff") or not image.endswith(b"\xff\xd9"):
            raise VideoError("jpeg_invalid")
        return image


@contextmanager
def open_video_session(username, password, did, runtime_path, *, authorization_cache=None, stopped=None):
    """Open one authorized video session and always close it on exit."""
    from .api import NutriPalAPI
    from .const import MODEL

    stage = "runtime_import"
    started = time.monotonic()
    mark = started
    api = None
    runtime = None
    session = None
    try:
        _check_cancelled(stopped)
        from .xp2p.models import DreameLawnMowerCameraStreamRuntimeInputs
        from .xp2p.xp2p_host_runtime import DreameLawnMowerXp2pHostRuntime
        from .xp2p.xp2p_runtime_bootstrap import ensure_xp2p_host_runtime

        stage = "runtime_prepare"
        assets = ensure_xp2p_host_runtime(runtime_path)
        assets.validate()
        if not (assets.startup_probe or {}).get("ready"):
            raise VideoError("runtime_probe_failed")
        _LOGGER.debug("NutriPal video runtime ready in %.1f s", time.monotonic() - mark)
        _check_cancelled(stopped)
        mark = time.monotonic()
        stage = "video_login"
        api = NutriPalAPI(username, password)
        api.discover(did)
        # Honor the device's own camera switch; never enable it ourselves.
        _LOGGER.debug("NutriPal video login/discovery in %.1f s", time.monotonic() - mark)
        _check_cancelled(stopped)
        check_started = time.monotonic()
        stage = "camera_switch"
        result = api.cloud.send("get_properties", [{"did": str(did), "siid": 1000, "piid": 1}], retry_count=0, timeout=15)
        if not isinstance(result, list) or not any(
            isinstance(x, dict) and x.get("siid") == 1000 and x.get("piid") == 1
            and x.get("code") == 0 and x.get("value") == 1 for x in result
        ):
            raise VideoError("camera_off_or_unknown")
        _LOGGER.debug("NutriPal camera switch check in %.1f s", time.monotonic() - check_started)
        _check_cancelled(stopped)
        stage = "video_provision"
        provision_started = time.monotonic()
        if authorization_cache is None:
            identity, reused = provision(api.cloud, did, MODEL), False
        else:
            identity, reused = authorization_cache.get_or_provision(api.cloud, did, MODEL)
        _LOGGER.debug("NutriPal video provisioning (%s) in %.1f s",
                      "cache hit" if reused else "fresh", time.monotonic() - provision_started)
        api.close()
        api = None
        _check_cancelled(stopped)
        inputs = DreameLawnMowerCameraStreamRuntimeInputs(
            source="mova_nutripal", did=str(did), channel_id=identity.device_id,
            product_id=identity.product_id, device_name=identity.device_name,
            p2p_info=identity.p2p_info, secret_id=identity.secret_id,
            secret_key=identity.secret_key, app_id=identity.secret_id,
            app_secret=identity.secret_key, stream_channel=0,
        )
        _LOGGER.debug("NutriPal video authorization in %.1f s", time.monotonic() - mark)
        mark = time.monotonic()
        stage = "xp2p_connect"
        runtime = DreameLawnMowerXp2pHostRuntime(assets)
        session = runtime.start_live_stream(inputs, command_timeout_us=2_500_000,
            device_status_attempts=20, device_status_retry_interval=2.0,
            delegate_attempts=20, delegate_retry_interval=0.5)
        _LOGGER.debug("NutriPal XP2P ready in %.1f s (total %.1f s)",
                      time.monotonic() - mark, time.monotonic() - started)
        _check_cancelled(stopped)
        stage = "video_consumer"
        _local_target(session.stream_url)
        yield session.stream_url
    except VideoCancelled:
        # An intentional handoff preserves a still-valid authorization.
        raise
    except VideoError:
        if authorization_cache is not None:
            authorization_cache.clear()
        raise
    except Exception:
        if stage == "video_consumer":
            raise  # The caller owns and sanitizes media-side failures.
        if authorization_cache is not None:
            authorization_cache.clear()
        # Upstream exceptions may contain private URL/identity values.
        failure = getattr(runtime, "last_failure", None) or {}
        status = failure.get("worker_status")
        if type(status) is int:
            stage += f"_{status}"
        raise VideoError(stage) from None
    finally:
        if session is not None:
            try:
                runtime.stop_live_stream(session)
            except Exception:
                if authorization_cache is not None:
                    authorization_cache.clear()
                raise VideoError("xp2p_cleanup") from None
        if api is not None:
            try:
                api.close()
            except Exception:
                if authorization_cache is not None:
                    authorization_cache.clear()
                raise VideoError("video_cloud_cleanup") from None


def snapshot(username, password, did, runtime_path, *, authorization_cache=None, stopped=None):
    """Keep the independent still-image path when live playback is not active."""
    _check_cancelled(stopped)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoError("ffmpeg_missing")
    with open_video_session(username, password, did, runtime_path,
                            authorization_cache=authorization_cache, stopped=stopped) as url:
        started = time.monotonic()
        try:
            image = capture_jpeg(url, ffmpeg, stopped=stopped)
            _check_cancelled(stopped)
            return image
        except VideoError:
            raise
        except TimeoutError:
            _check_cancelled(stopped)
            raise VideoError("jpeg_capture") from None
        except Exception:
            raise VideoError("jpeg_capture") from None
        finally:
            _LOGGER.debug("NutriPal JPEG capture ended in %.1f s", time.monotonic() - started)


def iter_enhanced_flv(stream_url, stopped):
    """Read one native FLV connection; yield complete converted tags until stopped."""
    host, port, target = _local_target(stream_url)
    connection = http.client.HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", target)
        response = connection.getresponse()
        if response.status != 200:
            raise VideoError("video_http_status")

        def read_exact(size):
            data = bytearray()
            while len(data) < size:
                if stopped.is_set():
                    raise EOFError()
                chunk = response.read1(size - len(data))
                if not chunk:
                    raise EOFError()
                data.extend(chunk)
            return bytes(data)

        yield from convert_stream(read_exact)
    finally:
        connection.close()
