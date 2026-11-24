from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN
from .entity import NutriPalEntity

GRAMS = ("intake_today", "intake_yesterday", "bowl_weight", "configured_weight", "calibration_weight", "estimated_distributed", "forecast", "budget", "target", "measured_weight")
COUNTS = ("meals_today", "meals_yesterday", "portions_today", "portions_yesterday", "supplement_remaining", "remaining_portions", "suggested_portions", "calibration_samples")
OTHER = ("device_status", "warning_mask", "fault_mask", "feeding_mode", "sd_card_status", "decision", "battery", "desiccant_days", "status_text", "manual_state", "manual_result", "next_meal", "next_meal_portions")
DIAGNOSTIC = {"device_status", "warning_mask", "fault_mask", "feeding_mode", "sd_card_status", "supplement_remaining", "configured_weight"}

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalSensor(coordinator, key) for key in GRAMS + COUNTS + OTHER])

class NutriPalSensor(NutriPalEntity, SensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key in DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "next_meal":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if key == "decision":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["unavailable", "schedule_uncertain", "device_not_ready", "budget_reached", "meal_soon", "bowl_not_empty", "would_feed"]
        enum_options = {
            "status_text": ["idle","feeding","supplements","fault","food_fault","supplement_fault","unknown"],
            "manual_state": ["disabled","pending","cooldown","blocked","ready"],
            "manual_result": ["none","pending","confirmed","uncertain","acknowledged"],
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

    @property
    def native_value(self):
        return self.coordinator.data.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key == "remaining_portions":
            return {"schedule": self.coordinator.data.get("schedule")}
        if self.key == "decision":
            return {"simulation_only": True, "automatic_distribution": False}
        if self.key in ("warning_mask", "fault_mask"):
            from .diagnostics_text import mask_messages
            return {"details": mask_messages(self.key, self.native_value, self.hass.config.language)}
        return None
