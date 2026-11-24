"""Offline cancellation and cleanup regression tests."""
import importlib
import threading
import unittest
from unittest.mock import MagicMock, patch

from test_camera_transport import PACKAGE, HEADER, cloud_video
from test_live_relay import RelayTests, SessionTests
from test_camera_startup import PriorityTests

_relay_setup, _connect = RelayTests.setUp, RelayTests.connect
_session_setup = SessionTests.setUp
_priority_setup = PriorityTests.setUp
# Do not let unittest discover imported TestCase classes a second time.
del RelayTests, SessionTests, PriorityTests
relay_module = importlib.import_module(PACKAGE + '.live_relay')
video = importlib.import_module(PACKAGE + '.video')
VideoCancelled = cloud_video.VideoCancelled
VideoError = cloud_video.VideoError


class PreemptionTests(unittest.TestCase):
    setUp = _relay_setup
    connect = _connect

    def test_live_cancels_snapshot_and_waits_for_cleanup(self):
        entered, cancelled, finish = (threading.Event() for _ in range(3))
        errors, results = [], []
        def snapshot(*, stopped):
            entered.set()
            if not stopped.wait(2):
                raise AssertionError('no cancellation')
            cancelled.set()
            if not finish.wait(2):
                raise AssertionError('no cleanup release')
            raise VideoCancelled('snapshot_cancelled')
        def capture():
            try:
                self.relay.capture(snapshot, cancellable=True)
            except Exception as exc:
                errors.append(exc)
        def live():
            _, response = self.connect()
            results.append((response.status, response.read()))
        snap = threading.Thread(target=capture)
        snap.start()
        with patch.object(relay_module, 'iter_enhanced_flv', return_value=(x for x in [HEADER])):
            reader = threading.Thread(target=live)
            try:
                self.assertTrue(entered.wait(1))
                reader.start()
                self.assertTrue(cancelled.wait(1))
                self.assertEqual(self.opens, 0)
                self.assertTrue(self.relay.active)
            finally:
                finish.set()
                snap.join(3)
                if reader.ident is not None:
                    reader.join(3)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], VideoCancelled)
        self.assertEqual(results, [(200, HEADER)])
        self.assertEqual((self.opens, self.closes), (1, 1))
        self.assertEqual(self.relay._retry_after, 0)

    def test_cancelled_snapshot_does_not_clear_authorization(self):
        clear = MagicMock()
        self.relay._invalidate_authorization = clear
        def cancel(*, stopped):
            stopped.set()
            raise VideoCancelled('snapshot_cancelled')
        with self.assertRaises(VideoCancelled):
            self.relay.capture(cancel, cancellable=True)
        clear.assert_not_called()
        self.assertEqual(self.relay.capture(lambda: b'jpeg'), b'jpeg')

    def test_disable_signals_snapshot(self):
        entered, exited = threading.Event(), threading.Event()
        errors = []
        def capture(*, stopped):
            entered.set()
            if not stopped.wait(2):
                raise AssertionError('disable did not cancel')
            raise VideoCancelled('snapshot_cancelled')
        def run():
            try:
                self.relay.capture(capture, cancellable=True)
            except Exception as exc:
                errors.append(exc)
            finally:
                exited.set()
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.relay.set_enabled(False)
            self.assertTrue(exited.wait(1))
        finally:
            thread.join(3)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], VideoCancelled)
        self.assertIsNone(self.relay.start())

    def test_cleanup_failure_blocks_later_sessions(self):
        url = self.relay.start()
        self.assertIsNotNone(url)
        with self.assertRaisesRegex(VideoError, 'xp2p_cleanup'):
            self.relay.capture(MagicMock(side_effect=VideoError('xp2p_cleanup')))
        self.relay.set_enabled(True)
        with patch.object(relay_module, 'monotonic', return_value=self.relay._retry_after + 10):
            self.assertIsNone(self.relay.start())
            with self.assertRaisesRegex(VideoError, 'xp2p_cleanup'):
                self.relay.capture(lambda: self.fail('opened another snapshot'))
        self.assertEqual(self.opens, 0)


    def test_waiting_live_refused_when_snapshot_cleanup_fails(self):
        entered = threading.Event()
        errors, statuses = [], []
        def snapshot(*, stopped):
            entered.set()
            if not stopped.wait(2):
                raise AssertionError('no cancellation')
            raise VideoError('xp2p_cleanup')
        def capture():
            try:
                self.relay.capture(snapshot, cancellable=True)
            except Exception as exc:
                errors.append(exc)
        def live():
            _, response = self.connect()
            statuses.append(response.status)
            response.read()
        snap = threading.Thread(target=capture)
        snap.start()
        reader = threading.Thread(target=live)
        try:
            self.assertTrue(entered.wait(1))
            reader.start()
        finally:
            snap.join(3)
            if reader.ident is not None:
                reader.join(3)
        self.assertEqual(statuses, [503])
        self.assertEqual(len(errors), 1)
        self.assertEqual(str(errors[0]), 'xp2p_cleanup')
        self.assertEqual(self.opens, 0)
        self.assertTrue(self.relay._cleanup_failed)


class SessionCancellationTests(unittest.TestCase):
    setUp = _session_setup

    def session_context(self, stopped, **kwargs):
        return video.open_video_session('test-user', 'test-password', 'did', '/test',
                                        stopped=stopped, **kwargs)

    def test_cancel_during_login_skips_native_and_closes_cloud(self):
        stopped = threading.Event()
        self.api.discover.side_effect = lambda *_: stopped.set()
        with self.assertRaises(VideoCancelled):
            with self.session_context(stopped):
                self.fail('opened camera')
        self.api.close.assert_called_once()
        self.api.cloud.send.assert_not_called()
        self.runtime.start_live_stream.assert_not_called()

    def test_cancel_during_provision_preserves_cache(self):
        stopped = threading.Event()
        cache = MagicMock()
        def provision(*_):
            stopped.set()
            return self.identity, False
        cache.get_or_provision.side_effect = provision
        with self.assertRaises(VideoCancelled):
            with self.session_context(stopped, authorization_cache=cache):
                self.fail('opened camera')
        self.api.close.assert_called_once()
        self.runtime.start_live_stream.assert_not_called()
        cache.clear.assert_not_called()

    def test_cancel_during_native_start_closes_before_return(self):
        stopped = threading.Event()
        def start(*_, **__):
            stopped.set()
            return self.session
        self.runtime.start_live_stream.side_effect = start
        with self.assertRaises(VideoCancelled):
            with self.session_context(stopped):
                self.fail('opened consumer')
        self.runtime.stop_live_stream.assert_called_once_with(self.session)
        self.api.close.assert_called_once()

    def test_cleanup_failure_not_hidden_by_cancellation(self):
        stopped = threading.Event()
        self.runtime.stop_live_stream.side_effect = RuntimeError('private')
        with self.assertRaisesRegex(VideoError, 'xp2p_cleanup') as error:
            with self.session_context(stopped):
                stopped.set()
                raise VideoCancelled('snapshot_cancelled')
        self.assertNotIsInstance(error.exception, VideoCancelled)

    def test_jpeg_cancels_before_opening_http(self):
        stopped = threading.Event()
        stopped.set()
        with patch.object(video.http.client, 'HTTPConnection') as http:
            with self.assertRaises(VideoCancelled):
                video.capture_jpeg('http://127.0.0.1:1/live', 'ffmpeg', stopped=stopped)
        http.assert_not_called()

    def test_jpeg_cancel_during_read_kills_ffmpeg_and_closes_http(self):
        stopped = threading.Event()
        process = MagicMock()
        process.poll.return_value = None
        process.stdin.fileno.return_value = 123
        def read(_):
            stopped.set()
            return HEADER
        with patch.object(video.http.client, 'HTTPConnection') as http, \
             patch.object(video.subprocess, 'Popen', return_value=process), \
             patch.object(video.os, 'set_blocking'):
            response = http.return_value.getresponse.return_value
            response.status = 200
            response.read1.side_effect = read
            with self.assertRaises(VideoCancelled):
                video.capture_jpeg('http://127.0.0.1:1/live', 'ffmpeg', stopped=stopped)
        process.stdin.close.assert_called_once()
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        http.return_value.close.assert_called_once()


class CameraHandoffTests(unittest.IsolatedAsyncioTestCase):
    setUp = _priority_setup

    async def test_cancelled_snapshot_returns_live_keyframe(self):
        async def executor(*_):
            self.camera._relay.active = True
            self.camera.stream = type('Stream', (), {})()
            self.camera.stream.async_get_image = unittest.mock.AsyncMock(side_effect=AssertionError('would start HLS'))
            self.camera.stream._keyframe_converter = type('Converter', (), {})()
            self.camera.stream._keyframe_converter.async_get_image = unittest.mock.AsyncMock(return_value=b'live-jpeg')
            raise VideoCancelled('snapshot_cancelled')
        self.camera.hass.async_add_executor_job.side_effect = executor
        with patch.object(self.module, 'SNAPSHOT_GRACE', 0):
            self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
        self.assertEqual(self.camera._last_image, b'live-jpeg')
        self.camera.hass.async_add_executor_job.assert_awaited_once()
