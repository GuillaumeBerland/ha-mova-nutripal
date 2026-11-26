/* Local Lovelace card. No remote assets, no feeding commands, no localStorage. */
(() => {
  'use strict';
  const SVG = 'http://www.w3.org/2000/svg';
  const num = x => typeof x === 'number' && Number.isFinite(x);
  const dateOK = x => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x) && Number.isFinite(Date.parse(x));
  const txt = (tag, value, cls) => { const e = document.createElement(tag); if (value != null) e.textContent = String(value); if (cls) e.className = cls; return e; };
  function svg(tag, attrs, text) { const e = document.createElementNS(SVG, tag); Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k,String(v))); if (text != null) e.textContent = text; return e; }
  function sorted(rows) { return (Array.isArray(rows) ? rows : []).filter(r => r && dateOK(r.date) && num(r.grams) && r.grams > 0).slice().sort((a,b) => a.date.localeCompare(b.date)); }
  function getWeights(states, scope) {
    const out = new Map();
    if (!scope) return out;
    for (const [id,s] of Object.entries(states)) {
      const a = s.attributes || {};
      if (id.startsWith('sensor.') && a.health_scope === scope && typeof a.pet_id === 'string' && Array.isArray(a.measurements) && !['unknown','unavailable'].includes(s.state)) out.set(a.pet_id, s);
    }
    return out;
  }
  class MovaPetHealthCard extends HTMLElement {
    setConfig(config) {
      if (!/^sensor\.[a-z0-9_]+$/.test(config.entity || '')) throw new Error('Select the pet health sensor');
      this.config = {...config}; this.fr = config.language !== 'en'; this.lastHub = null; this.lastWeights = new Map();
      if (!this.shadowRoot) this.attachShadow({mode:'open'});
      this.build(); if (this._hass) this.hass = this._hass;
    }
    tr(fr,en) { return this.fr ? fr : en; }
    fmt(x, digits=3) { return num(x) ? x.toLocaleString(this.fr?'fr-FR':'en-GB',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—'; }
    getCardSize() { return 9; }
    getGridOptions() { return {columns:12, rows:'auto', min_columns:6}; }
    set hass(hass) {
      this._hass = hass;
      if (!this.config || !this.summary) return;
      const hub = hass.states[this.config.entity];
      const weights = getWeights(hass.states, hub?.attributes?.health_scope);
      const same = this.lastHub === hub && weights.size === this.lastWeights.size && [...weights].every(([k,v]) => this.lastWeights.get(k) === v);
      if (!same) { this.lastHub = hub; this.lastWeights = weights; this.refresh(); }
    }
    build() {
      this.shadowRoot.replaceChildren();
      const style = txt('style',`:host{display:block;max-width:1100px;margin:0 auto;width:100%} ha-card{padding:20px;box-sizing:border-box;color:var(--primary-text-color);font-family:inherit} h2,h3,p{margin:0 0 12px} h2{font-size:21px} h3{font-size:17px} .muted{color:var(--secondary-text-color);font-size:13px} .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:12px} .pet{border:1px solid var(--divider-color,#ddd);border-radius:12px;padding:14px;min-width:0} .food-row{border:1px solid var(--divider-color,#ddd);border-radius:12px;padding:12px;margin-top:12px;min-width:0;display:grid;gap:8px}.weight{font-size:29px;font-weight:650;font-variant-numeric:tabular-nums} .line{display:flex;justify-content:space-between;gap:10px;margin:7px 0} .track{height:8px;background:var(--divider-color,#ddd);border-radius:8px;overflow:hidden;margin:9px 0} .fill{height:100%;background:var(--primary-color,#039be5)} svg{width:100%;height:auto;display:block;margin:10px 0} details{margin:14px 0 0;border-top:1px solid var(--divider-color,#ddd);padding-top:12px} summary{cursor:pointer;font-weight:600} form{display:grid;gap:10px;margin-top:12px} label{display:grid;gap:4px;font-size:14px} input,select,button{box-sizing:border-box;font:inherit;color:inherit;background:var(--card-background-color,var(--primary-background-color));border:1px solid var(--divider-color,#888);border-radius:7px;padding:9px;min-width:0} button{cursor:pointer;background:var(--primary-color,#039be5);color:var(--text-primary-color,#fff);font-weight:600} button:disabled{opacity:.5;cursor:default} .check{display:flex;align-items:center;gap:8px} .check input{width:auto} .error{color:var(--error-color,#c33);white-space:pre-wrap} .status{min-height:1em;font-size:13px;white-space:pre-wrap} .scroll{overflow:auto;max-height:260px} table{border-collapse:collapse;width:100%;font-size:13px} td,th{padding:7px;text-align:left;border-bottom:1px solid var(--divider-color,#ddd)} .row{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,145px),1fr));gap:10px} [hidden]{display:none!important}`);
      const card = txt('ha-card'); card.append(txt('h2',this.tr('Santé · suivi du poids','Health · weight tracking')));
      this.summary = txt('div',this.tr('Chargement…','Loading…')); card.append(this.summary);
      this.forms = txt('div'); this.forms.hidden=true; card.append(this.forms); this.buildForms();
      card.append(txt('p',this.tr('Suivi local. Le poids cible est défini avec le vétérinaire ; aucune modification automatique des repas.','Local tracking. Set targets with your veterinarian; meals are never adjusted automatically.'),'muted'));
      this.shadowRoot.append(style,card);
    }
    field(form,label,type,opts={}) {
      const l=txt('label',label); const el=txt(type==='select'?'select':'input');
      if(type!=='select') el.type=type;
      Object.entries(opts).forEach(([k,v])=>{el[k]=v;}); l.append(el); form.append(l); return el;
    }
    option(select,value,label) { const o=txt('option',label); o.value=value; select.append(o); }
    buildForms() {
      const d=txt('details'); d.append(txt('summary',this.tr('Ajouter ou corriger une pesée','Add or correct a measurement'))); const f=txt('form'); d.append(f);
      this.pet=this.field(f,this.tr('Animal','Pet'),'select',{required:true});
      this.old=this.field(f,this.tr('Pesée existante (facultatif)','Existing measurement (optional)'),'select');
      this.day=this.field(f,'Date','date',{required:true});
      this.source=this.field(f,this.tr('Provenance','Source'),'select');
      [['home',this.tr('Domicile','Home')],['veterinarian',this.tr('Vétérinaire','Veterinarian')],['other',this.tr('Autre','Other')]].forEach(([v,l])=>this.option(this.source,v,l));
      this.method=this.field(f,this.tr('Méthode','Method'),'select'); this.option(this.method,'cage',this.tr('Avec cage','With carrier'));this.option(this.method,'direct',this.tr('Directe','Direct'));
      const row=txt('div',null,'row');f.append(row);
      const opt={min:'0.001',max:'30',step:'0.001',required:true};
      this.direct=this.field(row,this.tr('Poids direct (kg)','Direct weight (kg)'),'number',opt);
      this.gross=this.field(row,this.tr('Chat + cage (kg)','Pet + carrier (kg)'),'number',{...opt,max:'60'});
      this.cage=this.field(row,this.tr('Cage seule (kg)','Carrier only (kg)'),'number',opt);
      this.net=txt('p','','muted net');f.append(this.net);
      const check=txt('label',null,'check');this.replace=txt('input');this.replace.type='checkbox';check.append(this.replace,document.createTextNode(this.tr('Autoriser la correction de cette date','Allow replacement for this date')));f.append(check);
      this.save=txt('button',this.tr('Enregistrer la pesée','Save measurement'));this.save.type='submit';f.append(this.save);this.msg=txt('div','','status');this.msg.setAttribute('role','status');f.append(this.msg);
      this.pet.addEventListener('change',()=>{this.refreshOld();this.clearMeasurement();});
      this.old.addEventListener('change',()=>this.loadOld());
      this.method.addEventListener('change',()=>this.updateNet()); f.addEventListener('input',()=>this.updateNet());
      f.addEventListener('submit',e=>{e.preventDefault();this.saveMeasurement();});
      this.forms.append(d);
      const p=txt('details');p.append(txt('summary',this.tr('Créer ou modifier un profil','Create or edit a profile')));const pf=txt('form');p.append(pf);
      this.profileSelect=this.field(pf,this.tr('Profil existant','Existing profile'),'select');
      this.pid=this.field(pf,this.tr('Identifiant (a-z, 0-9, _)','ID (a-z, 0-9, _)'),'text',{required:true,maxLength:32,pattern:'[a-z0-9][a-z0-9_]{0,31}'});
      this.name=this.field(pf,this.tr('Nom','Name'),'text',{required:true,maxLength:64});
      this.target=this.field(pf,this.tr('Poids cible (kg)','Target (kg)'),'number',{...opt,required:false});
      this.baseline=this.field(pf,this.tr('Date de référence','Baseline date'),'date');
      pf.append(txt('p',this.tr('Les champs facultatifs vides conservent les valeurs existantes.','Blank optional fields preserve existing values.'),'muted'));
      this.psave=txt('button',this.tr('Enregistrer le profil','Save profile'));this.psave.type='submit';pf.append(this.psave);this.pmsg=txt('div','','status');this.pmsg.setAttribute('role','status');pf.append(this.pmsg);
      this.profileSelect.addEventListener('change',()=>this.loadProfile()); pf.addEventListener('submit',e=>{e.preventDefault();this.saveProfile();});this.forms.append(p);
      this.buildFoodForm();
      this.clearMeasurement();
    }
    buildFoodForm(){
      const d=txt('details');d.append(txt('summary',this.tr('Enregistrer ou corriger une période alimentaire','Record or correct a food period')));
      const f=txt('form');d.append(f);this.foodSelect=this.field(f,this.tr('Période existante','Existing period'),'select');
      this.foodDate=this.field(f,this.tr('Date de début','Start date'),'date',{required:true});
      this.foodName=this.field(f,this.tr('Nom du mélange','Mixture name'),'text',{required:true,maxLength:100});
      this.foodRows=txt('div');f.append(this.foodRows);this.foodFields=[];
      const add=txt('button',this.tr('Ajouter une croquette','Add a food'));add.type='button';add.addEventListener('click',()=>this.addFoodRow());f.append(add);
      this.foodRation=this.field(f,this.tr('Ration cible déclarée (g/jour, tous les animaux)','Declared target ration (g/day, all pets)'),'number',{min:'0.01',max:'10000',step:'0.01'});
      this.foodPortion=this.field(f,this.tr('Poids de référence déclaré (g/portion)','Declared reference weight (g/portion)'),'number',{min:'0.01',max:'100',step:'0.01'});
      const check=txt('label',null,'check');this.foodReplace=txt('input');this.foodReplace.type='checkbox';check.append(this.foodReplace,document.createTextNode(this.tr('Autoriser la correction de cette date','Allow replacement for this date')));f.append(check);
      f.append(txt('p',this.tr('Historique uniquement : ne modifie pas le réglage du distributeur. Les pourcentages sont exprimés en masse.','History only: does not change feeder settings. Percentages are by weight.'),'muted'));
      this.fsave=txt('button',this.tr('Enregistrer la période alimentaire','Save food period'));this.fsave.type='submit';f.append(this.fsave);this.fmsg=txt('div','','status');this.fmsg.setAttribute('role','status');f.append(this.fmsg);
      this.foodSelect.addEventListener('change',()=>this.loadFood());f.addEventListener('submit',e=>{e.preventDefault();this.saveFood();});this.forms.append(d);this.addFoodRow();
    }
    addFoodRow(c={}){
      if(this.foodFields.length>=10)return;
      const row=txt('div',null,'food-row');this.foodRows.append(row);
      const name=this.field(row,this.tr('Croquette','Food'),'text',{required:true,maxLength:100,value:c.name||''});
      const pct=this.field(row,this.tr('Part (%)','Share (%)'),'number',{required:true,min:'0.01',max:'100',step:'0.01',value:c.percent??''});
      const kcal=this.field(row,this.tr('Énergie (kcal/100 g, facultatif)','Energy (kcal/100 g, optional)'),'number',{min:'0.01',max:'900',step:'0.01',value:c.kcal_per_100g??''});
      const remove=txt('button',this.tr('Retirer cette croquette','Remove this food'));remove.type='button';const fields={name,pct,kcal};this.foodFields.push(fields);remove.addEventListener('click',()=>{if(this.foodFields.length>1){this.foodFields=this.foodFields.filter(x=>x!==fields);row.remove();}});row.append(remove);
    }
    loadFood(){
      const r=this.foodHistory.find(x=>x.start_date===this.foodSelect.value);this.foodDate.value=r?.start_date||this.today();this.foodName.value=r?.name||'';this.foodRation.value=r?.ration_g??'';this.foodPortion.value=r?.portion_g??'';this.foodReplace.checked=false;this.foodRows.replaceChildren();this.foodFields=[];for(const c of r?.components||[{}])this.addFoodRow(c);
    }
    async saveFood(){
      if(this.busy)return;
      const components=this.foodFields.map(x=>{const c={name:x.name.value,percent:Number(x.pct.value)};if(x.kcal.value!=='')c.kcal_per_100g=Number(x.kcal.value);return c;});
      if(components.reduce((a,c)=>a+Math.round(c.percent*100),0)!==10000){this.fmsg.textContent=this.tr('Le total doit être de 100 %.','Shares must total 100%.');return;}
      const period={start_date:this.foodDate.value,name:this.foodName.value,components};if(this.foodRation.value!=='')period.ration_g=Number(this.foodRation.value);if(this.foodPortion.value!=='')period.portion_g=Number(this.foodPortion.value);
      if(this.foodReplace.checked&&!window.confirm(this.tr('Remplacer la période de cette date ?','Replace the food period for this date?')))return;
      await this.action('record_food_period',{period,replace_existing:this.foodReplace.checked},this.fsave,this.fmsg);
    }
    foodCard(food){
      const a=txt('section',null,'food-row');a.append(txt('h3',this.tr('Alimentation · profil partagé','Food · shared profile')));
      const c=food?.current;const line=(label,value)=>{const l=txt('div',null,'line');l.append(txt('span',label,'muted'),txt('strong',value));a.append(l);};
      if(!c){a.append(txt('p',this.tr('Aucune période alimentaire enregistrée.','No recorded food period.')));return a;}
      a.append(txt('div',c.name,'weight'),txt('p',this.tr('Depuis ','Since ')+c.start_date,'muted'));
      for(const r of c.components||[])line(r.name,this.fmt(r.percent,2)+' %');
      line(this.tr('Ration cible déclarée','Declared target ration'),num(c.ration_g)?this.fmt(c.ration_g,2)+' g/j':'—');
      line(this.tr('Référence déclarée','Declared portion reference'),num(c.portion_g)?this.fmt(c.portion_g,2)+' g':'—');
      line(this.tr('Densité énergétique du mélange','Mixture energy density'),num(c.kcal_per_100g)?this.fmt(c.kcal_per_100g,2)+' kcal/100 g':'—');
      line(this.tr('Énergie de la ration cible (est.)','Target ration energy (est.)'),num(c.ration_kcal)?this.fmt(c.ration_kcal,2)+' kcal/j':'—');
      const detail=txt('details');detail.append(txt('summary',this.tr('Historique alimentaire','Food history')+` (${this.foodHistory.length})`));const wrap=txt('div',null,'scroll');
      for(const r of this.foodHistory.slice().reverse()){const b=txt('div',null,'food-row');b.append(txt('strong',r.start_date+' · '+r.name),txt('p',(r.components||[]).map(x=>`${x.name} : ${this.fmt(x.percent,2)} %`).join(' · '),'muted'));if(num(r.portion_g))b.append(txt('p',this.tr('Référence déclarée : ','Declared reference: ')+this.fmt(r.portion_g,2)+' g','muted'));wrap.append(b);}detail.append(wrap);a.append(detail);return a;
    }
    today() { try { return new Intl.DateTimeFormat('sv-SE',{timeZone:this._hass?.config?.time_zone||Intl.DateTimeFormat().resolvedOptions().timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); } catch { return ''; } }
    clearMeasurement() {this.day.value=this.today();this.direct.value='';this.gross.value='';this.cage.value='';this.replace.checked=false;this.old.value='';this.updateNet();}
    updateNet() {
      const cage=this.method.value==='cage';
      for(const [el,visible] of [[this.direct,!cage],[this.gross,cage],[this.cage,cage]]){el.parentElement.hidden=!visible;el.disabled=!visible;}
      const val=el=>el.value===''?NaN:Math.round(Number(el.value)*1000);
      const n=cage?val(this.gross)-val(this.cage):val(this.direct);
      this.net.textContent=this.tr('Poids net : ','Net weight: ')+(num(n)&&n>0?this.fmt(n/1000)+' kg':'—');
    }
    refreshOld() {
      const selected=this.old.value;this.old.replaceChildren();this.option(this.old,'',this.tr('Nouvelle pesée','New measurement'));
      for(const r of sorted(this.lastWeights.get(this.pet.value)?.attributes?.measurements).reverse()) this.option(this.old,r.date,`${r.date} · ${this.fmt(r.grams/1000)} kg`);
      if([...this.old.options].some(o=>o.value===selected))this.old.value=selected;
    }
    loadOld() {
      const r=sorted(this.lastWeights.get(this.pet.value)?.attributes?.measurements).find(r=>r.date===this.old.value);
      if(!r){this.clearMeasurement();return;} this.day.value=r.date;this.source.value=r.source;this.method.value=r.method;
      this.direct.value=r.method==='direct'?r.grams/1000:'';this.gross.value=r.method==='cage'?r.gross_grams/1000:'';this.cage.value=r.method==='cage'?r.cage_grams/1000:'';this.replace.checked=false;this.updateNet();
    }
    loadProfile(){const p=this.profiles.find(p=>p.pet_id===this.profileSelect.value);this.pid.readOnly=!!p;this.pid.value=p?.pet_id||'';this.name.value=p?.name||'';this.target.value=p?.target_kg??'';this.baseline.value=p?.baseline_date||'';}
    async action(service,data,button,msg) {
      if(this.busy || !this.lastHub || ['unknown','unavailable'].includes(this.lastHub.state))return false;
      this.busy=true;this.save.disabled=true;this.psave.disabled=true;this.fsave.disabled=true;msg.className='status';msg.textContent=this.tr('Enregistrement…','Saving…');
      try {await this._hass.callService('mova_nutripal',service,data,{entity_id:this.config.entity});msg.textContent=this.tr('Enregistré.','Saved.');return true;}
      catch(e){msg.className='status error';msg.textContent=this.tr('Échec : ','Failed: ')+(e?.message||String(e));return false;}
      finally{this.busy=false;this.save.disabled=!this.profiles?.length;this.psave.disabled=false;this.fsave.disabled=false;}
    }
    async saveMeasurement(){
      if(this.busy)return;
      const p=this.pet.value, d=this.day.value, r={date:d,source:this.source.value};
      if(!p||!d)return; if(this.method.value==='cage'){r.gross_kg=Number(this.gross.value);r.cage_kg=Number(this.cage.value);if(r.gross_kg<=r.cage_kg){this.msg.textContent=this.tr('Le poids brut doit dépasser la tare.','Gross weight must exceed carrier weight.');return;}}else r.weight_kg=Number(this.direct.value);
      if(this.replace.checked&&!window.confirm(this.tr('Remplacer la pesée de cette date ?','Replace the measurement for this date?')))return;
      if(await this.action('record_pet_weights',{pet_id:p,measurements:[r],replace_existing:this.replace.checked},this.save,this.msg))this.clearMeasurement();
    }
    async saveProfile(){
      if(this.busy)return;
      const data={pet_id:this.pid.value,name:this.name.value};if(this.target.value!=='')data.target_kg=Number(this.target.value);if(this.baseline.value)data.baseline_date=this.baseline.value;
      if(!this.profileSelect.value&&this.profiles.some(p=>p.pet_id===data.pet_id)){this.pmsg.textContent=this.tr('Identifiant déjà utilisé : sélectionne le profil existant.','ID already used: select the existing profile.');return;}
      await this.action('save_pet_profile',data,this.psave,this.pmsg);
    }
    refresh(){
      const hub=this.lastHub;const ready=!!hub&&!['unknown','unavailable'].includes(hub.state)&&Array.isArray(hub.attributes?.profiles);
      this.summary.replaceChildren(); this.forms.hidden=!ready;
      if(!ready){this.summary.append(txt('p',this.tr('Suivi santé indisponible.','Pet health unavailable.'),'error'));return;}
      this.profiles=hub.attributes.profiles.filter(p=>p&&typeof p.pet_id==='string');
      this.foodHistory=Array.isArray(hub.attributes.food?.history)?hub.attributes.food.history:[];
      const grid=txt('div',null,'cards');this.summary.append(grid);
      if(!this.profiles.length)grid.append(txt('p',this.tr('Aucun animal. Crée un profil ou importe tes pesées.','No pets. Create a profile or import measurements.')));
      for(const p of this.profiles)grid.append(this.petCard(p,this.lastWeights.get(p.pet_id)));
      this.summary.append(this.foodCard(hub.attributes.food));
      const fs=this.foodSelect.value;this.foodSelect.replaceChildren();this.option(this.foodSelect,'',this.tr('Nouvelle période','New period'));for(const r of this.foodHistory)this.option(this.foodSelect,r.start_date,r.start_date+' · '+r.name);if(this.foodHistory.some(r=>r.start_date===fs))this.foodSelect.value=fs;
      this.foodDate.max=this.today();if(!this.foodDate.value)this.foodDate.value=this.today();this.fsave.disabled=!!this.busy;
      const selected=this.pet.value, editing=this.profileSelect.value;this.pet.replaceChildren();this.profileSelect.replaceChildren();this.option(this.profileSelect,'',this.tr('Nouveau profil','New profile'));
      for(const p of this.profiles){this.option(this.pet,p.pet_id,p.name);this.option(this.profileSelect,p.pet_id,p.name);}
      if(this.profiles.some(p=>p.pet_id===selected))this.pet.value=selected;
      if(this.profiles.some(p=>p.pet_id===editing))this.profileSelect.value=editing;
      this.save.disabled=!!this.busy||!this.profiles.length; this.psave.disabled=!!this.busy; this.refreshOld(); if(!this.day.value)this.day.value=this.today();
      this.day.max=this.today();this.baseline.max=this.today();
    }
    petCard(p,s){
      const a=txt('section',null,'pet');a.append(txt('h3',p.name),txt('div',this.fmt(p.weight_kg)+' kg','weight'),txt('p',p.latest_date||this.tr('Pas de pesée','No measurements'),'muted'));
      const line=(label,value)=>{const l=txt('div',null,'line');l.append(txt('span',label,'muted'),txt('strong',value));a.append(l);};
      line(this.tr('Poids cible','Target'),num(p.target_kg)?this.fmt(p.target_kg,3)+' kg':'—');
      line(this.tr('Pesées enregistrées','Recorded weights'),num(p.measurement_count)?p.measurement_count:'—');
      line(this.tr('Référence','Baseline'),num(p.baseline_kg)?this.fmt(p.baseline_kg)+' kg · '+p.baseline_date:'—');
      line(this.tr('Depuis la référence','Since baseline'),num(p.change_grams)?`${p.change_grams>0?'+':''}${p.change_grams} g`+(num(p.change_percent)?` (${p.change_percent>0?'+':''}${this.fmt(p.change_percent,1)} %)`:''):'—');
      if(num(p.difference_to_target_grams))line(this.tr('Écart à la cible','Difference to target'),`${p.difference_to_target_grams>0?'+':''}${p.difference_to_target_grams} g`);
      if(num(p.baseline_kg)&&num(p.target_kg)&&num(p.weight_kg)&&p.baseline_kg!==p.target_kg){const progress=(p.baseline_kg-p.weight_kg)/(p.baseline_kg-p.target_kg)*100;const t=txt('div',null,'track'),f=txt('div',null,'fill');f.style.width=Math.max(0,Math.min(100,progress))+'%';t.append(f);a.append(t,txt('p',this.tr('Progression vers la cible : ','Progress toward target: ')+this.fmt(progress,1)+' %','muted'));}
      const rows=sorted(s?.attributes?.measurements);if(rows.length){a.append(this.graph(rows,p));const detail=txt('details');detail.append(txt('summary',this.tr('Historique des pesées','Weight history')+` (${rows.length})`));const wrap=txt('div',null,'scroll'),table=txt('table'),head=txt('tr');[this.tr('Date','Date'),this.tr('Poids','Weight'),this.tr('Source','Source')].forEach(v=>head.append(txt('th',v)));table.append(head);for(const r of rows.slice().reverse()){const tr=txt('tr');const source={home:this.tr('Domicile','Home'),veterinarian:this.tr('Vétérinaire','Veterinarian'),other:this.tr('Autre','Other')}[r.source]||r.source;[r.date,this.fmt(r.grams/1000)+' kg',source].forEach(v=>tr.append(txt('td',v)));table.append(tr);}wrap.append(table);detail.append(wrap);a.append(detail);}else a.append(txt('p',this.tr('Historique non disponible pour ce capteur.','History unavailable for this sensor.'),'muted'));
      return a;
    }
    graph(all,p){
      const wrapper=txt('div');const select=txt('select');select.setAttribute('aria-label',this.tr('Période du graphique','Chart period'));this.option(select,'baseline',this.tr('Depuis la référence','Since baseline'));this.option(select,'all',this.tr('Tout l’historique','All history'));wrapper.append(select);const chart=txt('div');wrapper.append(chart);
      const draw=()=>{let rows=select.value==='baseline'&&p.baseline_date?all.filter(r=>r.date>=p.baseline_date):all;if(!rows.length)rows=all;chart.replaceChildren();const values=rows.map(r=>r.grams/1000);if(num(p.target_kg))values.push(p.target_kg);let min=Math.floor((Math.min(...values)-.05)*10)/10,max=Math.ceil((Math.max(...values)+.05)*10)/10;if(max<=min)max=min+.1;const first=Date.parse(rows[0].date),last=Date.parse(rows.at(-1).date),x=d=>first===last?180:43+(Date.parse(d)-first)/(last-first)*295,y=v=>145-(v-min)/(max-min)*125;
      const g=svg('svg',{viewBox:'0 0 350 177',role:'img','aria-label':this.tr('Courbe de poids datée','Dated weight chart')});
      for(let i=0;i<=4;i++){const v=min+(max-min)*i/4,yy=y(v);g.append(svg('line',{x1:43,x2:338,y1:yy,y2:yy,stroke:'currentColor',opacity:.15}),svg('text',{x:37,y:yy+3,'text-anchor':'end','font-size':10,fill:'currentColor'},this.fmt(v,2)));}
      if(num(p.target_kg))g.append(svg('line',{x1:43,x2:338,y1:y(p.target_kg),y2:y(p.target_kg),stroke:'var(--success-color,#279557)','stroke-dasharray':'5 4','stroke-width':1.5}));
      for(const r of this.foodHistory||[]){if(first!==last&&Date.parse(r.start_date)>=first&&Date.parse(r.start_date)<=last){const xx=x(r.start_date);const marker=svg('line',{x1:xx,x2:xx,y1:20,y2:145,stroke:'var(--secondary-text-color,#888)','stroke-dasharray':'2 3','stroke-width':1.5});marker.append(svg('title',{},r.start_date+' · '+r.name));g.append(marker);}}
      g.append(svg('polyline',{points:rows.map(r=>`${x(r.date)},${y(r.grams/1000)}`).join(' '),stroke:'var(--primary-color,#039be5)','stroke-width':2,fill:'none','stroke-linejoin':'round'}));
      for(const r of rows){const c=svg('circle',{cx:x(r.date),cy:y(r.grams/1000),r:3,fill:'var(--primary-color,#039be5)'});c.append(svg('title',{},`${r.date} · ${this.fmt(r.grams/1000)} kg`));g.append(c);}
      g.append(svg('text',{x:43,y:165,'font-size':10,fill:'currentColor'},rows[0].date));if(first!==last)g.append(svg('text',{x:338,y:165,'text-anchor':'end','font-size':10,fill:'currentColor'},rows.at(-1).date));chart.append(g);if(num(p.target_kg))chart.append(txt('p',this.tr('Pointillés : poids cible','Dashed line: target weight'),'muted'));if((this.foodHistory||[]).some(r=>Date.parse(r.start_date)>=first&&Date.parse(r.start_date)<=last))chart.append(txt('p',this.tr('Repères verticaux : changements alimentaires déclarés.','Vertical markers: recorded food changes.'),'muted'));};select.addEventListener('change',draw);draw();return wrapper;
    }
  }
  if (!customElements.get('mova-pet-health-card')) customElements.define('mova-pet-health-card',MovaPetHealthCard);
})();
