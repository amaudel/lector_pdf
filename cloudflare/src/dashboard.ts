export const DASHBOARD_HTML = `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LECTOR PDF</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mut:#667085;--bd:#e4e7ec;--ac:#0b5fff;--ok:#067647;--wa:#b54708;--er:#b42318}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--tx:#e8eaee;--mut:#98a2b3;--bd:#2a2f3a;--ac:#6ea0ff;--ok:#47cd89;--wa:#fdb022;--er:#f97066}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 12px}h2{font-size:15px;margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px;margin-bottom:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--mut);font-size:12px}
button{background:var(--ac);color:#fff;border:0;border-radius:7px;padding:8px 12px;font:inherit;cursor:pointer}button.sec{background:transparent;color:var(--ac);border:1px solid var(--bd)}button:disabled{opacity:.5}
input[type=password],input[type=number]{padding:7px 9px;border:1px solid var(--bd);border-radius:7px;background:var(--bg);color:var(--tx);font:inherit}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.drop{border:2px dashed var(--bd);border-radius:10px;padding:22px;text-align:center;color:var(--mut)}.drop.on{border-color:var(--ac);color:var(--ac)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd);vertical-align:top}th{color:var(--mut);font-weight:600;font-size:12px}
.tag{display:inline-block;border-radius:99px;padding:1px 8px;font-size:12px;border:1px solid var(--bd)}.COMPLETADO,.ENCONTRADO{color:var(--ok)}.EN_PROCESO,.EN_COLA,.EN_INVESTIGACION{color:var(--wa)}.ERROR,.NO_ENCONTRADO,.DUPLICADO{color:var(--er)}
.wrap{overflow-x:auto}small{color:var(--mut)}#msg{min-height:20px;color:var(--mut)}
</style></head><body><main>
<h1>LECTOR PDF · Agente</h1>
<div class="card row"><input id="tk" type="password" placeholder="Token de acceso (API_TOKEN)" size="34"><button id="guardar" class="sec">Guardar</button><span id="msg"></span></div>
<div class="card"><div class="kpis" id="kpis"></div></div>
<div class="card"><h2>Agregar lotes nuevos</h2>
<div class="drop" id="drop">Arrastra aquí uno o varios .zip (o <label style="color:var(--ac);cursor:pointer">elígelos<input id="files" type="file" accept=".zip" multiple hidden></label>)</div>
<div class="row" style="margin-top:10px"><label><input type="checkbox" id="auto" checked> Procesar al subir</label><label><input type="checkbox" id="inv" checked> Investigar en internet lo que quede sin RUC</label>
<label>Máx. entidades por lote <input type="number" id="lim" value="5" min="0" max="50" style="width:70px"></label></div></div>
<div class="card"><h2>Acciones</h2><div class="row">
<button id="nuevos">Procesar todos los ZIP nuevos</button><button id="invest" class="sec">Investigar pendientes ahora</button><button id="csv" class="sec">Descargar CSV</button><button id="rf" class="sec">Actualizar</button></div></div>
<div class="card"><h2>Lotes</h2><div class="wrap"><table id="lotes"></table></div></div>
<div class="card"><h2>Entidades con RUC</h2><div class="wrap"><table id="ents"></table></div></div>
</main><script>
const $=s=>document.querySelector(s);const tk=()=>localStorage.getItem('tk')||'';
$('#tk').value=tk();$('#guardar').onclick=()=>{localStorage.setItem('tk',$('#tk').value.trim());say('Token guardado');load()};
const say=t=>$('#msg').textContent=t;
async function api(p,o={}){const r=await fetch('/api/'+p,{...o,headers:{...(o.headers||{}),authorization:'Bearer '+tk()}});if(r.status===401){say('Token inválido');throw 0}
if(!r.ok){say('Error '+r.status+': '+(await r.text()).slice(0,200));throw 0}return r}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){try{
const e=await (await api('estado')).json();
$('#kpis').innerHTML=[['ZIP en la nube',e.zips_total],['ZIP nuevos',e.zips_nuevos],['Lotes completados',e.lotes.COMPLETADO||0],['Entidades con RUC',e.entidades_maestro],['Sin RUC (por investigar)',e.pendientes],['Encontradas por el agente',e.agente.ENCONTRADO||0],['Revisión manual',e.agente.REVISION_MANUAL||0],['No encontradas',e.agente.NO_ENCONTRADO||0]].map(([a,b])=>'<div class="kpi"><b>'+b+'</b><span>'+a+'</span></div>').join('');
const l=await (await api('lotes')).json();
$('#lotes').innerHTML='<tr><th>Lote</th><th>Estado</th><th>Resumen</th><th>Inicio</th></tr>'+l.map(x=>'<tr><td>'+esc(x.lote)+'</td><td><span class="tag '+esc(x.estado)+'">'+esc(x.estado)+'</span></td><td><small>'+esc(x.resumen_corto)+'</small></td><td><small>'+esc(x.fecha_inicio||'')+'</small></td></tr>').join('');
const n=await (await api('entidades?limite=60')).json();
$('#ents').innerHTML='<tr><th>RUC</th><th>Razón social</th><th>Origen del RUC</th><th>Lotes</th><th>Menciones</th></tr>'+n.map(x=>'<tr><td>'+esc(x.ruc)+'</td><td>'+esc(x.razon_social_canonica)+'</td><td><small>'+esc(x.estado_resolucion_master)+'</small></td><td>'+x.total_lotes_detectado+'</td><td>'+x.total_menciones+'</td></tr>').join('');
}catch(e){}}
async function subir(files){let ok=0;for(const f of files){if(!/\\.zip$/i.test(f.name))continue;say('Subiendo '+f.name+'…');
try{const q=new URLSearchParams({procesar:$('#auto').checked?'1':'0',investigar:$('#inv').checked?'1':'0',limite:$('#lim').value});
await api('zips/'+encodeURIComponent(f.name)+'?'+q,{method:'PUT',body:f});ok++}catch(e){}}
say(ok+' ZIP subidos'+($('#auto').checked?' y en proceso':''));load()}
$('#files').onchange=e=>subir(e.target.files);
const d=$('#drop');d.ondragover=e=>{e.preventDefault();d.classList.add('on')};d.ondragleave=()=>d.classList.remove('on');d.ondrop=e=>{e.preventDefault();d.classList.remove('on');subir(e.dataTransfer.files)};
$('#nuevos').onclick=async()=>{const r=await (await api('procesar-nuevos',{method:'POST',body:JSON.stringify({investigar:$('#inv').checked,limite:+$('#lim').value})})).json();say(r.lanzados.length+' lotes lanzados, '+r.en_espera+' en espera');load()};
$('#invest').onclick=async()=>{const r=await (await api('investigar',{method:'POST',body:JSON.stringify({limite:+$('#lim').value||5})})).json();say('Investigación iniciada: '+r.id)};
$('#csv').onclick=async()=>{const b=await (await api('export.csv')).blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='entidades_enriquecidas.csv';a.click()};
$('#rf').onclick=load;load();setInterval(load,20000);
</script></body></html>`;
