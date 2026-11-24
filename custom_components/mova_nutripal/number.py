from homeassistant.components.number import NumberEntity, NumberMode
from .const import DOMAIN
from .entity import NutriPalEntity

SETTINGS = {
    'target_setting': ('target',10,500,1,'g'),
    'reference_setting': ('portion_weight',1,30,0.1,'g'),
    'threshold_setting': ('threshold',0,30,1,'g'),
    'max_setting': ('max_complement',1,3,1,None),
}

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Setting(hass.data[DOMAIN][entry.entry_id], key) for key in SETTINGS])

class Setting(NutriPalEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    def __init__(self, coordinator, key):
        super().__init__(coordinator,key)
        self.option, self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step, self._attr_native_unit_of_measurement = SETTINGS[key]

    @property
    def native_value(self):
        return self.coordinator.options[self.option]

    async def async_set_native_value(self, value):
        if not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError('Outside allowed range')
        value = float(value) if self.option == 'portion_weight' else int(value)
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, self.option:value})
        self.async_write_ha_state()
