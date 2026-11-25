from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_platform, config_validation as cv
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol
from math import isfinite
from .const import DOMAIN
from .entity import NutriPalEntity

GRAMS = ("intake_today", "intake_yesterday", "bowl_weight", "configured_weight", "calibration_weight", "estimated_distributed", "forecast", "budget", "target", "measured_weight", "compensated_weight", "daily_reconstructed", "daily_portion_weight", "daily_difference", "daily_corrected_forecast", "physical_reference", "scheduled_daily_weight")
COUNTS = ("meals_today", "meals_yesterday", "portions_today", "portions_yesterday", "supplement_remaining", "remaining_portions", "suggested_portions", "calibration_samples", "compensated_samples", "daily_history_count", "scheduled_daily_portions")
OTHER = ("device_status", "warning_mask", "fault_mask", "feeding_mode", "sd_card_status", "decision", "battery", "desiccant_days", "status_text", "manual_state", "manual_result", "next_meal", "next_meal_portions", "daily_quality")
DIAGNOSTIC = {"device_status", "warning_mask", "fault_mask", "feeding_mode", "sd_card_status", "supplement_remaining", "configured_weight", "compensated_weight", "compensated_samples", "physical_reference"}

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalSensor(coordinator, key) for key in GRAMS + COUNTS + OTHER])
    entity_platform.async_get_current_platform().async_register_entity_service(
        'add_calibration_measurement', {
            vol.Required('measurement_date'): cv.date,
            vol.Required('portions'): vol.All(_whole_number, vol.Range(min=1, max=100)),
            vol.Required('daily_counter'): vol.All(_whole_number, vol.Range(min=1, max=10000)),
            vol.Required('weight_before'): vol.All(_weight, vol.Range(min=0, max=10000)),
            vol.Required('weight_after'): vol.All(_weight, vol.Range(min=0, max=10000)),
            vol.Required('confirmed'): cv.boolean,
        }, 'async_add_calibration_measurement')
    entity_platform.async_get_current_platform().async_register_entity_service(
        'mark_feeding_day', {
            vol.Required('measurement_date'): cv.date,
            vol.Required('reason'): vol.All(str, vol.Length(min=1, max=120)),
        }, 'async_mark_feeding_day')
    entity_platform.async_get_current_platform().async_register_entity_service(
        'record_physical_calibration', {
            vol.Required('measurement_date'): cv.date,
            vol.Required('trials'): list,
            vol.Required('confirmed'): cv.boolean,
        }, 'async_record_physical_calibration')


def _whole_number(value):
    if type(value) not in (int, float) or not isfinite(value) or value != int(value):
        raise vol.Invalid('Expected a whole number')
    return int(value)


def _weight(value):
    if type(value) not in (int, float) or not isfinite(value):
        raise vol.Invalid('Expected a finite weight in grams')
    return float(value)

class NutriPalSensor(NutriPalEntity, SensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key in DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "compensated_weight":
            self._attr_suggested_display_precision = 2
        if key in ("physical_reference", "calibration_weight"):
            self._attr_suggested_display_precision = 1
        if key == "next_meal":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if key == "decision":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["unavailable", "schedule_uncertain", "device_not_ready", "budget_reached", "meal_soon", "bowl_not_empty", "would_feed"]
        enum_options = {
            "status_text": ["idle","feeding","supplements","fault","food_fault","supplement_fault","unknown"],
            "manual_state": ["disabled","pending","cooldown","blocked","ready"],
            "manual_result": ["none","pending","confirmed","uncertain","acknowledged"],
            "daily_quality": ["reconstructed", "missing_boundary", "inconsistent", "unavailable", "storage_error", "excluded"],
        }
        if key in enum_options:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = enum_options[key]
        if key in GRAMS:
            self._attr_native_unit_of_measurement = "g"
            self._attr_device_class = SensorDeviceClass.WEIGHT
        elif key == "battery":
            self._attr_native_unit_of_measurement = "%"
            self._attr_device_class = SensorDeviceClass.BATTERY
        elif key == "desiccant_days":
            self._attr_native_unit_of_measurement = "d"
            self._attr_device_class = SensorDeviceClass.DURATION
        if key in ("intake_today", "bowl_weight", "estimated_distributed", "forecast", "budget", "battery", "portions_today", "meals_today"):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    async def async_add_calibration_measurement(self, **kwargs):
        if self.key != 'calibration_samples':
            raise HomeAssistantError('Select the valid calibration samples sensor')
        await self.coordinator.async_add_calibration_measurement(**kwargs)

    async def async_mark_feeding_day(self, **kwargs):
        if self.key != 'daily_history_count':
            raise HomeAssistantError('Select the feeding history sensor')
        await self.coordinator.async_mark_feeding_day(**kwargs)

    async def async_record_physical_calibration(self, **kwargs):
        if self.key != 'calibration_samples':
            raise HomeAssistantError('Select the valid calibration samples sensor')
        await self.coordinator.async_record_physical_calibration(**kwargs)

    @property
    def native_value(self):
        return self.coordinator.data.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key == "physical_reference":
            return {'series': self.coordinator.data.get('physical_series', []),
                    'matches_configured_reference': self.coordinator.data.get('reference_matches_series', False),
                    'used_for_feeding': False}
        if self.key == "calibration_weight":
            return {'source': 'configured_reference',
                    'matches_latest_physical_series': self.coordinator.data.get('reference_matches_series', False)}
        if self.key == "daily_history_count":
            return {"days": self.coordinator.data.get("daily_history", []), "diagnostic_only": True,
                    "excluded_days": self.coordinator.data.get("daily_excluded_days", {}),
                    "yesterday_excluded": self.coordinator.data.get("daily_yesterday_excluded", False)}
        if self.key == "daily_quality":
            return {"current": self.coordinator.data.get("daily_current", {}), "diagnostic_only": True,
                    "excluded_days": self.coordinator.data.get("daily_excluded_days", {})}
        if self.key == "compensated_samples":
            return {"diagnostic_only": True, "used_for_feeding": False,
                    "observation_status": self.coordinator.data.get("compensated_status"),
                    "observations": self.coordinator.data.get("compensated_history", []),
                    "legacy_observations": sum(r.get('quality') == 'legacy_unverified' for r in self.coordinator.data.get("compensated_history", [])),
                    "rejected_observations": sum(r.get('quality') == 'rejected' for r in self.coordinator.data.get("compensated_history", []))}
        if self.key == "calibration_samples":
            history = self.coordinator.data.get('calibration_history', [])
            return {'diagnostic_only': True, 'used_for_feeding': False, 'assisted_samples': sum(row['source'] == 'assisted' for row in history),
                    'passive_samples': sum(row['source'] == 'passive' for row in history),
                    'legacy_samples': sum(row['source'] == 'legacy' for row in history),
                    'samples': history}
        if self.key == "remaining_portions":
            return {"schedule": self.coordinator.data.get("schedule")}
        if self.key == "decision":
            return {"simulation_only": True, "automatic_distribution": False}
        if self.key in ("warning_mask", "fault_mask"):
            from .diagnostics_text import mask_messages
            return {"details": mask_messages(self.key, self.native_value, self.hass.config.language)}
        return None
