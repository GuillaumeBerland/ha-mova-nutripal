"""On-demand H.264 compatibility stream. No files or external listener."""
import logging
import os
import select
import shutil
import subprocess
from threading import Event, Thread
import time

from .cloud_video import VideoError
from .video import iter_enhanced_flv

_LOGGER = logging.getLogger(__name__)


def ffmpeg_command(executable):
    # No -copyts: rebase the source's large initial timestamp. Use bounded
    # GOPs and zero-latency encoding for the native HA HLS segmenter.
    return [executable, '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-probesize', '524288', '-analyzeduration', '2000000',
            '-f', 'flv', '-i', 'pipe:0', '-map', '0:v:0', '-map', '0:a:0?',
            '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p', '-threads', '2', '-crf', '25',
            '-g', '30', '-keyint_min', '30', '-sc_threshold', '0',
            '-force_key_frames', 'expr:gte(t,n_forced*2)',
            '-c:a', 'copy', '-avoid_negative_ts', 'make_zero',
            '-f', 'flv', '-flvflags', 'no_duration_filesize', 'pipe:1']


class _Stop:
    def __init__(self, external, local):
        self.external, self.local = external, local

    def is_set(self):
        return self.external.is_set() or self.local.is_set()


def iter_h264_flv(url, stopped):
    """Feed converted HEVC to FFmpeg; concurrently drain FLV output."""
    executable = shutil.which('ffmpeg')
    if not executable:
        raise VideoError('ffmpeg_missing')
    local = Event()
    stop = _Stop(stopped, local)
    errors = []
    process = subprocess.Popen(ffmpeg_command(executable), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               bufsize=0)

    def feed():
        try:
            for packet in iter_enhanced_flv(url, stop):
                remaining = memoryview(packet)
                while remaining and not stop.is_set():
                    count = process.stdin.write(remaining)
                    if not count:
                        raise BrokenPipeError()
                    remaining = remaining[count:]
                if stop.is_set():
                    break
        except EOFError:
            pass  # Let FFmpeg flush the received frames.
        except Exception:
            if not stop.is_set():
                errors.append('transcode_input')
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    worker = Thread(target=feed, name='nutripal-transcode-input', daemon=True)
    started = False
    try:
        worker.start()
        started = True
        deadline = time.monotonic() + 20
        first = True
        while not stop.is_set():
            if not select.select([process.stdout], [], [], 0.25)[0]:
                if time.monotonic() >= deadline:
                    raise VideoError('transcode_output_timeout')
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                code = process.wait(timeout=3)
                if code or errors or first:
                    raise VideoError(errors[0] if errors else 'transcode_failed')
                return
            if first:
                # FFmpeg emits an FLV header before any tags.
                if not chunk.startswith(b'FLV'):
                    raise VideoError('transcode_invalid_header')
                first = False
                _LOGGER.debug('NutriPal H264 output ready')
            deadline = time.monotonic() + 20
            yield chunk
    finally:
        local.set()
        if process.poll() is None:
            process.kill()
        process.wait()
        if started:
            worker.join(timeout=10)
        else:
            process.stdin.close()
        process.stdout.close()
        if worker.is_alive():
            # Native HTTP reads have an 8s socket timeout. Closing the outer
            # session also terminates the native producer if it is stuck.
            _LOGGER.warning('NutriPal transcoder input cleanup delayed')
