from homeassistant.components.button import ButtonEntity
from .const import DOMAIN
from .entity import NutriPalEntity

async def async_setup_entry(hass, entry, async_add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalButton(c, key) for key in ('feed_one','reset_calibration','acknowledge_manual')])

class NutriPalButton(NutriPalEntity, ButtonEntity):
    @property
    def available(self):
        if self.key == 'feed_one':
            return self.coordinator.last_update_success and bool(self.coordinator.options['manual_enabled']) and self.coordinator.data.get('manual_state') == 'ready'
        if self.key == 'acknowledge_manual':
            return self.coordinator.state['pending'] is not None
        return True

    async def async_press(self):
        if self.key == 'feed_one':
            await self.coordinator.async_feed_one()
        elif self.key == 'reset_calibration':
            await self.coordinator.async_reset_calibration()
        elif self.key == 'acknowledge_manual':
            await self.coordinator.async_acknowledge()
