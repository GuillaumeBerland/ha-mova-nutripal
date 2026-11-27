#!/usr/bin/env python3
"""Offline Chromium regression for photos, colors, and health form payloads."""
import base64
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

CARD = Path(__file__).resolve().parents[1] / 'dashboard/mova-pet-health-card.js'
# Tiny fixture, served locally by Playwright; no real pet photo or HA server.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGM0SpnGwMDAxMDAwMDAAAAN1gEwpPE8dQAAAABJRU5ErkJggg==')
ORIGIN = 'http://ha.test'


def run(browser):
    page = browser.new_page(viewport={'width': 1100, 'height': 1000})
    errors, unexpected = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def serve(route):
        url = route.request.url
        if url == ORIGIN + '/':
            route.fulfill(content_type='text/html', body='<html><body><mova-pet-health-card></mova-pet-health-card></body></html>')
        elif url == ORIGIN + '/local/pets/ok.png':
            route.fulfill(content_type='image/png', body=PNG)
        elif url == ORIGIN + '/local/pets/missing.png':
            route.fulfill(status=404, body='Not found')
        elif url == ORIGIN + '/favicon.ico':
            route.fulfill(status=204, body='')
        else:
            unexpected.append(url)
            route.abort()

    page.route('**/*', serve)
    page.goto(ORIGIN + '/')
    page.add_script_tag(path=str(CARD))
    page.evaluate('''() => {
      window.calls=[];
      const pet=(pet_id,name,color,photo_url)=>({pet_id,name,color,photo_url,
        weight_kg:4.2,target_kg:4,baseline_kg:4.5,baseline_date:'2024-10-01',
        latest_date:'2024-11-01',measurement_count:2});
      window.a=pet('cat_a','Example A','#123456','/local/pets/ok.png');
      window.b=pet('cat_b','Example B','#b66e89','/local/pets/missing.png');
      const rows=[{date:'2024-10-01',grams:4500,source:'home',method:'direct'},
                  {date:'2024-11-01',grams:4200,source:'home',method:'direct'}];
      const weight=p=>({state:'4.2',attributes:{...p,health_scope:'example',measurements:rows}});
      const care=(p,id,category)=>({record_id:id.repeat(32),pet_id:p.pet_id,
        date:'2024-11-01',category,title:'Example care',notes:'',due_date:'2024-12-01',completed:false});
      window.hass={config:{time_zone:'Europe/Paris'},states:{
        'sensor.hub':{state:'2',attributes:{health_scope:'example',profiles:[a,b],
          care_records:[care(a,'a','deworming'),care(b,'b','vaccination')]}},
        'sensor.weight_a':weight(a),'sensor.weight_b':weight(b)},
        callService:async(...args)=>{calls.push(args);}};
      window.card=document.querySelector('mova-pet-health-card');
      card.setConfig({entity:'sensor.hub',language:'fr'});card.today=()=> '2024-11-15';card.hass=hass;
      window.updateProfiles=profiles=>{const old=hass.states['sensor.hub'];
        hass.states['sensor.hub']={...old,attributes:{...old.attributes,profiles}};card.hass=hass;};
    }''')
    root = page.locator('mova-pet-health-card')
    first, second = root.locator('.pet').nth(0), root.locator('.pet').nth(1)
    page.wait_for_function('''()=>{const pets=card.shadowRoot.querySelectorAll('.pet');
        const img=pets[0].querySelector('.pet-avatar img');
        return img?.naturalWidth>0 && pets[0].querySelector('.pet-avatar ha-icon').hidden &&
               !pets[1].querySelector('.pet-avatar img');}''')
    assert first.locator('.pet-avatar img').get_attribute('src') == '/local/pets/ok.png'
    assert second.locator('.pet-avatar ha-icon').get_attribute('icon') == 'mdi:cat'
    assert not second.locator('.pet-avatar ha-icon').evaluate('(e)=>e.hidden')
    assert first.locator('.pet-avatar').evaluate('(e)=>e.style.backgroundColor') == 'rgb(18, 52, 86)'
    assert second.locator('.pet-avatar').evaluate('(e)=>e.style.backgroundColor') == 'rgb(182, 110, 137)'
    assert first.locator('svg polyline').get_attribute('stroke') == '#123456'
    assert second.locator('svg polyline').get_attribute('stroke') == '#b66e89'
    for name, color, icon in [('Example A', 'rgb(18, 52, 86)', 'mdi:pill'),
                              ('Example B', 'rgb(182, 110, 137)', 'mdi:needle')]:
        entries = root.locator('.care-entry').filter(has_text=name)
        assert entries.count() == 2  # pending and historical entry
        for entry in entries.all():
            assert entry.locator('.pet-avatar').evaluate('(e)=>e.style.backgroundColor') == color
            assert entry.locator('.care-category ha-icon').get_attribute('icon') == icon
    # Legacy profiles and untrusted photo strings must never request an external URL.
    page.evaluate("()=>updateProfiles([{...a,color:null,photo_url:'https://bad.invalid/pet.png'},{...b,photo_url:null}])")
    assert first.locator('.pet-avatar img').count() == 0
    assert second.locator('.pet-avatar img').count() == 0
    assert first.locator('svg polyline').get_attribute('stroke') == '#527fba'
    assert first.locator('.pet-avatar ha-icon').get_attribute('icon') == 'mdi:cat'
    # Restore valid attributes and verify editing, rejection, and explicit clearing.
    page.evaluate('()=>updateProfiles([a,b])')
    root.get_by_text('Créer ou modifier un profil', exact=True).click()
    root.get_by_label('Profil existant').select_option('cat_a')
    assert root.get_by_label('Couleur (#RRGGBB)').input_value() == '#123456'
    assert root.get_by_label('Photo locale (facultatif)').input_value() == '/local/pets/ok.png'
    root.get_by_label('Photo locale (facultatif)').fill('https://bad.invalid/pet.png')
    root.get_by_role('button', name='Enregistrer le profil').click()
    assert page.evaluate('calls.length') == 0
    assert 'invalide' in root.locator('ha-card').inner_text()
    root.get_by_label('Couleur (#RRGGBB)').fill('#abcdef')
    root.get_by_label('Photo locale (facultatif)').fill('/local/pets/ok.png')
    root.get_by_role('button', name='Enregistrer le profil').click()
    page.wait_for_function('calls.length===1 && !card.busy')
    assert page.evaluate('calls[0]') == ['mova_nutripal','save_pet_profile',
        {'pet_id':'cat_a','name':'Example A','target_kg':4,'baseline_date':'2024-10-01',
         'color':'#abcdef','photo_url':'/local/pets/ok.png'}, {'entity_id':'sensor.hub'}]
    root.get_by_label('Couleur (#RRGGBB)').fill('')
    root.get_by_label('Photo locale (facultatif)').fill('')
    root.get_by_role('button', name='Enregistrer le profil').click()
    page.wait_for_function('calls.length===2 && !card.busy')
    assert page.evaluate('calls[1][2].color') == ''
    assert page.evaluate('calls[1][2].photo_url') == ''
    # Responsive card with care entries and a real loaded image.
    page.set_viewport_size({'width':390,'height':800})
    assert root.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    assert not unexpected, unexpected
    assert not errors, errors
    page.close()
    print('Browser visual regression OK (local photo, missing photo, fallback, colors, care icons, profile edit, mobile)')


if __name__ == '__main__':
    with sync_playwright() as p:
        kwargs = {'executable_path':sys.argv[1]} if len(sys.argv)>1 else {}
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'], **kwargs)
        try:
            run(browser)
        finally:
            browser.close()
