"""Native local health entities and actions; no calls to the feeder API."""
import asyncio
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_batched_platform_entity_service
import voluptuous as vol

from .const import DOMAIN
from .pet_health import PetHealth, load_health, save_health

_LOGGER = logging.getLogger(__name__)


class PetHealthManager:
    def __init__(self, hass, entry, did, async_add_entities):
        self.hass = hass
        self.entry = entry
        self.did = did
        self.path = hass.config.path('.storage', f'{DOMAIN}.{entry.entry_id}.pet_health.json')
        self.model = PetHealth()
        self.failed = False
        self.lock = asyncio.Lock()
        self.add_entities = async_add_entities
        self.entities = set()

    async def async_load(self):
        try:
            self.model = await self.hass.async_add_executor_job(load_health, self.path)
        except Exception:
            self.failed = True
            _LOGGER.error('Could not load local pet health data; writes disabled')

    def today(self):
        return datetime.now(ZoneInfo(self.hass.config.time_zone)).date()

    async def async_change(self, method, **kwargs):
        async with self.lock:
            if self.failed:
                raise HomeAssistantError('Pet health storage unavailable; restore data before reloading')
            candidate = PetHealth(self.model.export())
            try:
                getattr(candidate, method)(today=self.today(), **kwargs)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                raise HomeAssistantError(str(exc)) from None
            if candidate.export() == self.model.export():
                return
            new_ids = candidate.pets.keys() - self.model.pets.keys()
            # Save before changing the visible state. A failed/ambiguous write
            # blocks further changes until reload, so it cannot overwrite data.
            write = None
            try:
                write = asyncio.ensure_future(
                    self.hass.async_add_executor_job(save_health, self.path, candidate)
                )
                await asyncio.shield(write)
            except asyncio.CancelledError:
                # Cancelling the service does not stop an executor thread. Never
                # permit a later edit to overwrite an uncertain on-disk commit.
                self.failed = True
                try:
                    if write is not None:
                        while not write.done():
                            try:
                                await asyncio.shield(write)
                            except asyncio.CancelledError:
                                # Even repeated cancellation must not release the lock
                                # while the executor may still be writing.
                                continue
                        if not write.cancelled():
                            write.result()
                except Exception:
                    _LOGGER.error('Interrupted pet health save also failed')
                finally:
                    for entity in tuple(self.entities):
                        entity.async_write_ha_state()
                raise
            except Exception:
                self.failed = True
                for entity in tuple(self.entities):
                    entity.async_write_ha_state()
                raise HomeAssistantError('Could not save pet health data; writes disabled until reload') from None
            self.model = candidate
            for entity in tuple(self.entities):
                entity.async_write_ha_state()
            if new_ids:
                self.add_entities([PetWeightSensor(self, key) for key in sorted(new_ids)])


class HealthEntity(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager):
        self.manager = manager

    @property
    def available(self):
        return not self.manager.failed

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.manager.entities.add(self)

    async def async_will_remove_from_hass(self):
        self.manager.entities.discard(self)
        await super().async_will_remove_from_hass()


class PetHealthSensor(HealthEntity):
    _attr_translation_key = 'pet_health'
    _unrecorded_attributes = frozenset({'profiles', 'food', 'care_records'})

    def __init__(self, manager):
        super().__init__(manager)
        self._attr_unique_id = f'{manager.did}_pet_health'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, manager.did)},
            manufacturer='MOVA', model='NutriPal 10 Ultra', name='MOVA NutriPal')

    @property
    def native_value(self):
        return len(self.manager.model.pets)

    @property
    def extra_state_attributes(self):
        return {'profiles': [self.manager.model.summary(key) for key in sorted(self.manager.model.pets)],
                'food': self.manager.model.food_summary(self.manager.today()),
                'care_records': self.manager.model.export()['care_records'], 'local_only': True, 'used_for_feeding': False, 'health_scope': self.manager.entry.entry_id}

    async def async_save_pet_profile(self, **kwargs):
        await self.manager.async_change('save_profile', **kwargs)

    async def async_record_food_period(self, **kwargs):
        await self.manager.async_change('record_food_period', **kwargs)

    async def async_record_pet_care(self, **kwargs):
        await self.manager.async_change('record_care', **kwargs)

    async def async_record_pet_weights(self, **kwargs):
        await self.manager.async_change('record_weights', **kwargs)


class PetWeightSensor(HealthEntity):
    _attr_translation_key = 'pet_weight'
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = 'kg'
    _attr_suggested_display_precision = 3
    _unrecorded_attributes = frozenset({'measurements', 'color', 'photo_url'})

    def __init__(self, manager, pet_id):
        super().__init__(manager)
        self.pet_id = pet_id
        self._attr_unique_id = f'{manager.did}_pet_{pet_id}_weight'

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, f'{self.manager.did}_pet_{self.pet_id}')},
            name=self.manager.model.pets[self.pet_id]['name'])

    @property
    def native_value(self):
        return self.manager.model.summary(self.pet_id)['weight_kg']

    @property
    def extra_state_attributes(self):
        summary = self.manager.model.summary(self.pet_id)
        summary['health_scope'] = self.manager.entry.entry_id
        summary['measurements'] = self.manager.model.export()['pets'][self.pet_id]['measurements']
        return summary


def _kg(value):
    from .pet_health import _grams
    try:
        return _grams(value)/1000
    except (ValueError, OverflowError) as exc:
        raise vol.Invalid(str(exc)) from None


async def async_setup_pet_health(hass, entry, did, async_add_entities):
    manager = PetHealthManager(hass, entry, did, async_add_entities)
    await manager.async_load()
    async_add_entities([PetHealthSensor(manager),
                        *[PetWeightSensor(manager, key) for key in sorted(manager.model.pets)]])
    # Batched service handlers reject a broad target before any write occurs.
    for name, schema, handler in (
        ('save_pet_profile', {
            vol.Required('pet_id'): str,
            vol.Required('name'): str,
            vol.Optional('target_kg'): _kg,
            vol.Optional('baseline_date'): cv.date,
            vol.Optional('color'): str,
            vol.Optional('photo_url'): str,
        }, _save_profile),
        ('record_food_period', {
            vol.Required('period'): dict,
            vol.Optional('replace_existing', default=False): cv.boolean,
        }, _record_food_period),
        ('record_pet_care', {
            vol.Required('record'): dict,
            vol.Optional('record_id'): str,
            vol.Optional('replace_existing', default=False): cv.boolean,
        }, _record_pet_care),
        ('record_pet_weights', {
            vol.Required('pet_id'): str,
            vol.Required('measurements'): list,
            vol.Optional('replace_existing', default=False): cv.boolean,
        }, _record_weights),
    ):
        if not hass.services.has_service(DOMAIN, name):
            async_register_batched_platform_entity_service(hass, DOMAIN, name,
                entity_domain='sensor', func=handler, schema=schema)


def _one_health_sensor(entities):
    if len(entities) != 1 or not isinstance(entities[0], PetHealthSensor):
        raise HomeAssistantError('Select exactly one Pet health tracking sensor')
    return entities[0]


async def _save_profile(entities, call):
    await _one_health_sensor(entities).async_save_pet_profile(**call.data)


async def _record_weights(entities, call):
    await _one_health_sensor(entities).async_record_pet_weights(**call.data)


async def _record_food_period(entities, call):
    await _one_health_sensor(entities).async_record_food_period(**call.data)


async def _record_pet_care(entities, call):
    await _one_health_sensor(entities).async_record_pet_care(**call.data)
