/* Seyd Yar — georeferenced daily FTLE/LCS map. Coordinates come from NetCDF;
   NO latitude/longitude offsets from the unrelated reference frontend. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = (v, digits=3) => (Number.isFinite(v) && v !== -9999) ? Number(v).toFixed(digits) : 'No ocean data';
  const fieldNames = {
    ftle_smooth:'Attracting FTLE (1/hour)', ridge_support:'LCS ridge support',
    accumulation_potential_physics_first:'Relative aggregation score — physics-first (0–100)',
    accumulation_potential_balanced:'Relative aggregation score — balanced (0–100)',
    current_speed:'Surface current speed (m/s)', persistence_3d:'Persistence (3 days)',
    persistence_5d:'Persistence (5 days)', physics_first_composite:'Physics-first composite',
    balanced_composite:'Balanced composite'
  };
  if(typeof L === 'undefined') { $('message').hidden=false; $('message').textContent='Leaflet map library could not load; check CDN/network.'; return; }
  const map = L.map('map', {preferCanvas:true, zoomControl:true});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution:'© OpenStreetMap contributors', maxZoom:13
  }).addTo(map);
  const oceanOverlay = L.layerGroup().addTo(map);
  const vectorsOverlay = L.layerGroup().addTo(map);
  const ridgeOverlay = L.layerGroup().addTo(map);
  const clusterOverlay = L.layerGroup().addTo(map);
  const hotspotOverlay = L.layerGroup().addTo(map);
  L.control.layers(null, {
    'FTLE / current raster':oceanOverlay, 'LCS ridge lines':ridgeOverlay,
    'Accumulation clusters':clusterOverlay, 'Hotspots':hotspotOverlay,
    'Current direction arrows':vectorsOverlay
  }, {collapsed:true}).addTo(map);
  let manifest, selected=0, raster, field, interval, overlayBounds;
  let firstFit=true;
  let requestSerial=0;
  const nowDate = new Date();
  const isMissing = x => x == null || x === -9999 || !Number.isFinite(x);
  const color = (f) => {
    const z = Math.max(0,Math.min(1,f));
    const stops = [[10,46,91],[20,123,160],[53,177,166],[240,198,98],[236,95,61]];
    const p=z*4, i=Math.min(3,Math.floor(p)), t=p-i;
    return stops[i].map((v,c)=>Math.round(v*(1-t)+stops[i+1][c]*t));
  };
  const showError = e => { $('message').textContent = String(e?.message || e); $('message').hidden=false; };
  async function getJSON(url){const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(`Unable to load ${url}: ${r.status}`); return r.json();}
  function axisNearest(axis, value){
    if (!axis?.length) return -1;
    if(value < axis[0] || value > axis[axis.length-1]) return -1;
    const step=(axis[axis.length-1]-axis[0])/(axis.length-1);
    return Math.max(0,Math.min(axis.length-1,Math.round((value-axis[0])/step)));
  }
  function val(name,i,j){ const arr=field?.layers?.[name]; return arr ? arr[i*field.lat_axis.length+j] : NaN; }
  function sample(lat,lon){
    if(!field) return null;
    const i=axisNearest(field.lon_axis,lon),j=axisNearest(field.lat_axis,lat);
    if(i<0||j<0||val('ocean_mask',i,j)<0.5) return null;
    const speed=val('current_speed',i,j), u=val('current_u',i,j),v=val('current_v',i,j);
    const direction = !isMissing(u)&&!isMissing(v) ? (Math.atan2(u,v)*180/Math.PI+360)%360 : NaN;
    return {lat:field.lat_axis[j],lon:field.lon_axis[i],ftle:val('ftle_smooth',i,j),
      potential:val('accumulation_potential_physics_first',i,j), persistence:val('persistence_5d',i,j),
      speed,direction, ridge:val('ridge_support',i,j)};
  }
  function popupHtml(lat,lon,extra=''){
    const p=sample(lat,lon);
    if(!p) return `<b>Outside valid ocean cells</b><br>Lat ${lat.toFixed(5)}°, Lon ${lon.toFixed(5)}°<br>Masked: land, coast margin or missing data`;
    return `<b>${extra || 'Seyd Yar — ocean pixel'}</b><hr>
      <b>Latitude:</b> ${p.lat.toFixed(5)}°<br><b>Longitude:</b> ${p.lon.toFixed(5)}°<br>
      <b>FTLE:</b> ${fmt(p.ftle,5)} h⁻¹<br><b>Accumulation index:</b> ${fmt(p.potential,1)} / 100<br>
      <b>Ridge support:</b> ${fmt(p.ridge)}<br><b>Persistence 5d:</b> ${fmt(p.persistence)}<br>
      <b>Current speed:</b> ${fmt(p.speed,3)} m/s<br><b>Direction (to):</b> ${fmt(p.direction,1)}°<br>
      <small>Uncalibrated relative score, not a tuna presence/catch probability.</small>`;
  }
  map.on('click', e => L.popup({maxWidth:290}).setLatLng(e.latlng)
    .setContent(popupHtml(e.latlng.lat,e.latlng.lng)).openOn(map));
  function rasterize(layer){
    const nx=field.lon_axis.length, ny=field.lat_axis.length;
    const canvas=document.createElement('canvas');canvas.width=nx;canvas.height=ny;
    const ctx=canvas.getContext('2d'), img=ctx.createImageData(nx,ny);
    const raw=field.layers[layer] || field.layers.ftle_smooth;
    const finite=Array.from(raw).filter(v=>!isMissing(v));
    if(!finite.length) return canvas.toDataURL();
    const sorted=finite.slice().sort((a,b)=>a-b);
    const q=(r)=>sorted[Math.min(sorted.length-1,Math.max(0,Math.floor((sorted.length-1)*r)))];
    const lo=layer==='accumulation_potential_physics_first'||layer==='accumulation_potential_balanced' ? 0:q(0.03);
    const hi=layer==='accumulation_potential_physics_first'||layer==='accumulation_potential_balanced' ? 100:q(0.97);
    for(let j=0;j<ny;j++) for(let i=0;i<nx;i++){
      const v=raw[i*ny+j], wet=val('ocean_mask',i,j)>0.5;
      const a=4*((ny-1-j)*nx+i);
      if(isMissing(v)||!wet) {img.data[a+3]=0;continue;}
      const c=color((v-lo)/Math.max(1e-12,hi-lo));
      img.data[a]=c[0];img.data[a+1]=c[1];img.data[a+2]=c[2];img.data[a+3]=196;
    }
    ctx.putImageData(img,0,0);return canvas.toDataURL('image/png');
  }
  function redrawRaster(){
    if(!field) return;
    oceanOverlay.clearLayers();
    const lat=field.lat_axis,lon=field.lon_axis;
    const dy=lat.length>1?(lat[lat.length-1]-lat[0])/(lat.length-1):0;
    const dx=lon.length>1?(lon[lon.length-1]-lon[0])/(lon.length-1):0;
    overlayBounds=[[lat[0]-dy/2,lon[0]-dx/2],[lat[lat.length-1]+dy/2,lon[lon.length-1]+dx/2]];
    raster=L.imageOverlay(rasterize($('layerSelect').value),overlayBounds,{opacity:0.84,interactive:false}).addTo(oceanOverlay);
    if(firstFit){
      const b=field.metadata?.bbox;
      if(b && [b.lon_min,b.lon_max,b.lat_min,b.lat_max].every(Number.isFinite))
        map.fitBounds([[b.lat_min,b.lon_min],[b.lat_max,b.lon_max]]);
      else map.fitBounds(overlayBounds);
      firstFit=false;
    }
    $('legendTitle').textContent=fieldNames[$('layerSelect').value] || $('layerSelect').value;
  }
  function addVectors(){
    vectorsOverlay.clearLayers();
    const nx=field.lon_axis.length,ny=field.lat_axis.length;
    const step=Math.max(4,Math.ceil(Math.max(nx,ny)/19));
    for(let i=0;i<nx;i+=step)for(let j=0;j<ny;j+=step){
      if(val('ocean_mask',i,j)<0.5)continue;
      const u=val('current_u',i,j),v=val('current_v',i,j);
      if(isMissing(u)||isMissing(v))continue;
      const theta=Math.atan2(v,u);
      const lat=field.lat_axis[j],lon=field.lon_axis[i];
      const scale=Math.min(0.22,(field.lon_axis.at(-1)-field.lon_axis[0])/(nx/step*3));
      const dl=scale*Math.cos(theta),db=scale*Math.sin(theta);
      L.polyline([[lat,lon],[lat+db,lon+dl]],{color:'#fff',weight:2,opacity:0.8}).addTo(vectorsOverlay);
      L.circleMarker([lat+db,lon+dl],{radius:2,color:'#fff',weight:1,fillOpacity:1}).addTo(vectorsOverlay);
    }
  }
  function drawVectorsAndLines(){
    ridgeOverlay.clearLayers();clusterOverlay.clearLayers();hotspotOverlay.clearLayers();addVectors();
    for(const line of (field.ridges||[])){
      if(line.length<2)continue;
      L.polyline(line.map(p=>[p[1],p[0]]),{color:'#fff4a5',weight:2.1,opacity:0.95,bubblingMouseEvents:false})
        .bindPopup('LCS ridge — derived from attracting FTLE').addTo(ridgeOverlay);
    }
    for(const cluster of (field.clusters||[])){
      const coords=cluster.polygon_lonlat || [];
      if(coords.length<3) continue;
      L.polygon(coords.map(p=>[p[1],p[0]]),{color:'#f5c873',weight:1.5,fillOpacity:0.12,bubblingMouseEvents:false})
        .bindPopup(`Cluster ${Number(cluster.rank)||''}<br>Peak FTLE: ${fmt(cluster.peak_ftle,5)}`)
        .addTo(clusterOverlay);
    }
    for(const hs of (field.hotspots||[])){
      L.circleMarker([hs.lat,hs.lon],{radius:6,color:'#ffdf69',fillColor:'#f97355',fillOpacity:0.95,weight:2,bubblingMouseEvents:false})
        .bindPopup(popupHtml(hs.lat,hs.lon,`Hotspot #${hs.rank||''}`)).addTo(hotspotOverlay);
    }
  }
  function setPlaying(value){
    if(interval){clearInterval(interval);interval=null;}
    $('play').textContent=value?'⏸ Pause':'▶ Play';
    if(value && manifest.runs.length>1){interval=setInterval(()=>setRun((selected+1)%manifest.runs.length),1100);}
  }
  async function setRun(n){
    if(!manifest.runs.length)return;
    selected=Math.max(0,Math.min(manifest.runs.length-1,n));
    map.closePopup();
    $('dayRange').value=String(selected);
    const run=manifest.runs[selected];
    $('dayLabel').textContent=run.summary?.metadata?.requested_target_date_local||run.name;
    $('dayType').textContent=run.summary?.metadata?.data_kind==='forecast'?'FORECAST':'HISTORICAL / ANALYSIS';
    $('utcLabel').textContent=run.summary?.metadata?.actual_selected_utc||'—';
    $('runCount').textContent=`${selected+1} / ${manifest.runs.length}`;
    const qc = run.summary?.metadata?.numerical_quality;
    if($('qualityStatus')) {
      $('qualityStatus').textContent = qc
        ? `کیفیت عددی: ${qc.quality_flag || 'نامشخص'} | پوشش FTLE: ${Number(qc.valid_ftle_fraction_in_aoi*100).toFixed(1)}٪ | خطای گام: ${qc.refinement_warning ? 'نیازمند بررسی' : 'در آزمون نمونه‌ای مشاهده نشد'}`
        : 'گزارش کنترل کیفیت برای این روز موجود نیست';
    }
    const request=++requestSerial;
    try{
      const base=`runs/${encodeURIComponent(run.name)}/`;
      const next=await getJSON(base+'web_day.json');
      const res=await fetch(base+next.file,{cache:'no-store'});
      if(!res.ok)throw new Error(`Unable to load compact raster: ${res.status}`);
      const buffer=await res.arrayBuffer();
      if(request!==requestSerial)return;
      if(next.format!=='seyd-yaar-flat-f32-v1')throw new Error('Unknown map-data version');
      const count=next.shape[0]*next.shape[1];
      if(buffer.byteLength!==count*next.layers.length*4)throw new Error('Raster size does not match metadata');
      const all=new Float32Array(buffer);
      next.layers=Object.fromEntries(next.layers.map((name,k)=>[name,all.subarray(k*count,(k+1)*count)]));
      field=next; $('message').hidden=true;redrawRaster();drawVectorsAndLines();
      const q=next.metadata?.numerical_quality;
      if(q && (q.valid_ftle_fraction_in_aoi < 0.9 || q.refinement_warning)){$('message').textContent=`Numerical quality review required: ${(100*q.valid_ftle_fraction_in_aoi).toFixed(1)}% valid FTLE cells; RK4 step-refinement warning: ${Boolean(q.refinement_warning)}.`;$('message').hidden=false;}
      $('downloadRun').href=`runs/${encodeURIComponent(run.name)}/web_day.json`;
      $('downloadGeo').href=`runs/${encodeURIComponent(run.name)}/ridges.geojson`;
      $('downloadNC').href=`runs/${encodeURIComponent(run.name)}/summary.json`;
    }catch(err){if(request===requestSerial)showError(err);}
  }
  $('layerSelect').addEventListener('change',redrawRaster);
  $('dayRange').addEventListener('input',e=>{setPlaying(false);setRun(Number(e.target.value));});
  $('prev').addEventListener('click',()=>{setPlaying(false);setRun(selected-1);});
  $('next').addEventListener('click',()=>{setPlaying(false);setRun(selected+1);});
  $('play').addEventListener('click',()=>setPlaying(!interval));
  window.addEventListener('keydown',e=>{
    if(e.target?.tagName==='INPUT'||e.target?.tagName==='SELECT')return;
    if(e.key==='ArrowLeft'){setPlaying(false);setRun(selected-1);}
    if(e.key==='ArrowRight'){setPlaying(false);setRun(selected+1);}
  });
  async function init(){
    try{
      manifest=await getJSON('manifest.json');
      if(!manifest.runs?.length) throw new Error('No successful output days yet. Check run_report.json');
      $('dayRange').max=String(manifest.runs.length-1);
      $('dayRange').value='0';
      const vid=$('sequenceVideo');
      if(manifest.sequence_video){vid.src=manifest.sequence_video;vid.hidden=false;$('noVideo').hidden=true;}
      else {$('noVideo').hidden=false;}
      await setRun(manifest.runs.findIndex(x=>x.summary?.metadata?.data_kind==='forecast')-1 >= 0
        ? manifest.runs.findIndex(x=>x.summary.metadata.data_kind==='forecast')-1 : manifest.runs.length-1);
      const report=manifest.report;
      $('runReport').textContent=report ? `${report.outcomes.filter(o=>o.status==='success').length} successful · ${report.outcomes.filter(o=>o.status!=='success').length} skipped` : '';
    }catch(err){showError(err);map.setView([0,60],3);}
  }
  init();
})();
