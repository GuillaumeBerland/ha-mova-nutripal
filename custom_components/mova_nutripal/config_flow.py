import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from .api import NutriPalAPI
from .const import DOMAIN, DEFAULTS

class NutriPalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NutriPalOptions()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            def validate():
                api = NutriPalAPI(user_input["username"], user_input["password"])
                try:
                    device = api.discover()
                    return str(device["did"])
                finally:
                    api.close()
            try:
                did = await self.hass.async_add_executor_job(validate)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(did)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="MOVA NutriPal 10 Ultra", data={**user_input, "did": did})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("username"): str, vol.Required("password"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}), errors=errors)

class NutriPalOptions(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        values = {**DEFAULTS, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("target", default=values["target"]): vol.All(vol.Coerce(int), vol.Range(min=10, max=500)),
            vol.Required("portion_weight", default=values["portion_weight"]): vol.All(vol.Coerce(float), vol.Range(min=1, max=30)),
            vol.Required("threshold", default=values["threshold"]): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
            vol.Required("max_complement", default=values["max_complement"]): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
            vol.Required("manual_enabled", default=values["manual_enabled"]): bool,
            vol.Required("auto_calibration", default=values["auto_calibration"]): bool,
            vol.Required("video_codec", default=values.get("video_codec", "h264")): vol.In(["h264", "hevc"]),
        }))
