// Mini Contable UI logic backed by REST API
(function(){
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
  const qs = new URLSearchParams(location.search);
  const empresa = (document.querySelector('.msc-body')?.dataset?.empresa) || qs.get('empresa') || '';
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const csrfFetch = (url, opts = {}) => {
    const headers = { ...(opts.headers || {}) };
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }
    return fetch(url, { credentials: 'same-origin', ...opts, headers });
  };
  let cuentas = [];
  let asientos = [];
  let tempLineas = [];

  function initTabs(){
    const secciones = [
      {id:'sec-cuentas', label:'Plan de Cuentas'},
      {id:'sec-diario', label:'Libro Diario'},
    ];
    const tabs = $('#tabs');
    tabs.innerHTML = '';
    secciones.forEach((s,i)=>{
      const b = document.createElement('button');
      b.textContent = s.label; b.dataset.for = s.id; if(i===0) b.classList.add('active');
      b.onclick = ()=>{ $$('#tabs button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); secciones.forEach(ss=>$('#'+ss.id).classList.add('hidden')); $('#'+s.id).classList.remove('hidden'); };
      tabs.appendChild(b);
    });
    secciones.slice(1).forEach(ss=>$('#'+ss.id).classList.add('hidden'));
  }

  const fmt = (n)=> (Number(n)||0).toLocaleString('es-AR',{minimumFractionDigits:2, maximumFractionDigits:2});
  const parseNum = (v)=>{ const n = Number(String(v).replace(/\./g,'').replace(',','.')); return isNaN(n)?0:n; };
  const SUBRUBROS = {
    'Activo': ['Activo Corriente', 'Activo No Corriente', 'Otros Activos'],
    'Pasivo': ['Pasivo Corriente', 'Pasivo No Corriente', 'Otros Pasivos'],
    'Patrimonio Neto': ['Capital', 'Resultados Acumulados', 'Resultados del Ejercicio'],
    'Cuentas de Resultado': [
      'Ingresos (o Ventas)',
      'Egresos (o Costos)',
      'Gastos de Administración',
      'Gastos de Comercialización',
      'Gastos Financieros y Otros',
      'Otros Ingresos y Egresos'
    ]
  };
  function fillSubrubros(){
    const rubroSel = $('#accRubro'); const subSel = $('#accSubName'); if(!rubroSel || !subSel) return;
    const t = rubroSel.value || 'Activo';
    const opts = SUBRUBROS[t] || [];
    subSel.innerHTML = '<option value="">— Elegir —</option>' + opts.map(s=>`<option value="${s}">${s}</option>`).join('');
  }

  function renderCuentas(){
    const tb = $('#tablaCuentas tbody'); if(!tb) return; tb.innerHTML = '';
    cuentas.forEach(acc=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="monospace">${acc.cod_rubro || ''}</td><td>${acc.cuenta}</td><td>${acc.rubro || ''}</td><td>${acc.subrubro || ''}</td>
        <td></td>`;
      tb.appendChild(tr);
    });
    const optionsHTML = cuentas.map(c=>`<option value="${c.id_cuenta}">${c.cuenta}</option>`).join('');
    $$('#tablaEntrada tbody tr select.account').forEach(s=>{ const prev = s.value; s.innerHTML = optionsHTML; if(prev) s.value = prev; });
    const mayorSel = $('#selMayor'); if(mayorSel){ mayorSel.innerHTML = '<option value="">— Elegir —</option>' + cuentas.map(c=>`<option value="${c.id_cuenta}">${c.cuenta}</option>`).join(''); }
  }

  function lineaRow(l){
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><select class="account">${cuentas.map(c=>`<option value="${c.id_cuenta}" ${String(l?.id_cuenta)===String(c.id_cuenta)?'selected':''}>${c.cuenta}</option>`).join('')}</select></td>
      <td><input class="debe" type="number" min="0" step="0.01" value="${l?l.debe:0}" /></td>
      <td><input class="haber" type="number" min="0" step="0.01" value="${l?l.haber:0}" /></td>
      <td><button class="btn ghost del">Quitar</button></td>`;
    return tr;
  }

  function renderEntrada(){ const tb = $('#tablaEntrada tbody'); if(!tb) return; tb.innerHTML = ''; tempLineas.forEach(l=> tb.appendChild(lineaRow(l)) ); totalesEntrada(); }
  function totalesEntrada(){
    const rows = $$('#tablaEntrada tbody tr'); let d=0,h=0; rows.forEach(r=>{ d += parseNum(r.querySelector('.debe').value); h += parseNum(r.querySelector('.haber').value); });
    const td = $('#totDebe'), th=$('#totHaber'); if(td) td.textContent = fmt(d); if(th) th.textContent = fmt(h);
    const pill = $('#infoDescuadre'); if(!pill) return; pill.textContent = d===h? 'Cuadrado ✔' : `Descuadre: ${fmt(Math.abs(d-h))}`; pill.className = 'pill ' + (d===h? 'ok':'bad');
  }

  // Función global para eliminar asientos
  window.eliminarAsiento = async function(index) {
    console.log('Eliminando asiento en índice:', index);
    if (index < 0 || index >= asientos.length) {
      console.error('Índice de asiento inválido:', index);
      return;
    }
    
    const asientoAEliminar = asientos[index];
    
    if (!confirm('¿Estás seguro de que deseas eliminar este asiento? Esta acción no se puede deshacer.')) {
      return;
    }

    try {
      // Obtener el ID del asiento a eliminar
      const idAsiento = asientoAEliminar.id_asiento;
      if (!idAsiento) {
        throw new Error('El asiento no tiene un ID válido');
      }

      // Enviar petición al servidor para eliminar el asiento
      const response = await csrfFetch(`/accounting/api/asientos/${idAsiento}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        }
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Error al eliminar el asiento');
      }

      // Si la eliminación en el servidor fue exitosa, actualizar la vista local
      asientos.splice(index, 1);
      
      // Actualizar todas las vistas
      renderDiario();
      renderMayor();
      renderTrial();
      renderEstados();
      renderTodo();
      
      // Mostrar mensaje de éxito
      alert('El asiento ha sido eliminado correctamente de la base de datos.');
      
    } catch (error) {
      console.error('Error al eliminar el asiento:', error);
      alert(`Error al eliminar el asiento: ${error.message}`);
      
      // Recargar los datos del servidor para restaurar el estado
      try {
        await loadAsientos();
        renderDiario();
        renderTodo();
      } catch (e) {
        console.error('Error al recargar los datos:', e);
      }
    }
  };

  function renderDiario(){
    const tb = $('#tablaDiario tbody'); if(!tb) return; tb.innerHTML='';
    const list = asientos; // backend ya entrega desc (más nuevos arriba)
    list.forEach((a,idx)=>{
      const totalD = a.detalles.reduce((s,l)=>s + (l.tipo==='debe'? l.importe:0),0);
      const totalH = a.detalles.reduce((s,l)=>s + (l.tipo==='haber'? l.importe:0),0);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${a.fecha}</td>
        <td>${a.leyenda||''}</td>
        <td class="monospace">${fmt(totalD)}</td>
        <td class="monospace">${fmt(totalH)}</td>
        <td>
          <button class="btn ghost ver" data-i="${idx}">Ver</button>
          <button class="btn ghost danger" onclick="window.eliminarAsiento(${idx}); return false;">Borrar</button>
        </td>`;
      tb.appendChild(tr);
      const tr2 = document.createElement('tr');
      const det = a.detalles.map(l=>{
        const accn = l.cuenta || l.id_cuenta;
        return `${accn}: ${l.tipo==='debe'? 'Debe '+fmt(l.importe) : 'Haber '+fmt(l.importe)}`;
      }).join('<br/>');
      tr2.innerHTML = `<td></td><td colspan="4" class="hint">${det}</td>`;
      tb.appendChild(tr2);
    });
  }
  async function renderMayor(){
    const id = $('#selMayor')?.value; const tb = $('#tablaMayor tbody'); if(!tb) return; tb.innerHTML='';
    if(!id){ const si=$('#saldoInfo'); if(si) si.textContent='—'; return; }
    const qs = new URLSearchParams(); qs.set('cuenta', id); if(empresa) qs.set('empresa', empresa);
    const res = await fetch(`/accounting/api/mayor?${qs.toString()}`, { credentials: 'same-origin' });
    if(!res.ok){ const si=$('#saldoInfo'); if(si) si.textContent='—'; return; }
    const data = await res.json();
    data.movimientos.forEach(m=>{ const tr = document.createElement('tr'); tr.innerHTML = `<td>${m.fecha}</td><td>${m.concepto||''}</td><td class="monospace">${m.debe?fmt(m.debe):''}</td><td class="monospace">${m.haber?fmt(m.haber):''}</td><td class="monospace">${fmt(Math.abs(m.saldo))}</td>`; tb.appendChild(tr); });
    const si=$('#saldoInfo'); if(si) si.textContent = `Saldo ${data.side}: ${fmt(Math.abs(data.saldo))}`;
  }

  async function renderTrial(){
    const tb = $('#tablaTrial tbody'); if(!tb) return; tb.innerHTML='';
    const url = empresa? `/accounting/api/balance?empresa=${empresa}` : `/accounting/api/balance`;
    const res = await fetch(url, { credentials: 'same-origin' }); if(!res.ok) return;
    const data = await res.json(); let td=0, th=0;
    data.rows.forEach(r=>{ const tr = document.createElement('tr'); tr.innerHTML = `<td class="monospace">${r.cod_rubro||''}</td><td>${r.cuenta}</td><td class="monospace">${r.deudor?fmt(r.deudor):''}</td><td class="monospace">${r.acreedor?fmt(r.acreedor):''}</td>`; tb.appendChild(tr); td+=r.deudor||0; th+=r.acreedor||0; });
    const tde=$('#trialDebe'), tha=$('#trialHaber'); if(tde) tde.textContent = fmt(td); if(tha) tha.textContent = fmt(th);
    const chk=$('#chkBalance'); if(chk){ chk.textContent = data.cuadra ? 'Cuadra ✔' : 'No cuadra ✖'; chk.className = 'pill ' + (data.cuadra? 'ok':'bad'); }
  }

  async function renderEstados(){
    const url = empresa? `/accounting/api/estados?empresa=${empresa}` : `/accounting/api/estados`;
    const res = await fetch(url, { credentials: 'same-origin' }); if(!res.ok) return;
    const data = await res.json();
    const erBody = $('#tablaER tbody'); if(erBody){ erBody.innerHTML=''; [['Ingresos', data.er.ingresos], ['Gastos', data.er.gastos]].forEach(([n,v])=>{ const tr = document.createElement('tr'); tr.innerHTML = `<td>${n}</td><td class="monospace">${fmt(v)}</td>`; erBody.appendChild(tr); }); const erUtil=$('#erUtil'); if(erUtil) erUtil.textContent = fmt(data.er.utilidad); }
    const bgBody = $('#tablaBG tbody'); if(bgBody){ bgBody.innerHTML=''; const push = (n,v)=>{ const tr=document.createElement('tr'); tr.innerHTML=`<td>${n}</td><td class="monospace">${fmt(v)}</td>`; bgBody.appendChild(tr); }; push('Activo', data.bg.activo); push('Pasivo', data.bg.pasivo); push('Patrimonio (antes de utilidad)', data.bg.patrimonio); push('Utilidad del período', data.er.utilidad); }
    const bgAct=$('#bgAct'), bgPP=$('#bgPP'); if(bgAct) bgAct.textContent = fmt(data.bg.activo); if(bgPP) bgPP.textContent = fmt(data.bg.pasivo_patrimonio_utilidad);
  }

  function renderTodo(){ /* trasladado a Reportes */ }

  function bindEvents(){
    const addAcc = $('#addAcc');
    if(addAcc){
      addAcc.onclick = async ()=>{
        const codigo = $('#accCode').value.trim();
        const nombre = $('#accName').value.trim();
        const tipo = $('#accRubro').value;
        const cod_subrubro = $('#accSubCode')?.value.trim() || '';
        const subrubro = $('#accSubName')?.value || '';
        if(!nombre) return alert('Completá código y nombre');
        try{
          const payload = { codigo, nombre, tipo };
          if (subrubro) payload.subrubro = subrubro;
          if (cod_subrubro) payload.cod_subrubro = cod_subrubro;
          if(empresa) payload.empresa = parseInt(empresa,10);
          const res = await csrfFetch('/accounting/api/cuentas', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
          if(!res.ok){ const t = await res.text(); throw new Error(t); }
          $('#accCode').value=''; $('#accName').value=''; if($('#accSubCode')) $('#accSubCode').value=''; if($('#accSubName')) $('#accSubName').selectedIndex=0;
          await loadCuentas(); renderCuentas();
        }catch(err){ alert('Error al crear cuenta: '+err.message); }
      };
    }
    const rubroSel = $('#accRubro'); if(rubroSel){ rubroSel.addEventListener('change', fillSubrubros); fillSubrubros(); }
    const addLinea = $('#addLinea'); if(addLinea){ addLinea.onclick = ()=>{ if(!cuentas.length) return alert('Agregá cuentas primero'); tempLineas.unshift({id_cuenta:cuentas[0].id_cuenta, debe:0, haber:0}); renderEntrada(); }; }
    const tablaEntrada = $('#tablaEntrada'); if(tablaEntrada){
      tablaEntrada.addEventListener('input', (e)=>{ const row = e.target.closest('tr'); if(!row) return; const idx = Array.from(row.parentNode.children).indexOf(row); tempLineas[idx].id_cuenta = parseInt(row.querySelector('.account').value,10); tempLineas[idx].debe = parseNum(row.querySelector('.debe').value); tempLineas[idx].haber = parseNum(row.querySelector('.haber').value); if(tempLineas[idx].debe>0) { row.querySelector('.haber').value = 0; tempLineas[idx].haber=0; } if(tempLineas[idx].haber>0){ row.querySelector('.debe').value = 0; tempLineas[idx].debe=0; } totalesEntrada(); });
      tablaEntrada.addEventListener('click', (e)=>{ if(e.target.classList.contains('del')){ const row = e.target.closest('tr'); const idx = Array.from(row.parentNode.children).indexOf(row); tempLineas.splice(idx,1); renderEntrada(); } });
    }
    const addAsiento = $('#addAsiento'); if(addAsiento){ addAsiento.onclick = async ()=>{ const fecha = $('#jeDate').value || new Date().toISOString().slice(0,10); const concepto = $('#jeConcepto').value.trim() || 'Sin concepto'; const rows = $$('#tablaEntrada tbody tr'); if(rows.length<2) return alert('Agregá al menos dos líneas'); let d=0,h=0; const renglones = []; for(const r of rows){ const id_cuenta = parseInt(r.querySelector('.account').value,10); const debe = parseNum(r.querySelector('.debe').value); const haber = parseNum(r.querySelector('.haber').value); if(debe===0 && haber===0) continue; const tipo = debe>0? 'debe':'haber'; const importe = debe>0? debe:haber; renglones.push({id_cuenta, tipo, importe}); d+=debe; h+=haber; } if(renglones.length<2) return alert('Completá importes'); if(Math.abs(d-h) > 0.005) return alert('El asiento no está cuadrado'); try{ const payload = { fecha, doc: '', leyenda: concepto, renglones }; if(empresa) payload.empresa = parseInt(empresa,10); const res = await csrfFetch('/accounting/api/asientos', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }); if(!res.ok){ const t = await res.text(); throw new Error(t); } await loadAsientos(); tempLineas = []; $('#jeConcepto').value=''; renderEntrada(); renderDiario(); renderTodo(); }catch(err){ alert('Error al guardar: '+err.message); } }; }
    // Mayor/Balance/Estados trasladados a Reportes
  }

  async function loadCuentas(){ const url = empresa? `/accounting/api/cuentas?empresa=${empresa}` : `/accounting/api/cuentas`; const res = await fetch(url, { credentials: 'same-origin' }); cuentas = res.ok ? await res.json() : []; }
  async function loadAsientos(){ const url = empresa? `/accounting/api/asientos?empresa=${empresa}` : `/accounting/api/asientos`; const res = await fetch(url, { credentials: 'same-origin' }); asientos = res.ok ? await res.json() : []; }
  async function init(){
    initTabs(); await loadCuentas(); await loadAsientos(); renderCuentas(); renderDiario(); renderEntrada(); renderTodo(); bindEvents();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
