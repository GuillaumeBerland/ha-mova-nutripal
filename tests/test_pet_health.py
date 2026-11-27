"""Local pet data, validation, durability and HA adapter (offline stubs)."""
import asyncio
from datetime import date
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from test_camera_transport import PACKAGE

health = importlib.import_module(PACKAGE + '.pet_health')
TODAY = date(2026, 11, 26)


def profile(model, key='cat_a', **kw):
    model.save_profile(pet_id=key, name='Example cat', today=TODAY,
                       **dict({'target_kg': 4, 'baseline_date': '2025-01-01'}, **kw))


def direct(day='2025-01-01', weight=4.5):
    return dict(date=day, source='veterinarian', weight_kg=weight)


def cage(day='2026-10-31', gross=5.375, tare=1.025):
    return dict(date=day, source='home', gross_kg=gross, cage_kg=tare)


class PetHealthTests(unittest.TestCase):
    def setUp(self):
        self.model = health.PetHealth()
        profile(self.model)

    def record(self, *rows, replace=False, key='cat_a'):
        self.model.record_weights(pet_id=key, measurements=list(rows), today=TODAY, replace_existing=replace)

    def test_net_weight_and_baseline(self):
        self.record(cage(), direct(), direct('2023-01-01', 2.5))
        p = self.model.summary('cat_a')
        self.assertEqual(p['weight_kg'], 4.35)
        self.assertEqual(p['baseline_kg'], 4.5)
        self.assertEqual(p['change_grams'], -150)
        self.assertEqual(p['change_percent'], -3.33)
        self.assertEqual(p['difference_to_target_grams'], 350)
        self.assertEqual(p['latest_source'], 'home')

    def test_distinct_pets(self):
        profile(self.model, 'cat_b', target_kg=3.8)
        self.record(direct())
        self.record(direct(weight=4.2), key='cat_b')
        self.assertEqual(self.model.summary('cat_a')['weight_kg'], 4.5)
        self.assertEqual(self.model.summary('cat_b')['difference_to_target_grams'], 400)

    def test_missing_baseline_or_target_never_guessed(self):
        self.model.save_profile(pet_id='no_target', name='Example', today=TODAY, baseline_date='2024-01-01')
        self.record(cage(), key='no_target')
        s = self.model.summary('no_target')
        self.assertIsNone(s['baseline_kg'])
        self.assertIsNone(s['change_percent'])
        self.assertIsNone(s['difference_to_target_grams'])
        self.assertIsNone(self.model.summary('cat_a')['weight_kg'])

    def test_identical_reimport_idempotent(self):
        self.record(direct(), cage())
        old = self.model.export()
        self.record(cage(), direct())
        self.assertEqual(old, self.model.export())

    def test_conflicting_import_atomic_and_explicit_replacement(self):
        self.record(direct())
        old = self.model.export()
        with self.assertRaises(ValueError):
            self.record(cage(), direct(weight=4.6))
        self.assertEqual(old, self.model.export())
        self.record(direct(weight=4.6), replace=True)
        self.assertEqual(self.model.summary('cat_a')['baseline_kg'], 4.6)

    def test_invalid_measurements(self):
        bad = [direct(weight=True), direct(weight=float('nan')), direct(weight=float('inf')),
               direct(weight=0), direct(weight=4.1234), direct('2026-11-27'),
               direct('2026-02-30'), cage(gross=1, tare=2), cage(tare=0),
               dict(direct(), gross_kg=5, cage_kg=1), dict(direct(), source='unknown')]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.record(direct(), row)
        self.assertEqual(self.model.summary('cat_a')['measurement_count'], 0)

    def test_visual_profile_roundtrip_and_clear(self):
        self.record(direct())
        old = self.model.export()
        self.assertNotIn('color', old['pets']['cat_a'])
        self.model.save_profile(pet_id='cat_a', name='Example cat', today=TODAY,
                                color='#AABBCC', photo_url='/local/pets/cat_a.webp')
        loaded = health.PetHealth(self.model.export())
        self.assertEqual(loaded.summary('cat_a')['color'], '#aabbcc')
        self.assertEqual(loaded.summary('cat_a')['photo_url'], '/local/pets/cat_a.webp')
        loaded.save_profile(pet_id='cat_a', name='Renamed', today=TODAY)
        self.assertEqual(loaded.summary('cat_a')['photo_url'], '/local/pets/cat_a.webp')
        loaded.save_profile(pet_id='cat_a', name='Example cat', today=TODAY, color='', photo_url='')
        self.assertEqual(loaded.export(), old)

    def test_visual_profile_rejects_invalid_values_atomically(self):
        old = self.model.export()
        for fields in ({'color': 'red'}, {'color': '#123'}, {'photo_url': 'https://example.org/a.jpg'},
                       {'photo_url': '/local/pets/../secret.jpg'}, {'photo_url': '/local/pets/a.svg'},
                       {'photo_url': '/local/pets/a.jpg?x=1'}, {'photo_url': '/local/pets/a%2fb.jpg'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.model.save_profile(pet_id='cat_a', name='Example cat', today=TODAY, **fields)
            self.assertEqual(self.model.export(), old)
        corrupt = self.model.export()
        corrupt['pets']['cat_a']['photo_url'] = '//example.org/a.jpg'
        with self.assertRaises(ValueError):
            health.PetHealth(corrupt)

    def test_profile_edit_keeps_history_and_settings(self):
        self.record(direct())
        self.model.save_profile(pet_id='cat_a', name='Renamed', today=TODAY)
        s = self.model.summary('cat_a')
        self.assertEqual((s['name'], s['target_kg'], s['weight_kg']), ('Renamed', 4, 4.5))
        with self.assertRaises(ValueError):
            profile(self.model, 'invalid-id')
        with self.assertRaises(ValueError):
            profile(self.model, target_kg=-1)

    def test_persistence_and_corruption(self):
        self.record(direct(), cage())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'health.json'
            health.save_health(path, self.model)
            self.assertEqual(health.load_health(path).export(), self.model.export())
            raw = json.loads(path.read_text())
            raw['state']['pets']['cat_a']['measurements'][1]['grams'] = 1
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                health.load_health(path)
            self.assertEqual(json.loads(path.read_text()), raw)

    def test_duplicate_in_batch_rejected(self):
        with self.assertRaises(ValueError):
            self.record(direct(), direct())
        self.assertEqual(self.model.summary('cat_a')['measurement_count'], 0)

    def test_storage_limit_does_not_delete_data(self):
        self.record(direct())
        with patch.object(health, 'MAX_WEIGHTS', 1), self.assertRaises(ValueError):
            self.record(cage())
        self.assertEqual(self.model.summary('cat_a')['measurement_count'], 1)

    def test_export_is_copy(self):
        self.record(direct())
        exported = self.model.export()
        exported['pets']['cat_a']['measurements'].clear()
        self.assertEqual(self.model.summary('cat_a')['measurement_count'], 1)


# Minimal adapter stubs. Actual HA lifecycle needs a real HA smoke test.
class FakeSensor:
    async def async_added_to_hass(self): pass
    async def async_will_remove_from_hass(self): pass
    def async_write_ha_state(self): self.writes = getattr(self, 'writes', 0) + 1


def fake_module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


class PetHealthAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.register = Mock()
        cv = types.SimpleNamespace(date=lambda x:x, boolean=bool)
        stub = {
            'homeassistant.components.sensor': fake_module('sensor', SensorEntity=FakeSensor, SensorDeviceClass=types.SimpleNamespace(WEIGHT='weight')),
            'homeassistant.exceptions': fake_module('exceptions', HomeAssistantError=RuntimeError),
            'homeassistant.helpers.device_registry': fake_module('device_registry', DeviceInfo=dict),
            'homeassistant.helpers': fake_module('helpers', config_validation=cv),
            'homeassistant.helpers.service': fake_module('service', async_register_batched_platform_entity_service=self.register),
            'voluptuous': fake_module('voluptuous', Required=lambda x:x, Optional=lambda x,**kw:x, Invalid=ValueError),
        }
        with patch.dict(sys.modules, stub):
            self.adapter = importlib.import_module(PACKAGE + '.pet_health_sensor')
        async def executor(func,*args): return func(*args)
        self.hass = types.SimpleNamespace(config=types.SimpleNamespace(time_zone='Europe/Paris', path=lambda *p: str(Path(self.temp.name).joinpath(*p))), async_add_executor_job=executor, services=types.SimpleNamespace(has_service=lambda *_:False))
        self.entry = types.SimpleNamespace(entry_id='entry')
        self.added = []
        self.manager = self.adapter.PetHealthManager(self.hass,self.entry,'example',self.added.extend)
        self.manager.today = lambda:TODAY
        await self.manager.async_load()
        self.hub = self.adapter.PetHealthSensor(self.manager)
        await self.hub.async_added_to_hass()

    async def create(self):
        await self.hub.async_save_pet_profile(pet_id='cat_a',name='Example',target_kg=4)
        return self.added[-1]

    async def test_dynamic_sensor_and_local_updates(self):
        sensor = await self.create()
        await sensor.async_added_to_hass()
        self.assertEqual(sensor._attr_unique_id,'example_pet_cat_a_weight')
        await self.hub.async_record_pet_weights(pet_id='cat_a',measurements=[cage()])
        self.assertEqual(sensor.native_value, 4.35)
        self.assertEqual(sensor.writes, 1)
        self.assertEqual(self.hub.native_value,1)
        self.assertTrue(sensor.available)
        restored = health.load_health(self.manager.path)
        self.assertEqual(restored.summary('cat_a')['weight_kg'],4.35)
        await sensor.async_will_remove_from_hass()
        self.assertNotIn(sensor,self.manager.entities)

    async def test_health_scope_links_hub_and_weights(self):
        sensor = await self.create()
        self.assertEqual(self.hub.extra_state_attributes['health_scope'], 'entry')
        self.assertEqual(sensor.extra_state_attributes['health_scope'], 'entry')
        self.assertEqual(sensor.extra_state_attributes['pet_id'], 'cat_a')
        self.assertFalse(self.hub.extra_state_attributes['used_for_feeding'])

    async def test_failed_write_blocks_and_keeps_previous_model(self):
        await self.create()
        with patch.object(self.adapter,'save_health',side_effect=OSError):
            with self.assertRaises(RuntimeError):
                await self.hub.async_record_pet_weights(pet_id='cat_a',measurements=[cage()])
        self.assertFalse(self.hub.available)
        self.assertEqual(self.manager.model.summary('cat_a')['measurement_count'],0)
        with self.assertRaises(RuntimeError):
            await self.hub.async_record_pet_weights(pet_id='cat_a',measurements=[cage()])

    async def test_corrupt_storage_not_overwritten(self):
        path=Path(self.manager.path);path.parent.mkdir(exist_ok=True);path.write_text('bad')
        await self.manager.async_load()
        with self.assertRaises(RuntimeError): await self.create()
        self.assertEqual(path.read_text(),'bad')

    async def test_exact_target_guard(self):
        call=types.SimpleNamespace(data={'pet_id':'cat_a','name':'Example'})
        for targets in ([],[object()],[self.hub,object()]):
            with self.assertRaises(RuntimeError): await self.adapter._save_profile(targets,call)
        self.assertEqual(self.hub.native_value,0)
        await self.adapter._save_profile([self.hub],call)
        self.assertEqual(self.hub.native_value,1)

    async def test_concurrent_imports_serialized(self):
        await self.create()
        await asyncio.gather(self.hub.async_record_pet_weights(pet_id='cat_a',measurements=[direct()]),
            self.hub.async_record_pet_weights(pet_id='cat_a',measurements=[cage()]))
        self.assertEqual(health.load_health(self.manager.path).summary('cat_a')['measurement_count'],2)

    async def test_food_action_exact_target_and_persistence(self):
        period={'start_date':'2026-11-26','name':'Example','components':[{'name':'Food','percent':100}], 'portion_g':6.8}
        call=types.SimpleNamespace(data={'period':period})
        with self.assertRaises(RuntimeError):
            await self.adapter._record_food_period([self.hub,object()],call)
        self.assertIsNone(self.manager.model.food_summary(TODAY)['current'])
        await self.adapter._record_food_period([self.hub],call)
        attrs=self.hub.extra_state_attributes
        self.assertEqual(attrs['food']['current']['portion_g'],6.8)
        self.assertFalse(attrs['food']['used_for_feeding'])
        self.assertEqual(health.load_health(self.manager.path).food_summary(TODAY),attrs['food'])

    async def test_care_action_targets_exact_hub_and_persists(self):
        sensor=await self.create()
        record={'pet_id':'cat_a','date':'2026-11-20','category':'consultation','title':'Example visit','due_date':'2026-12-20'}
        call=types.SimpleNamespace(data={'record':record})
        for targets in ([],[sensor],[self.hub,sensor]):
            with self.assertRaises(RuntimeError):await self.adapter._record_pet_care(targets,call)
        await self.adapter._record_pet_care([self.hub],call)
        rows=self.hub.extra_state_attributes['care_records'];self.assertEqual(len(rows),1)
        self.assertEqual(health.load_health(self.manager.path).export()['care_records'],rows)
        self.assertIn('care_records',self.hub._unrecorded_attributes)

    async def test_renew_care_action_is_one_durable_save(self):
        sensor=await self.create()
        record={'pet_id':'cat_a','date':'2026-11-20','category':'consultation','title':'Example visit','due_date':'2026-12-20'}
        await self.hub.async_record_pet_care(record=record)
        old=self.manager.model.export();previous=old['care_records'][0]
        data={'record':dict(record,date=TODAY.isoformat(),title='New visit',due_date=None),
              'previous_record_id':previous['record_id'],'expected_due_date':previous['due_date']}
        call=types.SimpleNamespace(data=data)
        for targets in ([],[sensor],[self.hub,sensor]):
            with self.assertRaises(RuntimeError):await self.adapter._renew_pet_care(targets,call)
        self.assertEqual(self.manager.model.export(),old)
        with patch.object(self.adapter,'save_health',wraps=health.save_health) as save:
            await self.adapter._renew_pet_care([self.hub],call)
            self.assertEqual(save.call_count,1)
        rows=self.hub.extra_state_attributes['care_records']
        self.assertEqual(len(rows),2);self.assertIn(dict(previous,completed=True),rows)
        self.assertEqual(health.load_health(self.manager.path).export()['care_records'],rows)

    async def test_renew_care_failed_save_preserves_previous_follow_up(self):
        await self.create()
        record={'pet_id':'cat_a','date':'2026-11-20','category':'consultation','title':'Example visit','due_date':'2026-12-20'}
        await self.hub.async_record_pet_care(record=record)
        old=self.manager.model.export();previous=old['care_records'][0]
        with patch.object(self.adapter,'save_health',side_effect=OSError('test failure')),self.assertRaises(RuntimeError):
            await self.hub.async_renew_pet_care(record=dict(record,date=TODAY.isoformat(),title='New visit'),
                previous_record_id=previous['record_id'],expected_due_date=previous['due_date'])
        self.assertFalse(self.hub.available)
        self.assertEqual(self.manager.model.export(),old)
        self.assertEqual(health.load_health(self.manager.path).export(),old)

    async def test_concurrent_renewals_close_previous_only_once(self):
        await self.create()
        record = {'pet_id':'cat_a','date':'2026-11-20','category':'consultation',
                  'title':'Previous visit','due_date':'2026-12-20'}
        await self.hub.async_record_pet_care(record=record)
        previous = self.manager.model.export()['care_records'][0]
        args = dict(previous_record_id=previous['record_id'], expected_due_date=previous['due_date'])
        new = dict(record, date=TODAY.isoformat(), title='New visit')
        with patch.object(self.adapter, 'save_health', wraps=health.save_health) as save:
            results = await asyncio.gather(
                self.hub.async_renew_pet_care(record=new, **args),
                self.hub.async_renew_pet_care(record=dict(new, title='Competing visit'), **args),
                return_exceptions=True)
            self.assertEqual(sum(r is None for r in results), 1)
            self.assertEqual(sum(isinstance(r, RuntimeError) for r in results), 1)
            self.assertEqual(save.call_count, 1)
        rows = self.manager.model.export()['care_records']
        self.assertEqual(len(rows), 2)
        self.assertIn(dict(previous, completed=True), rows)
        self.assertEqual(len([r for r in rows if not r['completed']]), 1)
        self.assertTrue(self.hub.available)
        self.assertEqual(health.load_health(self.manager.path).export()['care_records'], rows)

    async def test_concurrent_visual_edit_and_renewal_preserve_both_changes(self):
        await self.create()
        await self.hub.async_record_pet_weights(pet_id='cat_a', measurements=[direct()])
        record = {'pet_id':'cat_a','date':'2026-11-20','category':'consultation',
                  'title':'Previous visit','due_date':'2026-12-20'}
        await self.hub.async_record_pet_care(record=record)
        previous = self.manager.model.export()['care_records'][0]
        await asyncio.gather(
            self.hub.async_save_pet_profile(pet_id='cat_a', name='Renamed',
                                            color='#123456', photo_url='/local/pets/example.png'),
            self.hub.async_renew_pet_care(record=dict(record, date=TODAY.isoformat(), title='New visit'),
                previous_record_id=previous['record_id'], expected_due_date=previous['due_date']))
        state = self.manager.model.export()
        summary = self.manager.model.summary('cat_a')
        self.assertEqual((summary['name'], summary['color'], summary['photo_url']),
                         ('Renamed', '#123456', '/local/pets/example.png'))
        self.assertEqual((summary['weight_kg'], summary['target_kg']), (4.5, 4))
        self.assertEqual(len(state['care_records']), 2)
        self.assertIn(dict(previous, completed=True), state['care_records'])
        self.assertEqual(health.load_health(self.manager.path).export(), state)

    async def test_cancelled_write_cannot_be_overwritten(self):
        await self.create()
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed_executor(func, *args):
            started.set()
            await release.wait()
            return func(*args)
        self.hass.async_add_executor_job = delayed_executor
        task = asyncio.create_task(self.hub.async_record_pet_weights(
            pet_id='cat_a', measurements=[direct()]))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(self.hub.available)
        self.assertFalse(task.done())
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        second = asyncio.create_task(self.hub.async_record_pet_weights(
            pet_id='cat_a', measurements=[cage()]))
        await asyncio.sleep(0)
        self.assertFalse(second.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(RuntimeError):
            await second
        self.assertEqual(self.manager.model.summary('cat_a')['measurement_count'], 0)
        self.assertEqual(health.load_health(self.manager.path).summary('cat_a')['weight_kg'], 4.5)
        # A new manager (as after reloading HA) sees the durable result.
        restored = self.adapter.PetHealthManager(self.hass, self.entry, 'example', self.added.extend)
        await restored.async_load()
        self.assertFalse(restored.failed)
        self.assertEqual(restored.model.summary('cat_a')['weight_kg'], 4.5)

    async def test_cancelled_failed_write_keeps_existing_history(self):
        await self.create()
        await self.hub.async_record_pet_weights(pet_id='cat_a', measurements=[direct()])
        before = Path(self.manager.path).read_bytes()
        started, release = asyncio.Event(), asyncio.Event()
        async def failed_executor(func, *args):
            started.set()
            await release.wait()
            raise OSError('example write failure')
        self.hass.async_add_executor_job = failed_executor
        task = asyncio.create_task(self.hub.async_record_pet_weights(
            pet_id='cat_a', measurements=[cage()]))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.hub.available)
        self.assertEqual(Path(self.manager.path).read_bytes(), before)
        with self.assertRaises(RuntimeError):
            await self.hub.async_record_pet_weights(pet_id='cat_a', measurements=[cage()])
