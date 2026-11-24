"""Bounded, on-demand JPEG capture. No media is retained by this module."""
import http.client
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from .cloud_video import VideoError, provision
from .flv import convert_stream


def _local_target(stream_url):
    url = urlsplit(stream_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1", "localhost")
            or url.username or url.password or url.fragment):
        raise VideoError("nonlocal_stream")
    return url.hostname, url.port or 80, (url.path or "/") + ("?" + url.query if url.query else "")


def capture_jpeg(stream_url, ffmpeg, *, seconds=35):
    """Convert in memory and extract one frame; terminate FFmpeg on failure."""
    host, port, target = _local_target(stream_url)
    connection = http.client.HTTPConnection(host, port, timeout=8)
    process = None
    deadline = time.monotonic() + seconds
    with tempfile.TemporaryDirectory(prefix="nutripal-camera-") as directory:
        destination = Path(directory) / "frame.jpg"
        try:
            connection.request("GET", target)
            response = connection.getresponse()
            if response.status != 200:
                raise VideoError("video_http_status")

            def read_exact(size):
                data = bytearray()
                while len(data) < size:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    chunk = response.read1(size - len(data))
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
                    if process.poll() is not None:
                        break
                    remaining = memoryview(packet)
                    while remaining:
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
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if process is None or process.returncode != 0 or not destination.is_file():
            raise VideoError("jpeg_capture_failed")
        if destination.stat().st_size > 8 * 1024 * 1024:
            raise VideoError("jpeg_size")
        image = destination.read_bytes()
        if not image.startswith(b"\xff\xd8\xff") or not image.endswith(b"\xff\xd9"):
            raise VideoError("jpeg_invalid")
        return image


def snapshot(username, password, did, runtime_path):
    """Separate cloud session; never share the feeding adapter's command lock."""
    from .api import NutriPalAPI
    from .const import MODEL

    stage = "runtime_import"
    api = None
    runtime = None
    session = None
    try:
        from .xp2p.models import DreameLawnMowerCameraStreamRuntimeInputs
        from .xp2p.xp2p_host_runtime import DreameLawnMowerXp2pHostRuntime
        from .xp2p.xp2p_runtime_bootstrap import ensure_xp2p_host_runtime

        stage = "ffmpeg_missing"
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoError(stage)
        stage = "runtime_prepare"
        assets = ensure_xp2p_host_runtime(runtime_path)
        assets.validate()
        if not (assets.startup_probe or {}).get("ready"):
            raise VideoError("runtime_probe_failed")
        stage = "video_login"
        api = NutriPalAPI(username, password)
        api.discover(did)
        # Honor the device's own camera switch; never enable it ourselves.
        stage = "camera_switch"
        result = api.cloud.send("get_properties", [{"did": str(did), "siid": 1000, "piid": 1}], retry_count=0, timeout=15)
        if not isinstance(result, list) or not any(
            isinstance(x, dict) and x.get("siid") == 1000 and x.get("piid") == 1
            and x.get("code") == 0 and x.get("value") == 1 for x in result
        ):
            raise VideoError("camera_off_or_unknown")
        stage = "video_provision"
        identity = provision(api.cloud, did, MODEL)
        api.close()
        api = None
        inputs = DreameLawnMowerCameraStreamRuntimeInputs(
            source="mova_nutripal", did=str(did), channel_id=identity.device_id,
            product_id=identity.product_id, device_name=identity.device_name,
            p2p_info=identity.p2p_info, secret_id=identity.secret_id,
            secret_key=identity.secret_key, app_id=identity.secret_id,
            app_secret=identity.secret_key, stream_channel=0,
        )
        stage = "xp2p_connect"
        runtime = DreameLawnMowerXp2pHostRuntime(assets)
        session = runtime.start_live_stream(inputs, command_timeout_us=2_500_000,
            device_status_attempts=20, device_status_retry_interval=2.0,
            delegate_attempts=20, delegate_retry_interval=0.5)
        stage = "jpeg_capture"
        return capture_jpeg(session.stream_url, ffmpeg)
    except VideoError:
        raise
    except Exception:
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
                raise VideoError("xp2p_cleanup") from None
        if api is not None:
            try:
                api.close()
            except Exception:
                raise VideoError("video_cloud_cleanup") from None
