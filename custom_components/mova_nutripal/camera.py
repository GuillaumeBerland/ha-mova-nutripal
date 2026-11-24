"""Experimental still-image camera, disabled by default in the entity registry."""
import asyncio
import logging
import time

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .video import snapshot
from .cloud_video import VideoError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalCamera(coordinator, entry)])


class NutriPalCamera(Camera):
    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_entity_registry_enabled_default = False
    _attr_supported_features = CameraEntityFeature(0)  # No continuous stream in this first milestone.

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

    @property
    def available(self):
        data = self.coordinator.data or {}
        return (not self._closing and not self.coordinator.stopping
                and self.coordinator.last_update_success
                and data.get("online") is True and data.get("camera_enabled") == 1)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._coordinator_updated))

    def _coordinator_updated(self):
        if not self.available:
            self._last_image = None
        self.async_write_ha_state()

    async def _capture(self):
        try:
            image = await self.hass.async_add_executor_job(snapshot,
                self.entry.data["username"], self.entry.data["password"],
                self.coordinator.did,
                self.hass.config.path(".storage", "mova_nutripal_xp2p"))
            if self.available and self.hass.is_running:
                self._last_image = image
                return image
            return None
        except VideoError as exc:
            _LOGGER.warning("NutriPal camera capture failed (%s)", str(exc))
            return None
        except Exception:
            _LOGGER.warning("NutriPal camera capture failed (unexpected error)")
            return None
        finally:
            self._last_attempt = time.monotonic()

    async def async_camera_image(self, width=None, height=None):
        if not self.available or not self.hass.is_running:
            self._last_image = None
            return None
        if self._task is not None and not self._task.done():
            return await asyncio.shield(self._task)
        # Avoid repeated logins/session startup from an automatic thumbnail refresh.
        if self._last_attempt and time.monotonic() - self._last_attempt < 30:
            return self._last_image
        self._last_image = None
        self._task = self.hass.async_create_task(self._capture())
        return await asyncio.shield(self._task)

    async def async_will_remove_from_hass(self):
        self._closing = True
        self._last_image = None
        if self._task is not None and not self._task.done():
            await asyncio.shield(self._task)
        await super().async_will_remove_from_hass()
