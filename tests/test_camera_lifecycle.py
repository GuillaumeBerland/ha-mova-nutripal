"""Offline lifecycle regression tests for alpha.6 (no cloud or SDK)."""
from contextlib import contextmanager
import importlib
import threading
import unittest
from unittest.mock import patch

from test_camera_transport import PACKAGE, HEADER
from test_camera_startup import PriorityTests
from test_live_relay import RelayTests

_priority_setup = PriorityTests.setUp
_stream = PriorityTests.stream
_relay_setup, _connect = RelayTests.setUp, RelayTests.connect
del PriorityTests, RelayTests
relay_module = importlib.import_module(PACKAGE + '.live_relay')
VideoError = importlib.import_module(PACKAGE + '.cloud_video').VideoError


class PassiveImageTests(unittest.IsolatedAsyncioTestCase):
    setUp = _priority_setup
    stream = _stream

    async def test_live_keyframe_never_calls_hls_starting_method(self):
        self.camera.stream = self.stream()
        self.assertEqual(await self.camera.async_camera_image(320, 480), b'live-jpeg')
        self.camera.stream._keyframe_converter.async_get_image.assert_awaited_once_with(
            width=320, height=480, wait_for_next_keyframe=False)
        self.camera.stream.async_get_image.assert_not_awaited()
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_pending_provider_does_not_start_worker_or_snapshot(self):
        self.camera.stream = self.stream()
        self.camera._relay.active = False
        self.assertIsNone(await self.camera.async_camera_image())
        self.camera.stream._keyframe_converter.async_get_image.assert_not_awaited()
        self.camera.stream.async_get_image.assert_not_awaited()
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_missing_private_converter_uses_cache_not_public_method(self):
        self.camera.stream = self.stream()
        del self.camera.stream._keyframe_converter
        self.camera._remember_image(b'cached-jpeg')
        self.assertEqual(await self.camera.async_camera_image(), b'cached-jpeg')
        self.camera.stream.async_get_image.assert_not_awaited()
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_converter_failure_uses_cache(self):
        self.camera.stream = self.stream()
        self.camera.stream._keyframe_converter.async_get_image.side_effect = RuntimeError('unavailable')
        self.camera._remember_image(b'cached-jpeg')
        self.assertEqual(await self.camera.async_camera_image(), b'cached-jpeg')
        self.camera.stream.async_get_image.assert_not_awaited()

    async def test_unchanged_keyframe_does_not_extend_cache(self):
        self.camera.stream = self.stream()
        with patch.object(self.module.time, 'monotonic', return_value=100) as clock:
            self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
            clock.return_value = 129
            self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
            self.assertEqual(self.camera._last_image_at, 100)
            clock.return_value = 131
            self.camera._relay.active = False
            self.camera.stream = None
            with patch.object(self.module, 'SNAPSHOT_GRACE', 0):
                self.assertEqual(await self.camera.async_camera_image(), b'jpeg')
            self.camera.hass.async_add_executor_job.assert_awaited_once()

    async def test_teardown_during_passive_read_does_not_restart(self):
        self.camera.stream = self.stream()
        self.camera._remember_image(b'cached-jpeg')
        async def finish(**_):
            self.camera._relay.active = False
            return b'late-jpeg'
        self.camera.stream._keyframe_converter.async_get_image.side_effect = finish
        self.assertEqual(await self.camera.async_camera_image(), b'cached-jpeg')
        self.camera.stream.async_get_image.assert_not_awaited()
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_disable_during_passive_read_returns_no_image(self):
        self.camera.stream = self.stream()
        self.camera._remember_image(b'cached-jpeg')
        async def finish(**_):
            self.coordinator.data['camera_enabled'] = 0
            return b'late-jpeg'
        self.camera.stream._keyframe_converter.async_get_image.side_effect = finish
        self.assertIsNone(await self.camera.async_camera_image())


class ReconnectTests(unittest.TestCase):
    setUp = _relay_setup
    connect = _connect

    def handoff(self, *, fail=False, disable=False):
        closing = threading.Event()
        release = threading.Event()
        waiting = threading.Event()
        results = []
        errors = []
        @contextmanager
        def factory():
            self.opens += 1
            try:
                yield 'http://127.0.0.1:1/native'
            finally:
                if self.opens == 1:
                    closing.set()
                    if not release.wait(3):
                        raise AssertionError('cleanup not released')
                    if fail:
                        raise VideoError('xp2p_cleanup')
                self.closes += 1
        self.relay._session_factory = factory
        original_wait = self.relay._state_changed.wait_for
        def signal_wait(*args, **kwargs):
            waiting.set()
            return original_wait(*args, **kwargs)
        def reconnect():
            try:
                _, response = self.connect()
                results.append((response.status, response.read()))
            except Exception as exc:
                errors.append(exc)
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=lambda *_: (x for x in [HEADER])), \
             patch.object(self.relay._state_changed, 'wait_for', side_effect=signal_wait):
            _, first = self.connect()
            self.assertEqual(first.status, 200)
            self.assertTrue(closing.wait(1))
            reader = threading.Thread(target=reconnect)
            reader.start()
            try:
                self.assertTrue(waiting.wait(1))
                self.assertEqual(self.opens, 1)
                if disable:
                    self.relay.set_enabled(False)
            finally:
                release.set()
                reader.join(4)
            self.assertFalse(reader.is_alive())
            self.assertEqual(first.read(), HEADER)
        self.assertEqual(errors, [])
        return results

    def test_immediate_reconnect_waits_for_cleanup_and_succeeds(self):
        self.assertEqual(self.handoff(), [(200, HEADER)])
        self.assertEqual((self.opens, self.closes), (2, 2))
        self.assertEqual(self.relay._retry_after, 0)

    def test_cleanup_failure_refuses_waiting_reader(self):
        with self.assertLogs(relay_module.__name__, level='WARNING'):
            results = self.handoff(fail=True)
        self.assertEqual([status for status, _ in results], [503])
        self.assertEqual(self.opens, 1)
        self.assertTrue(self.relay._cleanup_failed)

    def test_disable_refuses_waiting_reader(self):
        results = self.handoff(disable=True)
        self.assertEqual([status for status, _ in results], [503])
        self.assertEqual((self.opens, self.closes), (1, 1))

    def test_existing_viewer_not_evicted_on_duplicate_request(self):
        release = threading.Event()
        def packets(_, stopped):
            yield HEADER
            release.wait(3)
            if not stopped.is_set():
                yield b'still-active'
        with patch.object(relay_module, 'iter_enhanced_flv', side_effect=packets), \
             patch.object(relay_module, 'RECONNECT_WAIT', 0.05):
            _, first = self.connect()
            try:
                _, duplicate = self.connect()
                self.assertEqual(duplicate.status, 503)
                duplicate.read()
                self.assertEqual(self.opens, 1)
                self.assertFalse(self.relay._stopped.is_set())
            finally:
                release.set()
            self.assertEqual(first.read(), HEADER + b'still-active')
        self.assertEqual((self.opens, self.closes), (1, 1))
        self.assertEqual(self.relay._retry_after, 0)
