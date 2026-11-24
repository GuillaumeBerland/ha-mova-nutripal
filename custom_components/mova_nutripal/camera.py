"""Experimental JPEG and native HLS camera, disabled by default."""
import asyncio
import logging
import time
from functools import partial

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from .const import DOMAIN
from .video import open_video_session, snapshot
from .live_relay import LiveRelay
from .cloud_video import VideoAuthorizationCache, VideoCancelled, VideoError

_LOGGER = logging.getLogger(__name__)
SNAPSHOT_GRACE = 0.75


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalCamera(coordinator, entry)])


class NutriPalCamera(Camera):
    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_entity_registry_enabled_default = False
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator, entry):
        super().__init__()
        self.coordinator = coordinator
        self.entry = entry
        self._attr_unique_id = f"{coordinator.did}_camera_snapshot"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.did)},
            manufacturer="MOVA", model="NutriPal 10 Ultra", name="MOVA NutriPal")
        self._task = None
        self._last_attempt = 0.0
        self._last_image = None
        self._closing = False
        self._relay = None
        self._authorization_cache = VideoAuthorizationCache()

    @property
    def available(self):
        data = self.coordinator.data or {}
        return (not self._closing and not self.coordinator.stopping
                and self.coordinator.last_update_success
                and data.get("online") is True and data.get("camera_enabled") == 1)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._video_args = (self.entry.data["username"], self.entry.data["password"],
                            self.coordinator.did,
                            self.hass.config.path(".storage", "mova_nutripal_xp2p"))
        self._relay = LiveRelay(
            partial(open_video_session, *self._video_args,
                    authorization_cache=self._authorization_cache),
            codec=self.entry.options.get("video_codec", "h264"),
            invalidate_authorization=self._authorization_cache.clear)
        self._relay.set_enabled(self.available)
        self.async_on_remove(self.coordinator.async_add_listener(self._coordinator_updated))
        self.async_on_remove(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_stop))

    def _coordinator_updated(self):
        if self._relay is not None:
            self._relay.set_codec(self.entry.options.get("video_codec", "h264"))
            self._relay.set_enabled(self.available)
        if not self.available:
            self._last_image = None
        self.async_write_ha_state()

    def _live_requested(self):
        # HA registers a provider before starting its HTTP reader. Detect this
        # early, not only after the relay receives the GET.
        return self._relay.active or (self.stream is not None and bool(self.stream.outputs()))

    async def _live_image(self, width=None, height=None):
        if self.stream is not None:
            try:
                image = await self.stream.async_get_image(
                    width=width, height=height, wait_for_next_keyframe=False)
                if self.available and image:
                    self._last_image = image
                    self._last_attempt = time.monotonic()
                    return image
            except Exception:
                _LOGGER.debug("NutriPal live keyframe not available")
        if self.available and self._last_attempt and time.monotonic() - self._last_attempt < 30:
            return self._last_image
        return None

    async def _capture(self):
        # A poster request often arrives just before HA requests HLS. Give
        # that reader a short head start, without opening a remote session.
        await asyncio.sleep(SNAPSHOT_GRACE)
        if not self.available or not self.hass.is_running:
            return None
        if self._live_requested():
            _LOGGER.debug("NutriPal standalone snapshot skipped for live stream")
            return await self._live_image()
        try:
            image = await self.hass.async_add_executor_job(
                partial(self._relay.capture,
                        partial(snapshot, *self._video_args,
                                authorization_cache=self._authorization_cache),
                        cancellable=True))
            if self.available and self.hass.is_running:
                self._last_image = image
                return image
            return None
        except VideoCancelled:
            # The executor has finished cleaning up before returning. HA can
            # now supply the poster from the live reader rather than a new session.
            if self.available and self._live_requested():
                return await self._live_image()
            return None
        except VideoError as exc:
            if str(exc) == "video_busy" and self.available and self._live_requested():
                return await self._live_image()
            _LOGGER.warning("NutriPal camera capture failed (%s)", str(exc))
            return None
        except Exception:
            _LOGGER.warning("NutriPal camera capture failed (unexpected error)")
            return None
        finally:
            self._last_attempt = time.monotonic()

    async def stream_source(self):
        """Return a stable local URL without waiting for MOVA/XP2P startup."""
        if not self.available or self._relay is None or not self.hass.is_running:
            return None
        return await self.hass.async_add_executor_job(self._relay.start)

    async def async_camera_image(self, width=None, height=None):
        if not self.available or not self.hass.is_running:
            self._last_image = None
            return None
        if self._relay is None:
            return None
        if self._live_requested():
            return await self._live_image(width, height)
        if self._task is not None and not self._task.done():
            return await asyncio.shield(self._task)
        # Avoid repeated logins/session startup from an automatic thumbnail refresh.
        if self._last_attempt and time.monotonic() - self._last_attempt < 30:
            return self._last_image
        self._last_image = None
        self._task = self.hass.async_create_task(self._capture())
        return await asyncio.shield(self._task)

    async def _async_stop(self, _event=None):
        self._closing = True
        self._last_image = None
        if self._relay is not None:
            self._relay.set_enabled(False)
        if self._task is not None and not self._task.done():
            await asyncio.shield(self._task)
        if self._relay is not None:
            await self.hass.async_add_executor_job(self._relay.close)

    async def async_will_remove_from_hass(self):
        await self._async_stop()
        await super().async_will_remove_from_hass()
