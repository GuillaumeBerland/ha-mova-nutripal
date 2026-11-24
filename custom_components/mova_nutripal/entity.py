from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

class NutriPalEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{coordinator.did}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.did)}, manufacturer="MOVA", model="NutriPal 10 Ultra", name="MOVA NutriPal")

    @property
    def available(self):
        return super().available and self.coordinator.data.get(self.key) is not None
