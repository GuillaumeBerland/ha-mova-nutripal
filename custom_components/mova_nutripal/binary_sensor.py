from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN
from .entity import NutriPalEntity

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalBinary(coordinator, key) for key in ("online", "battery_present", "child_lock", "camera_enabled", "simulation", "has_warning", "has_fault", "calibration_enabled", "manual_enabled", "manual_pending")])

class NutriPalBinary(NutriPalEntity, BinarySensorEntity):
    @property
    def is_on(self):
        value = self.coordinator.data.get(self.key)
        return bool(value) if value in (0, 1) else None
