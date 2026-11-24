"""Offline alpha.4 startup/cache tests; no real credentials or cloud calls."""
import asyncio
from dataclasses import replace
import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_camera_transport import PACKAGE, FakeCloud, cloud_video
from test_live_relay import SessionTests
_session_setup = SessionTests.setUp
del SessionTests


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = cloud_video.VideoAuthorizationCache()
        self.cloud = FakeCloud()
        self.clock = self.enterContext(patch.object(cloud_video.time, 'monotonic', return_value=100))
        self.wall = self.enterContext(patch.object(cloud_video.time, 'time', return_value=1_800_000_000))
        self.read = self.cloud._api_call
        self.expiry = 1_800_003_600

        def call(endpoint, params, **kwargs):
            response = self.read(endpoint, params, **kwargs)
            if endpoint.endswith('user/accesstoken'):
                response['data']['data']['expireAt'] = self.expiry
            return response
        self.cloud._api_call = call

    def get(self, did='did'):
        return self.cache.get_or_provision(self.cloud, did, 'model')

    def test_hit_and_maximum_ttl(self):
        first, hit = self.get()
        self.assertFalse(hit)
        self.assertEqual(first.cache_until, 160)
        self.clock.return_value = 159
        self.assertEqual(self.get(), (first, True))
        self.assertEqual(len(self.cloud.calls), 4)
        self.clock.return_value = 160
        self.assertFalse(self.get()[1])
        self.assertEqual(len(self.cloud.calls), 8)

    def test_millisecond_expiry_and_margin(self):
        self.expiry = 1_800_000_020_000
        identity, _ = self.get()
        self.assertEqual(identity.cache_until, 115)
        self.clock.return_value = 115
        self.assertFalse(self.get()[1])

    def test_unknown_or_expired_not_cached(self):
        for value in (None, '1800003600', 3600, 1_799_999_999, 1_800_000_004, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.cache.clear()
                self.expiry = value
                self.assertFalse(self.get()[1])
                self.assertFalse(self.get()[1])

    def test_clear_and_scope(self):
        self.get()
        self.cache.clear()
        self.assertFalse(self.get()[1])
        self.assertFalse(self.get('other-device')[1])
        self.cloud._uid = 'another-user'
        self.assertFalse(self.get('other-device')[1])

    def test_invalidation_during_fill(self):
        real_provision = cloud_video.provision
        def provision(*args):
            identity = real_provision(*args)
            self.cache.clear()
            return identity
        with patch.object(cloud_video, 'provision', side_effect=provision):
            with self.assertRaisesRegex(cloud_video.VideoError, 'video_authorization_invalidated'):
                self.get()
        self.assertFalse(self.get()[1])

    def test_denial_does_not_fill(self):
        self.cloud.allowed = False
        with self.assertRaisesRegex(cloud_video.VideoError, 'video_permission_denied'):
            self.get()
        self.cloud.allowed = True
        self.assertFalse(self.get()[1])


# Reuse the existing session fixture without inheriting its test methods.
class CachedSessionTests(unittest.TestCase):
    def setUp(self):
        _session_setup(self)
        self.video = importlib.import_module(PACKAGE + '.video')
        self.cache = cloud_video.VideoAuthorizationCache()
        self.provision.return_value = replace(self.identity, cache_until=float('inf'))
        self.args = ('test-user', 'test-password', 'did', '/test')
        self.p = self.enterContext(patch.object(cloud_video, 'provision', self.provision))

    def open(self):
        return self.video.open_video_session(*self.args, authorization_cache=self.cache)

    def test_reuse_still_checks_switch_and_closes(self):
        for _ in range(2):
            with self.open():
                pass
        self.assertEqual(self.provision.call_count, 1)
        self.assertEqual(self.api.discover.call_count, 2)
        self.assertEqual(self.api.cloud.send.call_count, 2)
        self.assertEqual(self.runtime.stop_live_stream.call_count, 2)
        self.api.cloud.send.return_value[0]['value'] = 0
        with self.assertRaisesRegex(cloud_video.VideoError, 'camera_off_or_unknown'):
            with self.open():
                self.fail('opened camera when off')
        self.api.cloud.send.return_value[0]['value'] = 1
        with self.open():
            pass
        self.assertEqual(self.provision.call_count, 2)

    def test_failed_native_start_invalidates_without_retry(self):
        with self.open():
            pass
        self.runtime.start_live_stream.side_effect = RuntimeError('private error')
        with self.assertRaisesRegex(cloud_video.VideoError, 'xp2p_connect'):
            with self.open():
                self.fail('native failure ignored')
        self.assertEqual(self.runtime.start_live_stream.call_count, 2)
        self.runtime.start_live_stream.side_effect = None
        with self.open():
            pass
        self.assertEqual(self.provision.call_count, 2)


class PriorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        class FakeCamera:
            def __init__(self):
                self.stream = None
        modules = {}
        for name, attrs in (
            ('homeassistant', {}), ('homeassistant.components', {}),
            ('homeassistant.components.camera', {'Camera': FakeCamera,
                'CameraEntityFeature': types.SimpleNamespace(STREAM=1)}),
            ('homeassistant.helpers', {}),
            ('homeassistant.helpers.device_registry', {'DeviceInfo': Mock()}),
            ('homeassistant.const', {'EVENT_HOMEASSISTANT_STOP': 'stop'}),
            (PACKAGE + '.const', {'DOMAIN': 'mova_nutripal'}),
        ):
            modules[name] = types.ModuleType(name)
            vars(modules[name]).update(attrs)
        with patch.dict(sys.modules, modules):
            self.module = importlib.import_module(PACKAGE + '.camera')
        self.coordinator = types.SimpleNamespace(did='test', stopping=False,
            last_update_success=True, data={'online': True, 'camera_enabled': 1})
        self.camera = self.module.NutriPalCamera(self.coordinator, Mock())
        self.camera._relay = Mock(active=False)
        self.camera._video_args = ('user', 'password', 'did', '/test')
        self.camera.hass = types.SimpleNamespace(is_running=True,
            async_add_executor_job=AsyncMock(return_value=b'jpeg'), async_create_task=asyncio.create_task)

    def stream(self):
        return types.SimpleNamespace(outputs=lambda: {'hls': object()},
            async_get_image=AsyncMock(return_value=b'live-jpeg'))

    async def test_provider_starting_uses_live_keyframe(self):
        self.camera.stream = self.stream()
        self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_poster_grace_allows_live_to_arrive(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def sleep(_):
            started.set()
            await release.wait()
        with patch.object(self.module.asyncio, 'sleep', side_effect=sleep):
            task = asyncio.create_task(self.camera.async_camera_image())
            await started.wait()
            self.camera.stream = self.stream()
            release.set()
            self.assertEqual(await task, b'live-jpeg')
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_standalone_snapshot_still_works_and_coalesces(self):
        with patch.object(self.module, 'SNAPSHOT_GRACE', 0):
            images = await asyncio.gather(self.camera.async_camera_image(),
                                          self.camera.async_camera_image())
        self.assertEqual(images, [b'jpeg', b'jpeg'])
        self.camera.hass.async_add_executor_job.assert_awaited_once()
        self.assertEqual(await self.camera.async_camera_image(), b'jpeg')

    async def test_disable_during_grace_skips_capture(self):
        async def sleep(_):
            self.coordinator.data['camera_enabled'] = 0
        with patch.object(self.module.asyncio, 'sleep', side_effect=sleep):
            self.assertIsNone(await self.camera.async_camera_image())
        self.camera.hass.async_add_executor_job.assert_not_awaited()

    async def test_live_image_cached_after_disconnect(self):
        self.camera.stream = self.stream()
        self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
        self.camera.stream = None
        self.assertEqual(await self.camera.async_camera_image(), b'live-jpeg')
        self.camera.hass.async_add_executor_job.assert_not_awaited()




class RelayInvalidationTests(unittest.TestCase):
    def test_disable_close_and_capture_error_invalidate(self):
        relay_module = importlib.import_module(PACKAGE + '.live_relay')
        clear = Mock()
        relay = relay_module.LiveRelay(Mock(), invalidate_authorization=clear)
        self.addCleanup(relay.close)
        relay.set_enabled(True)
        clear.assert_not_called()
        with self.assertRaisesRegex(cloud_video.VideoError, 'expected'):
            relay.capture(Mock(side_effect=cloud_video.VideoError('expected')))
        self.assertEqual(clear.call_count, 1)
        relay.set_enabled(False)
        self.assertEqual(clear.call_count, 2)
        relay.close()
        self.assertEqual(clear.call_count, 3)
