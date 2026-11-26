#!/usr/bin/env python3
"""Optional browser smoke test with a mocked HA frontend.
Requires playwright and Chromium; not part of the normal Python unit suite.
Run: python tools/test_pet_health_card.py [chromium executable]
"""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

CARD = Path(__file__).resolve().parents[1] / 'dashboard/mova-pet-health-card.js'


def run(browser):
    page = browser.new_page(viewport={'width': 1100, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('<html><body><mova-pet-health-card></mova-pet-health-card></body></html>')
    page.add_script_tag(path=str(CARD))
    page.evaluate('''() => {
      window.calls=[];
      window.a={pet_id:'cat_a',name:'Example A',weight_kg:4.2, target_kg:4,baseline_kg:4.5,baseline_date:'2023-11-04',latest_date:'2024-10-31',change_grams:-300,difference_to_target_grams:200,measurement_count:2};
      window.b={pet_id:'cat_b',name:'Example B',weight_kg:4.6,target_kg:4,baseline_kg:5.0,baseline_date:'2023-11-04',latest_date:'2024-10-31',change_grams:-400,difference_to_target_grams:600,measurement_count:2};
      const weight=(p,scope,rows)=>({state:String(p.weight_kg),attributes:{...p,health_scope:scope,measurements:rows}});
      window.hass={config:{time_zone:'Europe/Paris'},states:{
        'sensor.hub':{state:'2',attributes:{health_scope:'entry-a',profiles:[a,b]}},
        'sensor.weight_a':weight(a,'entry-a',[{date:'2023-11-04',grams:4500,source:'veterinarian',method:'direct'},{date:'2024-10-31',grams:4200,source:'home',method:'cage',gross_grams:5250,cage_grams:1050}]),
        'sensor.weight_b':weight(b,'entry-a',[{date:'2023-11-04',grams:5000,source:'veterinarian',method:'direct'},{date:'2024-10-31',grams:4600,source:'veterinarian',method:'direct'}]),
        'sensor.other_weight':weight(a,'entry-b',[{date:'2024-01-01',grams:9999,source:'other',method:'direct'}])
      },callService:async(...args)=>{window.calls.push(args);if(window.fail)throw new Error('Test error');}};
      window.card=document.querySelector('mova-pet-health-card');card.setConfig({entity:'sensor.hub',language:'fr'});card.hass=hass;
    }''')
    root = page.locator('mova-pet-health-card')
    assert root.locator('.pet').count() == 2
    assert root.locator('svg circle').count() == 4
    assert '9,999' not in root.locator('ha-card').inner_text()
    assert root.locator('.pet').first.locator('.weight').inner_text() == '4,200 kg'
    assert '60,0 %' in root.locator('ha-card').inner_text()
    # Common scale and date bounds, distinct chart colours, translated dates.
    axes = root.locator('.pet').evaluate_all("cards=>cards.map(c=>[...c.querySelectorAll('svg text[text-anchor=end]')].map(x=>x.textContent))")
    assert axes[0] == axes[1], axes
    colours = root.locator('svg polyline').evaluate_all("lines=>lines.map(x=>x.getAttribute('stroke'))")
    assert len(set(colours)) == 2, colours
    assert '31/10/2024' in root.locator('.pet').first.inner_text()
    page.evaluate("()=>{card.today=()=> '2024-11-15';card.refresh();}")
    root.get_by_label('Période des courbes').select_option('3')
    assert root.locator('svg circle').count() == 2
    assert 'Il y a 15 j' in root.locator('.pet').first.inner_text()
    page.evaluate("()=>{hass.states['sensor.hub']={...hass.states['sensor.hub']};card.hass=hass;}")
    assert root.get_by_label('Période des courbes').input_value() == '3'
    root.get_by_label('Période des courbes').select_option('all')
    assert root.locator('svg circle').count() == 4
    root.get_by_label('Période des courbes').select_option('baseline')
    # Restore dynamic clock for other form tests.
    page.evaluate("()=>{delete card.today;card.hass=hass;}")
    # Actual DOM events and form submission; exact target and source fields.
    root.locator('form').first.evaluate('(f)=>f.parentElement.open=true')
    page.evaluate('''()=>{card.day.value='2024-10-30';card.gross.value='5.25';card.cage.value='1.050';card.updateNet();}''')
    assert 'Poids net : 4,200 kg' in root.locator('.net').inner_text()
    root.get_by_role('button',name='Enregistrer la pesée').click()
    page.wait_for_function('window.calls.length===1')
    calls = page.evaluate('window.calls')
    assert calls[0] == ['mova_nutripal','record_pet_weights',{'pet_id':'cat_a','measurements':[{'date':'2024-10-30','source':'home','gross_kg':5.25,'cage_kg':1.05}],'replace_existing':False},{'entity_id':'sensor.hub'}], calls
    # Existing measurement selection and explicit confirmation.
    page.evaluate('''()=>{card.old.value='2024-10-31';card.old.dispatchEvent(new Event('change'));}''')
    assert page.evaluate('card.gross.value') == '5.25'
    assert not page.evaluate('card.replace.checked')
    assert page.evaluate('card.day.readOnly')
    page.evaluate("card.day.value='2024-10-29'")
    root.get_by_role('button',name='Enregistrer la pesée').click()
    assert page.evaluate('calls.length') == 1
    assert 'ne peut pas être déplacée' in root.locator('ha-card').inner_text()
    page.evaluate("card.day.value='2024-10-31'")
    page.evaluate('''()=>{card.replace.checked=true;card.gross.value='5.26';}''')
    page.once('dialog', lambda dialog: dialog.dismiss())
    root.get_by_role('button',name='Enregistrer la pesée').click()
    assert page.evaluate('calls.length') == 1
    page.once('dialog', lambda dialog: dialog.accept())
    root.get_by_role('button',name='Enregistrer la pesée').click()
    page.wait_for_function('calls.length===2')
    assert page.evaluate('calls[1][2].replace_existing') is True
    # Profile form and error propagation.
    root.locator('form').nth(1).evaluate('(f)=>f.parentElement.open=true')
    page.evaluate('''()=>{card.profileSelect.value='cat_b';card.loadProfile();card.target.value='4.1';window.fail=true;}''')
    root.get_by_role('button',name='Enregistrer le profil').click()
    page.wait_for_function('calls.length===3')
    assert 'Test error' in root.locator('ha-card').inner_text()
    assert page.evaluate('calls[2][2].pet_id') == 'cat_b'
    assert page.evaluate('calls[2][2].target_kg') == 4.1
    # Food period UI: no guessed energy, exact target, shares must sum to 100.
    root.locator('form').nth(2).evaluate('(f)=>f.parentElement.open=true')
    page.evaluate("""()=>{window.fail=false;card.foodDate.value='2024-10-31';card.foodName.value='Example blend';card.foodFields[0].name.value='A';card.foodFields[0].pct.value='70';card.addFoodRow({name:'B',percent:20});card.foodRation.value='100';card.foodPortion.value='6.8';}""")
    root.get_by_role('button',name='Enregistrer la période alimentaire').click()
    assert page.evaluate('calls.length') == 3
    assert '100 %' in root.locator('ha-card').inner_text()
    page.evaluate("card.foodFields[1].pct.value='30'")
    root.get_by_role('button',name='Enregistrer la période alimentaire').click()
    page.wait_for_function('calls.length===4')
    assert page.evaluate('calls[3]') == ['mova_nutripal','record_food_period',{'period':{'start_date':'2024-10-31','name':'Example blend','components':[{'name':'A','percent':70},{'name':'B','percent':30}],'ration_g':100,'portion_g':6.8},'replace_existing':False},{'entity_id':'sensor.hub'}]
    page.evaluate("""()=>{const r=calls[3][2].period;hass.states['sensor.hub']={state:'2',attributes:{health_scope:'entry-a',profiles:[a,b],food:{current:r,history:[r],used_for_feeding:false}}};card.hass=hass;}""")
    assert 'Example blend' in root.locator('ha-card').inner_text()
    assert root.locator('.mixture > div').count() == 2
    assert root.locator('.mixture > div').evaluate_all("els=>els.map(e=>e.style.width)") == ['70%', '30%']
    assert 'A · 70 %' in root.locator('.mix-legend').inner_text()
    assert 'Début déclaré : 31/10/2024' in root.locator('ha-card').inner_text()
    assert 'Repères verticaux' in root.locator('ha-card').inner_text()
    page.evaluate("""()=>{card.foodSelect.value='2024-10-31';card.loadFood();}""")
    assert page.evaluate('card.foodFields.length') == 2
    assert page.evaluate('card.foodPortion.value') == '6.8'
    assert not page.evaluate('card.foodReplace.checked')
    assert page.evaluate('card.foodDate.readOnly')
    page.evaluate("card.foodDate.value='2024-10-30'")
    root.get_by_role('button',name='Enregistrer la période alimentaire').click()
    assert page.evaluate('calls.length') == 4
    assert 'ne peut pas être déplacée' in root.locator('ha-card').inner_text()
    page.evaluate("card.foodDate.value='2024-10-31'")
    # Histories stay expanded across an incoming state refresh and period change.
    page.evaluate("""()=>{card.summary.querySelector('[data-history-key="weight:cat_a"]').open=true;card.summary.querySelector('[data-history-key="food"]').open=true;hass.states['sensor.hub']={...hass.states['sensor.hub']};card.hass=hass;}""")
    assert root.locator('details[data-history-key="weight:cat_a"]').evaluate('(e)=>e.open')
    assert root.locator('details[data-history-key="food"]').evaluate('(e)=>e.open')
    root.get_by_label('Période des courbes').select_option('all')
    assert root.locator('details[data-history-key="food"]').evaluate('(e)=>e.open')
    # Veterinary entry, history and correction are scoped to one animal.
    root.locator('form').nth(3).evaluate('(f)=>f.parentElement.open=true')
    page.evaluate("""()=>{card.carePet.value='cat_b';card.carePet.dispatchEvent(new Event('change'));card.careDate.value='2024-10-30';card.careCategory.value='vaccination';card.careTitle.value='Example vaccine';card.careNotes.value='Example notes';card.careDue.value='2025-10-30';}""")
    root.get_by_role('button',name='Enregistrer l’événement').click()
    page.wait_for_function('calls.length===5')
    assert page.evaluate('calls[4]') == ['mova_nutripal','record_pet_care',{'record':{'pet_id':'cat_b','date':'2024-10-30','category':'vaccination','title':'Example vaccine','notes':'Example notes','completed':False,'due_date':'2025-10-30'},'replace_existing':False},{'entity_id':'sensor.hub'}]
    page.evaluate("""()=>{const r={...calls[4][2].record,record_id:'a'.repeat(32)};hass.states['sensor.hub']={...hass.states['sensor.hub'],attributes:{...hass.states['sensor.hub'].attributes,care_records:[r]}};card.hass=hass;card.careOld.value=r.record_id;card.loadCare();}""")
    assert 'Example vaccine' in root.locator('ha-card').inner_text()
    assert 'En retard' in root.locator('ha-card').inner_text()
    assert page.evaluate('card.careTitle.value') == 'Example vaccine'
    page.evaluate('card.careDone.checked=true')
    root.get_by_role('button',name='Enregistrer l’événement').click()
    assert page.evaluate('calls.length') == 5
    page.evaluate('card.careReplace.checked=true')
    page.once('dialog', lambda dialog: dialog.accept())
    root.get_by_role('button',name='Enregistrer l’événement').click()
    page.wait_for_function('calls.length===6')
    assert page.evaluate('calls[5][2].record.completed') is True
    assert page.evaluate('calls[5][2].record_id') == 'a'*32
    # Narrow layout and unavailable hub. Form must be hidden and no actions fired.
    page.set_viewport_size({'width':390,'height':800})
    assert root.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    page.evaluate('''()=>{hass.states['sensor.hub']={state:'unavailable',attributes:{}};card.hass=hass;}''')
    assert not root.locator('form').first.is_visible()
    assert 'indisponible' in root.locator('ha-card').inner_text()
    assert not errors, errors
    page.close()
    print('Browser smoke test OK (charts, scope, cage entry, correction, profile, food, care, error, mobile, unavailable)')


if __name__ == '__main__':
    with sync_playwright() as p:
        kwargs = {'executable_path':sys.argv[1]} if len(sys.argv)>1 else {}
        browser = p.chromium.launch(headless=True,args=['--no-sandbox'],**kwargs)
        try: run(browser)
        finally: browser.close()
