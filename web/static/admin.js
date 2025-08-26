async function request(path, opts = {}){
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function q(sel){return document.querySelector(sel)}

function showTab(name){
  document.querySelectorAll('.tab').forEach(el=>el.classList.remove('active'))
  const t = document.getElementById(name)
  if (t) t.classList.add('active')
}

document.addEventListener('DOMContentLoaded', ()=>{
  // tabs
  document.querySelectorAll('.tabs button').forEach(b=>{
    b.addEventListener('click', ()=>showTab(b.dataset.target))
  })
  showTab('triggers')

  // triggers
  const listTriggers = async ()=>{
    const out = q('#triggers_list')
    try{
      const ts = await request('/admin/triggers')
      out.innerHTML = `<table><tr><th>id</th><th>pattern</th><th>response</th><th></th></tr>${ts.map(t=>`<tr><td>${t.id}</td><td>${t.regex_pattern}</td><td>${t.response_text||''}</td><td><button data-id="${t.id}" class="del">Delete</button></td></tr>`).join('')}</table>`
      out.querySelectorAll('.del').forEach(b=>b.addEventListener('click', async ()=>{ await request('/admin/triggers/'+b.dataset.id,{method:'DELETE'}); listTriggers() }))
    }catch(e){ out.textContent = 'Error: '+e.message }
  }
  q('#t_create').addEventListener('click', async ()=>{
    try{
      await request('/admin/triggers',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({regex_pattern:q('#t_regex').value,response_type_id:1,response_text:q('#t_response').value})})
      q('#t_regex').value=''; q('#t_response').value=''
      listTriggers()
    }catch(e){ alert('Create failed: '+e.message) }
  })
  listTriggers()

  // alerts list
  const listAlerts = async ()=>{
    const out = q('#alerts_list')
    try{
      const as = await request('/admin/alerts')
      out.innerHTML = `<ul>${as.map(a=>`<li>${a.alert_name} (id:${a.id})</li>`).join('')}</ul>`
    }catch(e){ out.textContent = 'Error: '+e.message }
  }
  listAlerts()

  // assets list
  const listAssets = async ()=>{
    const out = q('#assets_list')
    try{
      const as = await request('/admin/assets')
      out.innerHTML = `<ul>${as.map(a=>`<li>${a.short_name} - ${a.asset_kind}</li>`).join('')}</ul>`
    }catch(e){ out.textContent = 'Error: '+e.message }
  }
  listAssets()

  // create asset
  q('#as_create').addEventListener('click', async ()=>{
    try{
      await request('/admin/assets',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({short_name:q('#as_name').value,asset_kind:q('#as_kind').value,file_path:q('#as_path').value})})
      q('#as_name').value=''; q('#as_path').value=''
      listAssets()
    }catch(e){ alert('Create asset failed: '+e.message) }
  })

  // create alert
  q('#a_create').addEventListener('click', async ()=>{
    try{
      await request('/admin/alerts',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({alert_name:q('#a_name').value,audio_asset_id:q('#a_audio').value,visual_asset_id:q('#a_visual').value})})
      q('#a_name').value=''; q('#a_audio').value=''; q('#a_visual').value=''
      listAlerts();
    }catch(e){ alert('Create alert failed: '+e.message) }
  })

  // twitch config
  const loadConfig = async ()=>{
    try{
      const cfg = await request('/admin/config')
      q('#tc_client').value = cfg.client_id || ''
      q('#tc_secret').value = cfg.client_secret || ''
      q('#tc_channel').value = cfg.channel || ''
      q('#tc_redirect').value = cfg.redirect_uri || ''
    }catch(e){ /* ignore */ }
  }
  q('#tc_save').addEventListener('click', async ()=>{
    try{
      await request('/admin/config',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({client_id:q('#tc_client').value,client_secret:q('#tc_secret').value,channel:q('#tc_channel').value,redirect_uri:q('#tc_redirect').value})})
      alert('Saved')
    }catch(e){ alert('Save failed: '+e.message) }
  })
  loadConfig()

  // admin auth UI
  function showAuthFields(mode){
    q('#aa_api').style.display = (mode === 'api_key') ? 'flex' : 'none'
    q('#aa_basic').style.display = (mode === 'basic') ? 'flex' : 'none'
  }
  q('#aa_mode').addEventListener('change', ()=> showAuthFields(q('#aa_mode').value))

  const loadAdminAuth = async ()=>{
    try{
      const cfg = await request('/admin/config')
      const mode = cfg.admin_auth_mode || 'none'
      q('#aa_mode').value = mode
      showAuthFields(mode)
      q('#aa_api_key').value = cfg.admin_api_key || ''
      q('#aa_basic_user').value = cfg.admin_basic_user || ''
      q('#aa_basic_pass').value = cfg.admin_basic_pass || ''
    }catch(e){ /* ignore */ }
  }
  q('#aa_save').addEventListener('click', async ()=>{
    try{
      const payload = {
        admin_auth_mode: q('#aa_mode').value,
        admin_api_key: q('#aa_api_key').value,
        admin_basic_user: q('#aa_basic_user').value,
        admin_basic_pass: q('#aa_basic_pass').value
      }
      await request('/admin/config',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})
      alert('Saved')
    }catch(e){ alert('Save failed: '+e.message) }
  })
  loadAdminAuth()

  // regex tester
  q('#rt_run').addEventListener('click', ()=>{
    try{
      const re = new RegExp(q('#rt_pattern').value)
      const m = re.exec(q('#rt_text').value)
      q('#rt_out').textContent = m ? JSON.stringify(m) : 'No match'
    }catch(e){ q('#rt_out').textContent = 'Error: '+e.message }
  })

  q('#tt_send').addEventListener('click', async ()=>{
    try{
      const payload = {user:q('#tt_user').value, message:q('#tt_msg').value}
      const r = await request('/trigger',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})
      q('#tt_out').textContent = JSON.stringify(r)
    }catch(e){ q('#tt_out').textContent = 'Error: '+e.message }
  })
})
