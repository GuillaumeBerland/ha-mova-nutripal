from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from .api import NutriPalAPI
from .const import DOMAIN
from .coordinator import NutriPalCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.BUTTON, Platform.CAMERA]

async def async_setup_entry(hass, entry):
    api = await hass.async_add_executor_job(NutriPalAPI, entry.data["username"], entry.data["password"])
    try:
        await hass.async_add_executor_job(api.discover, entry.data["did"])
        coordinator = NutriPalCoordinator(hass, entry, api)
        await coordinator.async_load_state()
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        await hass.async_add_executor_job(api.close)
        raise ConfigEntryNotReady(f"MOVA unavailable ({type(exc).__name__})") from None
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True

async def _reload(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        await coordinator.async_request_refresh()

async def async_unload_entry(hass, entry):
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_close()
    return True
