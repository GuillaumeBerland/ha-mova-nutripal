from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio
import logging
from time import monotonic
from homeassistant.exceptions import HomeAssistantError
from copy import deepcopy
from .state_store import (load_state, save_state, append_sample, assisted_measurement,
                          calibration_history)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DEFAULTS, DOMAIN
from .planner import plan
from .calibration import Calibration, effective_weight, near_meal, number
from .control import manual_allowed, confirm_pending
from .compensated import CompensatedCalibration, append_observation, diagnostic_summary
from .presentation import next_scheduled_meal

_LOGGER = logging.getLogger(__name__)
TZ = ZoneInfo('Europe/Paris')

class NutriPalCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, api):
        super().__init__(hass, _LOGGER, name='MOVA NutriPal', update_interval=timedelta(minutes=5), config_entry=entry)
        self.entry = entry
        self.api = api
        self.did = entry.data['did']
        self.lock = asyncio.Lock()
        self.state_path = hass.config.path(".storage", f"{DOMAIN}.{entry.entry_id}.v020.json")
        self.storage_failed = False
        self.state = {'samples': [], 'pending': None, 'last_attempt': 0, 'last_result': 'none'}
        self.cal = Calibration()
        self.compensated = CompensatedCalibration()
        self.notification_active = None
        self.stopping = False

    async def async_load_state(self):
        saved = await self.hass.async_add_executor_job(load_state, self.state_path)
        if saved is not None:
            self.state.update(saved)

    async def _save(self):
        try:
            await self.hass.async_add_executor_job(save_state, self.state_path, deepcopy(self.state))
        except Exception:
            self.storage_failed = True
            raise

    @property
    def options(self):
        return {**DEFAULTS, **self.entry.options}

    def _enrich(self, data, now):
        options = self.options
        samples = self.state['samples']
        weight = effective_weight(samples, options['portion_weight'], options['auto_calibration'])
        data.update(plan(data, {**options, 'portion_weight': weight}, now))
        data['calibration_history'] = calibration_history(self.state)
        records = self.state.get('compensated_records', [])
        data.update(diagnostic_summary(records))
        data['compensated_history'] = deepcopy(records)
        data['compensated_status'] = self.compensated.status
        data.update(target=options['target'], calibration_weight=weight, simulation=True,
                    calibration_samples=len(samples), measured_weight=effective_weight(samples, None) if len(samples)>=3 else None,
                    calibration_enabled=options['auto_calibration'], manual_enabled=options['manual_enabled'],
                    manual_state="blocked" if self.storage_failed else manual_allowed(data, options, self.state, now),
                    manual_result=self.state['last_result'], manual_pending=self.state['pending'] is not None,
                    threshold_setting=options['threshold'], max_setting=options['max_complement'],
                    reference_setting=options['portion_weight'], target_setting=options['target'])
        # Display-only: never used by the hybrid decision or command guards.
        next_meal = next_scheduled_meal(data.get('schedule'), now) if data.get('online') is True else None
        data['next_meal'] = next_meal[0] if next_meal else None
        data['next_meal_portions'] = next_meal[1] if next_meal else None
        raw = data.get('device_status')
        data['status_text'] = {1:'idle',2:'feeding',5:'supplements',6:'fault',7:'food_fault',8:'supplement_fault'}.get(raw, 'unknown') if raw is not None else None
        w, f = data.get('warning_mask'), data.get('fault_mask')
        data['has_warning'] = w != 0 if type(w) is int and w >= 0 else None
        data['has_fault'] = f != 0 if type(f) is int and f >= 0 else None
        return data

    async def _snapshot(self):
        now = datetime.now(TZ)
        data = await self.hass.async_add_executor_job(self.api.snapshot, now)
        end = datetime.now(TZ)
        if now.date() != end.date():
            raise UpdateFailed('Date changed during refresh')
        return data, end

    async def _notify(self, active):
        if active == self.notification_active:
            return
        nid = f'{DOMAIN}_{self.entry.entry_id}'
        if active:
            await self.hass.services.async_call('persistent_notification', 'create', {
                'notification_id': nid, 'title': 'MOVA NutriPal',
                'message': 'Vérifier la gamelle : alerte, défaut ou distribution manuelle non confirmée. Consultez les capteurs et MOVAhome.'}, blocking=True)
        else:
            await self.hass.services.async_call('persistent_notification', 'dismiss', {'notification_id': nid}, blocking=True)
        self.notification_active = active

    async def _async_update_data(self):
        async with self.lock:
            try:
                started = monotonic()
                data, now = await self._snapshot()
                duration = monotonic() - started
                options = self.options
                pending = self.state['pending']
                changed = False
                if confirm_pending(pending, data, now):
                    self.state['pending'] = None
                    self.state['last_result'] = 'confirmed'
                    changed = True
                elif pending is not None and self.state['last_result'] != 'uncertain' and now.timestamp() - pending.get('time',0) > 180:
                    self.state['last_result'] = 'uncertain'
                    changed = True
                fast = near_meal(data, now) or (pending is not None and now.timestamp()-pending.get('time',0) <= 240) or self.cal.candidate is not None
                self.update_interval = timedelta(seconds=30) if fast else timedelta(minutes=5)
                if options['auto_calibration'] and fast:
                    baseline = self.cal.baseline
                    sample = self.cal.observe(data, now)
                    if sample is not None and baseline is not None:
                        detail = {'source': 'passive', 'day': now.date().isoformat(),
                                  'start_count': baseline[2], 'end_count': data['portions_today']}
                        changed = append_sample(self.state, sample, detail) or changed
                else:
                    self.cal.reset()
                # Independent experimental observations; never append to calibration samples.
                if (options['auto_calibration'] and fast and not options['manual_enabled']
                        and pending is None and self.state['pending'] is None):
                    record = self.compensated.observe(data, now, duration)
                    if record is not None:
                        changed = append_observation(self.state.setdefault('compensated_records', []), record) or changed
                else:
                    self.compensated.reset('disabled' if not options['auto_calibration'] else 'waiting')
                if changed:
                    await self._save()
                result = self._enrich(data, now)
                try:
                    await self._notify(result['has_warning'] is True or result['has_fault'] is True or result['manual_result'] == 'uncertain')
                except Exception:
                    _LOGGER.warning('Could not update NutriPal notification')
                return result
            except Exception as exc:
                self.cal.reset()
                self.compensated.reset('invalid_reading')
                raise UpdateFailed(f'MOVA update failed ({type(exc).__name__})') from None

    async def async_feed_one(self):
        # No calls to this method from the coordinator's periodic update.
        async with self.lock:
            if self.stopping or self.storage_failed or not self.hass.is_running:
                raise HomeAssistantError('Integration stopping')
            started = datetime.now(TZ)
            data, now = await self._snapshot()
            if (now-started).total_seconds() > 45:
                raise HomeAssistantError("MOVA: data acquisition too slow")
            data = self._enrich(data, now)
            if data['manual_state'] != 'ready':
                raise HomeAssistantError(f'MOVA: manual supplement blocked ({data["manual_state"]})')
            # Write reservation BEFORE any network write. On interruption it stays locked.
            self.state['pending'] = {'time': now.timestamp(), 'day': now.date().isoformat(), 'count': data['portions_today'], 'ack': False}
            self.state['last_attempt'] = now.timestamp()
            self.state['last_result'] = 'pending'
            await self._save()
            self.update_interval = timedelta(seconds=30)
            if self.stopping or not self.hass.is_running:
                raise HomeAssistantError("MOVA: stopping; command reserved but not sent")
            ack = False
            try:
                ack = await self.hass.async_add_executor_job(self.api.feed_one)
                if ack:
                    self.state['pending']['ack'] = True
                else:
                    self.state['last_result'] = 'uncertain'
            except Exception:
                self.state['last_result'] = 'uncertain'
            await self._save()
            self.async_set_updated_data(self._enrich(data, now))
        await self.async_request_refresh()
        if not ack:
            raise HomeAssistantError('MOVA: uncertain command; check feeder before unlocking')

    async def async_add_calibration_measurement(self, measurement_date, portions,
                                               daily_counter, weight_before,
                                               weight_after, confirmed):
        """Record one verified weighing; never dispense or alter the program."""
        async with self.lock:
            if self.stopping or self.storage_failed or not self.hass.is_running:
                raise HomeAssistantError('Calibration storage unavailable')
            if self.state['pending'] is not None or self.options['manual_enabled']:
                raise HomeAssistantError('Disable manual dispensing and resolve any pending command first')
            try:
                value, detail = assisted_measurement(
                    measurement_date, datetime.now(TZ).date(), portions, daily_counter,
                    weight_before, weight_after, confirmed)
            except ValueError as exc:
                raise HomeAssistantError(str(exc)) from None
            previous = deepcopy(self.state)
            if not append_sample(self.state, value, detail):
                raise HomeAssistantError('This dispensing event overlaps an existing calibration sample')
            try:
                await self._save()
            except Exception:
                self.state = previous
                raise HomeAssistantError('Could not save calibration measurement') from None
            self.cal.reset()
        # A normal refresh publishes the new median using current device data.
        # No dispensing command is issued by this action.
        await self.async_request_refresh()

    async def async_reset_calibration(self):
        async with self.lock:
            self.cal.reset()
            self.state['samples'] = []
            self.state['sample_details'] = []
            await self._save()
        await self.async_request_refresh()

    async def async_acknowledge(self):
        # Explicit user acknowledgement after visually checking the feeder.
        async with self.lock:
            if self.storage_failed:
                raise HomeAssistantError("MOVA: storage failed; restart and inspect feeder")
            if self.state['pending'] is not None:
                self.state['pending'] = None
                self.state['last_result'] = 'acknowledged'
                # Cooldown starts again; acknowledgement cannot cause an immediate new dose.
                self.state['last_attempt'] = datetime.now(TZ).timestamp()
                await self._save()
        await self.async_request_refresh()

    async def async_close(self):
        self.stopping = True
        async with self.lock:
            await self.hass.async_add_executor_job(self.api.close)
