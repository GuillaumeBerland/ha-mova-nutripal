"""Offline FFmpeg compatibility checks; optional synthetic encode test."""
import importlib
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch
from test_camera_transport import PACKAGE

transcode = importlib.import_module(PACKAGE + '.transcode')


class TranscodeTests(unittest.TestCase):
    def test_command_gop_audio_and_timestamps(self):
        args = transcode.ffmpeg_command('/usr/bin/ffmpeg')
        self.assertEqual(args[args.index('-g') + 1], '30')
        self.assertEqual(args[args.index('-c:v') + 1], 'libx264')
        self.assertEqual(args[args.index('-c:a') + 1], 'copy')
        self.assertNotIn('-copyts', args)

    def test_missing_executable(self):
        with patch.object(transcode.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(transcode.VideoError, 'ffmpeg_missing'):
                next(transcode.iter_h264_flv('unused', threading.Event()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools unavailable')
    def test_synthetic_input(self):
        # Exercise both pipes using a generated FLV; no live camera or files.
        source = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=160x120:rate=15', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=16000', '-t', '3',
            '-c:v', 'libx265', '-x265-params', 'pools=1:frame-threads=1',
            '-c:a', 'aac', '-output_ts_offset', '229342.432',
            '-f', 'flv', 'pipe:1'], capture_output=True, timeout=15)
        if source.returncode:
            self.skipTest('Enhanced HEVC FLV encoder unavailable in test environment')
        with patch.object(transcode, 'iter_enhanced_flv', return_value=iter([source.stdout])):
            output = b''.join(transcode.iter_h264_flv('unused', threading.Event()))
        probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries', 'stream=codec_name,nb_read_frames,start_time',
            '-of', 'default=noprint_wrappers=1', 'pipe:0'], input=output,
            capture_output=True, timeout=15, check=True)
        self.assertIn(b'codec_name=h264', probe.stdout)
        self.assertIn(b'nb_read_frames=45', probe.stdout)
        self.assertIn(b'codec_name=aac', probe.stdout)
        for line in probe.stdout.decode().splitlines():
            if line.startswith('start_time=') and line != 'start_time=N/A':
                self.assertLess(float(line.split('=')[1]), 1.0)
