"""Offline tests: local loopback only, fake native video sessions."""
from contextlib import contextmanager
import http.client
import io
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from test_camera_transport import PACKAGE, HEADER, tag
import importlib

relay_module = importlib.import_module(PACKAGE + '.live_relay')
video = importlib.import_module(PACKAGE + '.video')
VideoError = importlib.import_module(PACKAGE + '.cloud_video').VideoError


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.opens = 0
        self.closes = 0
        self.entered = threading.Event()
        self.exited = threading.Event()

        @contextmanager
        def factory():
            self.opens += 1
            self.entered.set()
            try:
                yield 'http://127.0.0.1:1/native'
            finally:
                self.closes += 1
                self.exited.set()

        self.relay = relay_module.LiveRelay(factory)
        self.relay.set_enabled(True)
        self.addCleanup(self.relay.close)

    def connect(self, path=None):
        url = urlsplit(self.relay.start())
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
        self.addCleanup(conn.close)
        conn.request('GET', path if path is not None else url.path)
        return conn, conn.getresponse()

    def test_lazy_stable_loopback(self):
        first = self.relay.start()
        self.assertEqual(first, self.relay.start())
        self.assertEqual(urlsplit(first).hostname, '127.0.0.1')
        self.assertEqual(self.opens, 0)
        self.assertFalse(self.relay.active)

    def test_unknown_path_does_not_open(self):
        _, response = self.connect('/wrong/live.flv')
        self.assertEqual(response.status, 404)
        self.assertEqual(self.opens, 0)

    def test_disabled_does_not_bind_or_open(self):
        self.relay.set_enabled(False)
        self.assertIsNone(self.relay.start())
        self.assertEqual(self.opens, 0)
        with self.assertRaisesRegex(VideoError, 'camera_off_or_unknown'):
            self.relay.capture(lambda: self.fail('capture invoked'))

    def test_bytes_relay_and_cleanup(self):
        data = tag(9, b'\x90hvc1abc')
        def packets(*_):
            yield HEADER
            yield data
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets):
            _, response = self.connect()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'video/x-flv')
            self.assertEqual(response.read(), HEADER + data)
            self.assertTrue(self.exited.wait(2))
        self.assertEqual((self.opens, self.closes), (1, 1))

    def test_single_reader_and_snapshot_exclusion(self):
        def packets(_, stopped):
            yield HEADER
            stopped.wait(3)
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets):
            _, first = self.connect()
            self.assertEqual(first.status, 200)
            self.assertEqual(first.read(len(HEADER)), HEADER)
            self.assertTrue(self.relay.active)
            _, second = self.connect()
            self.assertEqual(second.status, 503)
            with self.assertRaisesRegex(VideoError, 'video_busy'):
                self.relay.capture(lambda: self.fail('second native session'))
            self.relay.set_enabled(False)
            self.assertTrue(self.exited.wait(2))
        self.assertEqual((self.opens, self.closes), (1, 1))

    def test_reconnect_starts_a_fresh_session(self):
        def packets(*_):
            yield HEADER
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets):
            for _ in range(2):
                _, response = self.connect()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), HEADER)
        self.assertEqual((self.opens, self.closes), (2, 2))

    def test_close_stops_active_reader(self):
        def packets(_, stopped):
            yield HEADER
            stopped.wait(3)
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets):
            _, response = self.connect()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(len(HEADER)), HEADER)
            self.relay.close()
            self.assertTrue(self.exited.is_set())
            self.assertFalse(self.relay.active)
        self.assertEqual((self.opens, self.closes), (1, 1))

    def test_snapshot_gate_released_on_failure(self):
        def fail():
            raise VideoError('expected')
        with self.assertRaisesRegex(VideoError, 'expected'):
            self.relay.capture(fail)
        self.assertEqual(self.relay.capture(lambda: b'jpeg'), b'jpeg')

    def test_close_idempotent(self):
        self.relay.start()
        self.relay.close()
        self.relay.close()
        self.relay.set_enabled(True)
        self.assertIsNone(self.relay.start())

    def test_native_failure_before_headers(self):
        def packets(*_):
            raise VideoError('video_http_status')
            yield b''
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets):
            with self.assertLogs(relay_module.__name__, level='WARNING'):
                _, response = self.connect()
            self.assertEqual(response.status, 503)
            self.assertTrue(self.exited.wait(2))


class NativeReaderTests(unittest.TestCase):
    def test_conversion_on_reader_and_connection_closed(self):
        from unittest.mock import MagicMock
        raw = HEADER + tag(9, b'\x1c\x00\x00\x00\x00abc')
        response = MagicMock(status=200)
        response.read1.side_effect = io.BytesIO(raw).read
        with patch.object(video.http.client, 'HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            reader = video.iter_enhanced_flv('http://127.0.0.1:1234/live', threading.Event())
            self.assertEqual(next(reader), HEADER)
            self.assertEqual(next(reader), tag(9, b'\x90hvc1abc'))
            with self.assertRaises(EOFError):
                next(reader)
            connection.return_value.close.assert_called_once()


class SessionTests(unittest.TestCase):
    def setUp(self):
        import sys
        import types
        from unittest.mock import MagicMock
        self.api = MagicMock()
        self.api.cloud.send.return_value = [
            {'siid': 1000, 'piid': 1, 'code': 0, 'value': 1}
        ]
        self.runtime = MagicMock()
        self.session = self.runtime.start_live_stream.return_value
        self.session.stream_url = 'http://127.0.0.1:1234/native'
        self.assets = MagicMock()
        self.assets.startup_probe = {'ready': True}
        self.identity = importlib.import_module(PACKAGE + '.cloud_video').VideoIdentity(
            'device', 'product', 'name', 'test-id', 'test-key', 'p2p')

        def module(suffix, **attrs):
            name = PACKAGE + suffix
            obj = types.ModuleType(name)
            vars(obj).update(attrs)
            return name, obj
        entries = dict([
            module('.api', NutriPalAPI=MagicMock(return_value=self.api)),
            module('.const', MODEL='test-model'),
            module('.xp2p', __path__=[]),
            module('.xp2p.models', DreameLawnMowerCameraStreamRuntimeInputs=MagicMock()),
            module('.xp2p.xp2p_host_runtime', DreameLawnMowerXp2pHostRuntime=MagicMock(return_value=self.runtime)),
            module('.xp2p.xp2p_runtime_bootstrap', ensure_xp2p_host_runtime=MagicMock(return_value=self.assets)),
        ])
        self.enterContext(patch.dict(sys.modules, entries))
        self.provision = self.enterContext(patch.object(video, 'provision', return_value=self.identity))

    def test_context_closes_on_consumer_disconnect(self):
        with self.assertRaises(BrokenPipeError):
            with video.open_video_session('test-user', 'test-password', 'did', '/test') as url:
                self.assertEqual(url, self.session.stream_url)
                raise BrokenPipeError()
        self.runtime.stop_live_stream.assert_called_once_with(self.session)
        self.api.close.assert_called_once()

    def test_disabled_camera_never_opens_native_session(self):
        self.api.cloud.send.return_value[0]['value'] = 0
        with self.assertRaisesRegex(VideoError, 'camera_off_or_unknown'):
            with video.open_video_session('test-user', 'test-password', 'did', '/test'):
                self.fail('camera opened')
        self.provision.assert_not_called()
        self.runtime.start_live_stream.assert_not_called()
        self.api.close.assert_called_once()
