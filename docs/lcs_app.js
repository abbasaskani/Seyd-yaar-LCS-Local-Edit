/* Seyd Yar LCS — map viewer v8, applied ONLY to this LCS project.
   Coordinates and observations come from the scientific NetCDF-derived web raster.
   No arbitrary lat/lon offsets; Gamma/Min/Max only change visualization. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = (v, d=3) => Number.isFinite(v) && v !== -9999 ? Number(v).toFixed(d) : 'بدون داده';
  const missing = v => v == null || v === -9999 || !Number.isFinite(v);
  const label = {
    ftle_smooth: 'Backward FTLE (h⁻¹)', ridge_support:'Ridge support',
    accumulation_potential_physics_first:'شاخص نسبی تجمع / فیزیکی (۰ تا ۱۰۰)',
    accumulation_potential_balanced:'شاخص نسبی تجمع / متوازن (۰ تا ۱۰۰)',
    current_speed:'سرعت جریان (m/s)', persistence_3d:'پایداری ۳ روزه',
    persistence_5d:'پایداری ۵ روزه', physics_first_composite:'امتیاز ترکیبی فیزیکی',
    balanced_composite:'امتیاز ترکیبی متوازن'
  };
  const palettes = {
    'blue-yellow': [[13,62,151],[54,132,212],[235,190,47],[255,247,120]],
    ocean: [[12,43,106],[20,144,167],[86,199,164],[242,138,55]],
    viridis: [[68,1,84],[49,104,142],[53,183,121],[253,231,37]],
    gray: [[19,30,44],[95,109,122],[176,189,199],[248,250,252]]
  };
  const uiError = e => { if($('message')) { $('message').hidden=false; $('message').textContent=String(e?.message||e); } };
  const clearError = () => {if($('message')) $('message').hidden=true;};
  if(typeof L==='undefined'){uiError('کتابخانه نقشه Leaflet بارگذاری نشد. فایل‌های leaflet.js و leaflet.css را بررسی کن.');return;}

  const map=L.map('map',{preferCanvas:true,zoomControl:true});
  const basemap=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution:'© OpenStreetMap contributors',maxZoom:13,crossOrigin:'anonymous'
  }).addTo(map);
  const rasterGroup=L.layerGroup().addTo(map), vectors=L.layerGroup().addTo(map);
  const ridges=L.layerGroup().addTo(map), clusters=L.layerGroup().addTo(map), hotspots=L.layerGroup().addTo(map);
  const gridLayer=L.layerGroup().addTo(map);
  L.control.layers(null, {'رستر FTLE و شاخص‌ها':rasterGroup, 'خطوط LCS':ridges,
    'خوشه‌ها':clusters,'نقاط داغ':hotspots,'جهت جریان':vectors,'گرید و مختصات':gridLayer}, {collapsed:true}).addTo(map);
  const stage=$('mapStage'), inspector=$('inspector'), connector=$('inspectConnector'), line=$('inspectLine');
  const picker=$('datePick');
  let manifest=null, sourceBase='', selected=0, field=null, raster=null, playing=null, serial=0;
  let firstFit=true, rawImage=null, marker=null, anchor=null, pinned=false;
  let autoRange=true, manualMin=null, manualMax=null, limits=[0,1];
  let panelPos={x:0,y:0}, panelMoved=false, refreshGridScheduled=false;
  let loadedSource='local';
  const num=v=>Number(v);
  function h(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  async function json(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`${url}: HTTP ${r.status}`);return r.json();}
  function baseUrl(path){return new URL(path,sourceBase||document.baseURI).href;}
  function dayUrl(run,file){return baseUrl(`runs/${encodeURIComponent(run.name)}/${file}`);}

  // Decimal degrees, degrees/decimal minutes and degrees/minutes/seconds.
  function parseCoord(text,axis){
    text=String(text??'').trim().replace(/[۰-۹]/g,c=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c)))
      .replace(/[٠-٩]/g,c=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(c))).replace(/٫/g,'.');
    const hemi=(text.match(/[NSEW]/i)||[])[0]?.toUpperCase();
    if(hemi && ((axis==='lat' && !'NS'.includes(hemi))||(axis==='lon'&&! 'EW'.includes(hemi))))throw Error('حرف جهت با عرض/طول جغرافیایی سازگار نیست.');
    const negative=/^\s*-/.test(text)||hemi==='S'||hemi==='W';
    const parts=text.replace(/[NSEW]/gi,'').match(/\d+(?:\.\d+)?/g);
    if(!parts || !parts.length||parts.length>3)throw Error('مختصات نامعتبر است. مثال: 58° 30′ 15″ E');
    const values=parts.map(Number);
    if(values.length>1 && (values[1]>=60 || values[1]<0))throw Error('دقیقه باید کمتر از ۶۰ باشد.');
    if(values.length>2 && (values[2]>=60 || values[2]<0))throw Error('ثانیه باید کمتر از ۶۰ باشد.');
    let dd=(values[0]+(values[1]||0)/60+(values[2]||0)/3600)*(negative?-1:1);
    if(Math.abs(dd)>(axis==='lat'?90:180))throw Error('مختصات خارج از بازه جغرافیایی است.');
    return dd;
  }
  function coordText(value,mode,axis){
    const hem=axis==='lat'?(value<0?'S':'N'):(value<0?'W':'E');
    let a=Math.abs(value);
    if(mode==='dd')return value.toFixed(6)+'°';
    if(mode==='dmm') {
      let d=Math.floor(a), m=(a-d)*60;
      m=Number(m.toFixed(4));if(m>=60){d++;m=0;}
      return `${d}° ${m.toFixed(4)}′ ${hem}`;
    }
    let d=Math.floor(a),m=Math.floor((a-d)*60),s=Number(((a-d)*60-m)*60).toFixed(2);
    if(Number(s)>=60){s='0.00';m++;}if(m>=60){m=0;d++;}
    return `${d}° ${m}′ ${s}″ ${hem}`;
  }
  const coordsOf=(lat,lon)=>{
    const dd=`${coordText(lat,'dd','lat')} / ${coordText(lon,'dd','lon')}`;
    const dmm=`${coordText(lat,'dmm','lat')} / ${coordText(lon,'dmm','lon')}`;
    const dms=`${coordText(lat,'dms','lat')} / ${coordText(lon,'dms','lon')}`;
    return {dd,dmm,dms};
  };
  function writeConverter(lat,lon){
    const m=$('coordinateMode').value;
    $('coordLat').value=coordText(lat,m,'lat');$('coordLon').value=coordText(lon,m,'lon');
  }
  function readConverter(){return {lat:parseCoord($('coordLat').value,'lat'),lon:parseCoord($('coordLon').value,'lon')};}
  $('coordinateMode').addEventListener('change',()=>{
    try{const c=readConverter();writeConverter(c.lat,c.lon);$('coordHelp').textContent='نمایش مختصات تغییر کرد.';}
    catch(e){if(anchor){writeConverter(anchor.lat,anchor.lng);}else $('coordHelp').textContent=e.message;}
  });
  $('convertCoords').addEventListener('click',()=>{
    try{const c=readConverter();const values=coordsOf(c.lat,c.lon);$('coordHelp').textContent=`DD: ${values.dd} | DMM: ${values.dmm} | DMS: ${values.dms}`;}
    catch(e){$('coordHelp').textContent=e.message;}
  });
  $('goCoords').addEventListener('click',()=>{
    try{const c=readConverter();setAnchor(L.latLng(c.lat,c.lon),true);map.panTo([c.lat,c.lon]);$('coordHelp').textContent='نشانگر منتقل شد؛ مقادیر از نزدیک‌ترین سلول معتبر نمونه‌برداری می‌شوند.';}
    catch(e){$('coordHelp').textContent=e.message;}
  });
  $('copyCoords').addEventListener('click',async()=>{
    try{const c=readConverter();const text=Object.entries(coordsOf(c.lat,c.lon)).map(([k,v])=>`${k.toUpperCase()}: ${v}`).join('\n');
      await navigator.clipboard.writeText(text);$('coordHelp').textContent='مختصات در کلیپ‌بورد کپی شد.';}
    catch(e){$('coordHelp').textContent='کپی خودکار ممکن نیست؛ مختصات را دستی انتخاب کن.';}
  });

  const axisNearest=(axis,v)=>{
    if(!axis?.length || v<axis[0] || v>axis[axis.length-1])return -1;
    const step=(axis[axis.length-1]-axis[0])/Math.max(1,axis.length-1);
    return clamp(Math.round((v-axis[0])/step),0,axis.length-1);
  };
  function value(layer,i,j){const arr=field?.layers?.[layer];return arr?arr[i*field.lat_axis.length+j]:NaN;}
  function sample(lat,lon){
    if(!field)return null;
    const i=axisNearest(field.lon_axis,lon),j=axisNearest(field.lat_axis,lat);
    if(i<0||j<0||value('ocean_mask',i,j)<0.5)return null;
    const u=value('current_u',i,j),v=value('current_v',i,j);
    const direction=!missing(u)&&!missing(v)?(Math.atan2(u,v)*180/Math.PI+360)%360:NaN;
    return {lat:field.lat_axis[j],lon:field.lon_axis[i],ftle:value('ftle_smooth',i,j),
      potential:value('accumulation_potential_physics_first',i,j),speed:value('current_speed',i,j),
      ridge:value('ridge_support',i,j),persistence:value('persistence_5d',i,j),direction};
  }
  function panelContent(){
    if(!anchor)return;
    const data=sample(anchor.lat,anchor.lng), c=coordsOf(anchor.lat,anchor.lng);
    const row=(a,b)=>`<tr><td>${h(a)}</td><td>${h(b)}</td></tr>`;
    let html=`<table>${row('DD',c.dd)}${row('DMM',c.dmm)}${row('DMS',c.dms)}`;
    if(data)html+=`${row('نمونه از سلول',`${data.lat.toFixed(5)}°, ${data.lon.toFixed(5)}°`)}
      ${row('FTLE',`${fmt(data.ftle,5)} h⁻¹`)}${row('امتیاز نسبی تجمع',`${fmt(data.potential,1)} / 100`)}
      ${row('Ridge support',fmt(data.ridge))}${row('پایداری ۵روزه',fmt(data.persistence))}
      ${row('سرعت جریان',`${fmt(data.speed)} m/s`)}${row('جهت حرکت (به)',`${fmt(data.direction,1)}°`)}`;
    else html+=row('وضعیت','خشکی، حاشیه نامعتبر یا بیرون پوشش داده');
    html+='</table><small>نقطه انتخابی و مرکز سلول نمونه‌برداری‌شده ممکن است متفاوت باشند. امتیاز تجمع احتمال صید نیست.</small>';
    $('inspectBody').innerHTML=html;
    writeConverter(anchor.lat,anchor.lng);
    writeInspectorCoords(anchor.lat,anchor.lng);
  }
  function clampPanel(){
    const w=stage.clientWidth,h=stage.clientHeight,pw=inspector.offsetWidth,ph=inspector.offsetHeight;
    panelPos.x=clamp(panelPos.x,5,Math.max(5,w-pw-5));panelPos.y=clamp(panelPos.y,5,Math.max(5,h-ph-5));
    inspector.style.left=panelPos.x+'px';inspector.style.top=panelPos.y+'px';
  }
  function linkPanel(){
    if(!anchor || inspector.hidden){connector.style.display='none';return;}
    const q=map.latLngToContainerPoint(anchor), w=stage.clientWidth, h=stage.clientHeight;
    const panelX=panelPos.x,panelY=panelPos.y,pw=inspector.offsetWidth,ph=inspector.offsetHeight;
    const x2=clamp(q.x,panelX,panelX+pw),y2=clamp(q.y,panelY,panelY+ph);
    connector.style.display='block';
    connector.setAttribute('viewBox',`0 0 ${w} ${h}`);
    line.setAttribute('x1',String(q.x));line.setAttribute('y1',String(q.y));
    line.setAttribute('x2',String(x2));line.setAttribute('y2',String(y2));
  }
  function writeInspectorCoords(lat,lon){
    const mode=$('inspectCoordMode').value;
    $('inspectLat').value=coordText(lat,mode,'lat');
    $('inspectLon').value=coordText(lon,mode,'lon');
  }
  function inspectCoords(){
    return {lat:parseCoord($('inspectLat').value,'lat'),lon:parseCoord($('inspectLon').value,'lon')};
  }
  $('inspectCoordMode').addEventListener('change',()=>{
    try{const c=inspectCoords();writeInspectorCoords(c.lat,c.lon);$('inspectCoordMsg').textContent='';}
    catch(e){if(anchor)writeInspectorCoords(anchor.lat,anchor.lng);$('inspectCoordMsg').textContent=e.message;}
  });
  $('inspectCoordGo').addEventListener('click',()=>{
    try{const c=inspectCoords();setAnchor(L.latLng(c.lat,c.lon),true);map.panTo([c.lat,c.lon]);$('inspectCoordMsg').textContent='مختصات نشانگر به‌روزرسانی شد.';}
    catch(e){$('inspectCoordMsg').textContent=e.message;}
  });
  $('inspectCoordCopy').addEventListener('click',async()=>{
    try{const c=inspectCoords(),lines=Object.entries(coordsOf(c.lat,c.lon)).map(([k,v])=>`${k.toUpperCase()}: ${v}`);
      await navigator.clipboard.writeText(lines.join('\n'));
      $('inspectCoordMsg').textContent='مختصات کپی شد.';
    }catch(e){$('inspectCoordMsg').textContent='کپی خودکار ممکن نیست؛ متن را دستی کپی کن.';}
  });
  const pointIcon=L.divIcon({className:'',html:'<div class="lcs-point-anchor" title="برای جابه‌جایی نقطه بکشید"></div>',iconSize:[18,18],iconAnchor:[9,9]});
  function setAnchor(latlng,force=false){
    if(pinned && !force)return;
    anchor=L.latLng(latlng.lat,latlng.lng);
    if(!marker){
      marker=L.marker(anchor,{draggable:true,icon:pointIcon,autoPan:true}).addTo(map);
      marker.on('drag',()=>{anchor=marker.getLatLng();panelContent();linkPanel();});
      marker.on('dragend',()=>{anchor=marker.getLatLng();panelContent();linkPanel();});
    } else marker.setLatLng(anchor);
    inspector.hidden=false;
    if(!panelMoved){panelPos={x:Math.max(5,stage.clientWidth-inspector.offsetWidth-20),y:58};}
    clampPanel();panelContent();linkPanel();
  }
  function closePanel(){inspector.hidden=true;connector.style.display='none';if(marker){map.removeLayer(marker);marker=null;}anchor=null;pinned=false;pinStatus();}
  function pinStatus(){$('pinPoint').textContent=pinned?'📌 ثابت ✓':'📌 تثبیت';$('pinPoint').setAttribute('aria-pressed',String(pinned));}
  $('closeInspector').addEventListener('click',closePanel);
  $('pinPoint').addEventListener('click',()=>{pinned=!pinned;pinStatus();});
  map.on('click',e=>setAnchor(e.latlng));
  const handle=$('inspectHandle');
  handle.addEventListener('pointerdown',e=>{
    if(e.target.closest('button'))return;
    e.preventDefault();panelMoved=true;
    const start={x:e.clientX,y:e.clientY,px:panelPos.x,py:panelPos.y};
    handle.setPointerCapture(e.pointerId);
    const move=ev=>{panelPos={x:start.px+ev.clientX-start.x,y:start.py+ev.clientY-start.y};clampPanel();linkPanel();};
    const end=()=>{handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',end);handle.removeEventListener('pointercancel',end);};
    handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);
  });
  L.DomEvent.disableClickPropagation(inspector);
  L.DomEvent.disableScrollPropagation(inspector);
  map.on('move zoom resize',linkPanel);
  window.addEventListener('resize',()=>{if(!inspector.hidden){clampPanel();linkPanel();}});

  function paletteRGB(z){
    const a=palettes[$('paletteSelect').value]||palettes['blue-yellow'];
    const x=clamp(z,0,1)*(a.length-1),i=Math.min(a.length-2,Math.floor(x)),f=x-i;
    return a[i].map((v,k)=>Math.round(v*(1-f)+a[i+1][k]*f));
  }
  function shownRGB(value){
    const t=clamp((value-limits[0])/Math.max(1e-12,limits[1]-limits[0]),0,1);
    return paletteRGB(Math.pow(t,Number($('gammaRange').value)));
  }
  function autoLimits(raw,layer){
    if(layer.startsWith('accumulation_potential_'))return [0,100];
    if(layer.startsWith('persistence_')||layer.endsWith('_composite')||layer==='ridge_support')return [0,1];
    const ok=[];const wet=field?.layers?.ocean_mask;for(let i=0;i<raw.length;i++){if((!wet||wet[i]>.5)&&!missing(raw[i]))ok.push(raw[i]);}
    if(!ok.length)return [0,1];
    ok.sort((a,b)=>a-b);
    const lo=ok[Math.floor((ok.length-1)*0.03)],hi=ok[Math.ceil((ok.length-1)*0.97)];
    return hi>lo?[lo,hi]:[lo,lo+1e-9];
  }
  function rasterize(layer){
    const nx=field.lon_axis.length,ny=field.lat_axis.length;
    const canvas=document.createElement('canvas');canvas.width=nx;canvas.height=ny;
    const ctx=canvas.getContext('2d'),img=ctx.createImageData(nx,ny);
    const raw=field.layers[layer]||field.layers.ftle_smooth;
    limits=autoRange?autoLimits(raw,layer):[manualMin,manualMax];
    for(let j=0;j<ny;j++)for(let i=0;i<nx;i++){
      const v=raw[i*ny+j],wet=value('ocean_mask',i,j)>0.5;
      const k=4*((ny-j-1)*nx+i);
      if(missing(v)||!wet){img.data[k+3]=0;continue;}
      const c=shownRGB(v);img.data[k]=c[0];img.data[k+1]=c[1];img.data[k+2]=c[2];img.data[k+3]=220;
    }
    ctx.putImageData(img,0,0);
    return canvas.toDataURL('image/png');
  }
  function updateLegend(){
    const shades=[];for(let n=0;n<=20;n++){
      const z=n/20,p=paletteRGB(Math.pow(z,Number($('gammaRange').value)));
      shades.push(`rgb(${p.join(',')}) ${Math.round(z*100)}%`);
    }
    $('legendRamp').style.background=`linear-gradient(to top,${shades.join(',')})`;
    $('legendMin').textContent=fmt(limits[0],Math.abs(limits[1]-limits[0])<1?4:2);
    $('legendMax').textContent=fmt(limits[1],Math.abs(limits[1]-limits[0])<1?4:2);
    $('legendName').textContent=label[$('layerSelect').value]||$('layerSelect').value;
    $('legendTitle').textContent=label[$('layerSelect').value]||$('layerSelect').value;
    if(autoRange){$('minValue').value=String(Number(limits[0].toPrecision(6)));$('maxValue').value=String(Number(limits[1].toPrecision(6)));}
    $('gammaValue').textContent=Number($('gammaRange').value).toFixed(2);
  }
  function redrawRaster(){
    if(!field)return;
    rasterGroup.clearLayers();
    const lat=field.lat_axis,lon=field.lon_axis;
    const dy=lat.length>1?(lat.at(-1)-lat[0])/(lat.length-1):0;
    const dx=lon.length>1?(lon.at(-1)-lon[0])/(lon.length-1):0;
    const bounds=[[lat[0]-dy/2,lon[0]-dx/2],[lat.at(-1)+dy/2,lon.at(-1)+dx/2]];
    rawImage=rasterize($('layerSelect').value);
    raster=L.imageOverlay(rawImage,bounds,{opacity:.88,interactive:false}).addTo(rasterGroup);
    if(firstFit){
      const b=field.metadata?.bbox;
      if(b&&[b.lon_min,b.lon_max,b.lat_min,b.lat_max].every(Number.isFinite))map.fitBounds([[b.lat_min,b.lon_min],[b.lat_max,b.lon_max]]);
      else map.fitBounds(bounds);
      firstFit=false;
    }
    updateLegend();
  }
  function vectorDraw(){
    vectors.clearLayers();const nx=field.lon_axis.length,ny=field.lat_axis.length;
    const step=Math.max(4,Math.ceil(Math.max(nx,ny)/19));
    for(let i=0;i<nx;i+=step)for(let j=0;j<ny;j+=step){
      if(value('ocean_mask',i,j)<0.5)continue;
      const u=value('current_u',i,j),v=value('current_v',i,j);
      if(missing(u)||missing(v))continue;
      const t=Math.atan2(v,u),lat=field.lat_axis[j],lon=field.lon_axis[i];
      const d=Math.min(.22,(field.lon_axis.at(-1)-field.lon_axis[0])/(nx/step*3));
      L.polyline([[lat,lon],[lat+d*Math.sin(t),lon+d*Math.cos(t)]],{color:'#fff',weight:1.4,opacity:.75,interactive:false}).addTo(vectors);
    }
  }
  function drawVectorsAndLines(){
    ridges.clearLayers();clusters.clearLayers();hotspots.clearLayers();vectorDraw();
    for(const coords of field.ridges||[]){if(coords.length<2)continue;
      L.polyline(coords.map(p=>[p[1],p[0]]),{color:'#fff0a4',weight:2.2,opacity:.95,bubblingMouseEvents:false})
        .on('click',e=>setAnchor(e.latlng,true)).addTo(ridges);
    }
    for(const cl of field.clusters||[]){if((cl.polygon_lonlat||[]).length<3)continue;
      L.polygon(cl.polygon_lonlat.map(p=>[p[1],p[0]]),{color:'#e5c072',weight:1.3,fillOpacity:.12,bubblingMouseEvents:false})
        .on('click',e=>setAnchor(e.latlng,true)).addTo(clusters);
    }
    for(const hs of field.hotspots||[]){
      L.circleMarker([hs.lat,hs.lon],{radius:6,color:'#ffdf69',fillColor:'#f97355',fillOpacity:.95,weight:2,bubblingMouseEvents:false})
        .on('click',()=>setAnchor(L.latLng(hs.lat,hs.lon),true)).addTo(hotspots);
    }
  }

  function redrawGrid(){
    refreshGridScheduled=false;
    gridLayer.clearLayers();
    const b=map.getBounds();if(!b.isValid())return;
    const west=Math.max(-180,b.getWest()),east=Math.min(180,b.getEast());
    const south=Math.max(-89.9,b.getSouth()),north=Math.min(89.9,b.getNorth());
    let step=.2;
    while((east-west)/step>55||(north-south)/step>55)step*=2;
    const startLon=Math.ceil(west/step-1e-9),endLon=Math.floor(east/step+1e-9);
    const startLat=Math.ceil(south/step-1e-9),endLat=Math.floor(north/step+1e-9);
    const css={color:'#355b88',opacity:.28,weight:.8,interactive:false};
    const icon=(v,typ)=>L.divIcon({className:'lcs-grid-icon',html:`<span class="lcs-grid-label ${typ}">${v.toFixed(step<1?1:0)}°</span>`,iconSize:[44,18],iconAnchor:[0,0]});
    for(let n=startLon;n<=endLon;n++){
      const x=Number((n*step).toFixed(6));
      L.polyline([[south,x],[north,x]],css).addTo(gridLayer);
      L.marker([north,x],{icon:icon(x,'horizontal'),interactive:false}).addTo(gridLayer);
    }
    for(let n=startLat;n<=endLat;n++){
      const y=Number((n*step).toFixed(6));
      L.polyline([[y,west],[y,east]],css).addTo(gridLayer);
      L.marker([y,west],{icon:icon(y,'vertical'),interactive:false}).addTo(gridLayer);
    }
  }
  function scheduleGrid(){if(refreshGridScheduled)return;refreshGridScheduled=true;requestAnimationFrame(redrawGrid);}
  map.on('moveend zoomend resize',scheduleGrid);

  function updateQuality(run){
    const qc=run.summary?.metadata?.numerical_quality;
    $('qualityStatus').textContent=qc
      ?`کیفیت عددی: ${qc.quality_flag||'نامشخص'} | پوشش FTLE: ${fmt(num(qc.valid_ftle_fraction_in_aoi)*100,1)}٪ | هشدار همگرایی: ${qc.refinement_warning?'دارد':'ندارد'}`
      :'گزارش کیفیت این روز موجود نیست';
  }
  async function setRun(n){
    if(!manifest?.runs?.length)return;
    selected=clamp(n,0,manifest.runs.length-1);
    const run=manifest.runs[selected],md=run.summary?.metadata||{};
    $('dayRange').value=String(selected);
    $('dayLabel').textContent=md.requested_target_date_local||run.name;
    $('dayType').textContent=md.data_kind==='forecast'?'پیش‌بینی':'گذشته/تحلیل';
    $('utcLabel').textContent=md.actual_selected_utc||'زمان نامشخص';
    $('runCount').textContent=`${selected+1}/${manifest.runs.length}`;
    const localDate=md.requested_target_date_local;
    picker.value=/^\d{4}-\d{2}-\d{2}$/.test(localDate||'')?localDate:'';
    updateQuality(run);
    const token=++serial;
    try{
      const next=await json(dayUrl(run,'web_day.json'));
      const res=await fetch(dayUrl(run,next.file),{cache:'no-store'});
      if(!res.ok)throw new Error(`دریافت داده رستر: HTTP ${res.status}`);
      const buf=await res.arrayBuffer();
      if(token!==serial)return;
      if(next.format!=='seyd-yaar-flat-f32-v1')throw Error('فرمت داده پروژه دوم با LCS سازگار نیست.');
      const count=next.shape[0]*next.shape[1];
      if(buf.byteLength!==count*next.layers.length*4)throw Error('ابعاد رستر با متادیتا مطابقت ندارد.');
      const all=new Float32Array(buf);
      next.layers=Object.fromEntries(next.layers.map((name,k)=>[name,all.subarray(k*count,(k+1)*count)]));
      field=next;clearError();redrawRaster();drawVectorsAndLines();panelContent();linkPanel();
      const q=next.metadata?.numerical_quality;
      if(q&&(q.valid_ftle_fraction_in_aoi<.9||q.refinement_warning))uiError(`هشدار کیفیت عددی: پوشش FTLE ${fmt(q.valid_ftle_fraction_in_aoi*100,1)}٪؛ آزمون گام ${q.refinement_warning?'نیازمند بررسی است.':'هشداری ندارد.'}`);
      $('downloadRun').href=dayUrl(run,'web_day.json');
      $('downloadGeo').href=dayUrl(run,'ridges.geojson');
      $('downloadNC').href=dayUrl(run,'summary.json');
    }catch(e){if(token===serial)uiError(e);}
  }
  function setPlay(v){
    if(playing){clearInterval(playing);playing=null;}
    $('play').textContent=v?'⏸ توقف':'▶ پخش';
    if(v&&manifest?.runs.length>1){
      playing=setInterval(()=>setRun((selected+1)%manifest.runs.length),1100/num($('playSpeed').value));
    }
  }
  $('layerSelect').addEventListener('change',()=>{autoRange=true;redrawRaster();});
  $('paletteSelect').addEventListener('change',redrawRaster);
  $('gammaRange').addEventListener('input',redrawRaster);
  $('applyRange').addEventListener('click',()=>{
    const lo=num($('minValue').value),hi=num($('maxValue').value);
    if(!$('minValue').value||!$('maxValue').value||!Number.isFinite(lo)||!Number.isFinite(hi)||hi<=lo){$('rangeError').textContent='حداکثر باید بزرگ‌تر از حداقل باشد.';return;}
    $('rangeError').textContent='';autoRange=false;manualMin=lo;manualMax=hi;redrawRaster();
  });
  $('autoRange').addEventListener('click',()=>{autoRange=true;$('rangeError').textContent='';redrawRaster();});
  $('dayRange').addEventListener('input',e=>{setPlay(false);setRun(num(e.target.value));});
  $('prev').addEventListener('click',()=>{setPlay(false);setRun(selected-1);});
  $('next').addEventListener('click',()=>{setPlay(false);setRun(selected+1);});
  $('play').addEventListener('click',()=>setPlay(!playing));
  $('playSpeed').addEventListener('change',()=>{if(playing)setPlay(true);});
  picker.addEventListener('change',()=>{
    if(!picker.value||!manifest?.runs.length)return;
    const query=Date.parse(picker.value+'T12:00:00Z');
    const dates=manifest.runs.map(r=>Date.parse((r.summary?.metadata?.requested_target_date_local||'')+'T12:00:00Z'));
    let index=0,best=Infinity;
    dates.forEach((d,i)=>{const dist=Math.abs(d-query);if(Number.isFinite(dist)&&dist<best){best=dist;index=i;}});
    setPlay(false);setRun(index);
  });
  window.addEventListener('keydown',e=>{
    if(['INPUT','SELECT','TEXTAREA'].includes(e.target?.tagName))return;
    if(e.key==='ArrowLeft'){setPlay(false);setRun(selected-1);}
    if(e.key==='ArrowRight'){setPlay(false);setRun(selected+1);}
  });

  // Export visible map: try map tiles with CORS, then guaranteed data-only fallback.
  async function drawExport(withTiles){
    const el=$('map'),rect=el.getBoundingClientRect(),w=Math.round(rect.width),h=Math.round(rect.height);
    const c=document.createElement('canvas');c.width=w;c.height=h;const ctx=c.getContext('2d');
    ctx.fillStyle='#d9e9f0';ctx.fillRect(0,0,w,h);
    const imgNodes=[...el.querySelectorAll('.leaflet-tile-loaded')];
    if(withTiles){
      for(const img of imgNodes){
        if(!img.complete||!img.naturalWidth)continue;
        const r=img.getBoundingClientRect();ctx.drawImage(img,r.left-rect.left,r.top-rect.top,r.width,r.height);
      }
    }
    if(rawImage && rasterGroup.hasLayer(raster)){
      const img=new Image();img.src=rawImage;
      await new Promise((resolve,reject)=>{if(img.complete)resolve();else{img.onload=resolve;img.onerror=reject;}});
      const b=raster.getBounds(),ul=map.latLngToContainerPoint(b.getNorthWest()),br=map.latLngToContainerPoint(b.getSouthEast());
      ctx.globalAlpha=.88;ctx.drawImage(img,ul.x,ul.y,br.x-ul.x,br.y-ul.y);ctx.globalAlpha=1;
    }
    const path=(geo)=>{ctx.beginPath();geo.forEach((p,i)=>{const q=map.latLngToContainerPoint([p[1],p[0]]);if(i===0)ctx.moveTo(q.x,q.y);else ctx.lineTo(q.x,q.y);});};
    if(map.hasLayer(ridges))for(const coords of field?.ridges||[]){if(coords.length<2)continue;path(coords);ctx.strokeStyle='#fff0a4';ctx.lineWidth=2.2;ctx.stroke();}
    if(map.hasLayer(hotspots))for(const point of field?.hotspots||[]){const q=map.latLngToContainerPoint([point.lat,point.lon]);ctx.beginPath();ctx.arc(q.x,q.y,5,0,Math.PI*2);ctx.fillStyle='#f97355';ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='#ffdf69';ctx.stroke();}
    if(map.hasLayer(clusters))for(const cl of field?.clusters||[]){const pts=cl.polygon_lonlat||[];if(pts.length<3)continue;path(pts);ctx.closePath();ctx.strokeStyle='#e5c072';ctx.lineWidth=1.5;ctx.stroke();}
    if(marker&&anchor){const q=map.latLngToContainerPoint(anchor);ctx.beginPath();ctx.arc(q.x,q.y,7,0,2*Math.PI);ctx.strokeStyle='#fcaa32';ctx.lineWidth=3;ctx.stroke();}
    if(map.hasLayer(gridLayer)){
      const b=map.getBounds();let step=.2;while((b.getEast()-b.getWest())/step>55||(b.getNorth()-b.getSouth())/step>55)step*=2;
      ctx.strokeStyle='rgba(25,65,102,0.22)';ctx.fillStyle='#1b3e5b';ctx.font='10px sans-serif';
      for(let x=Math.ceil(b.getWest()/step);x<=Math.floor(b.getEast()/step);x++){
        const n=x*step;const p=map.latLngToContainerPoint([b.getNorth(),n]);ctx.beginPath();ctx.moveTo(p.x,0);ctx.lineTo(p.x,h);ctx.stroke();ctx.fillText(n.toFixed(step<1?1:0)+'°',p.x+2,14);
      }
      for(let y=Math.ceil(b.getSouth()/step);y<=Math.floor(b.getNorth()/step);y++){
        const n=y*step,p=map.latLngToContainerPoint([n,b.getWest()]);ctx.beginPath();ctx.moveTo(0,p.y);ctx.lineTo(w,p.y);ctx.stroke();ctx.fillText(n.toFixed(step<1?1:0)+'°',4,p.y-2);
      }
    }
    ctx.fillStyle='#081829cc';ctx.fillRect(0,h-35,w,35);
    ctx.fillStyle='white';ctx.font='13px sans-serif';
    const run=manifest?.runs[selected];
    ctx.fillText(`LCS / ${run?.summary?.metadata?.actual_selected_utc||''} / ${$('layerSelect').value}`,9,h-13);
    ctx.fillText('© OpenStreetMap contributors',Math.max(8,w-185),h-13);
    return c;
  }
  $('saveMap').addEventListener('click',async()=>{
    try{
      let c=await drawExport(true);
      try{c.toDataURL('image/png');}catch{c=await drawExport(false);}
      const href=c.toDataURL('image/png');const a=document.createElement('a');
      a.href=href;a.download=`LCS_${manifest?.runs[selected]?.name||'map'}_${$('layerSelect').value}.png`;
      document.body.appendChild(a);a.click();a.remove();
    }catch(e){uiError('ذخیره تصویر ناموفق بود: '+String(e.message||e));}
  });

  async function loadManifest(base){
    ++serial;setPlay(false);field=null;firstFit=true;closePanel();
    sourceBase=new URL(base,document.baseURI).href;
    manifest=await json(baseUrl('manifest.json'));
    if(!Array.isArray(manifest.runs)||!manifest.runs.length)throw Error('فایل manifest پروژه هیچ روز خروجی معتبر ندارد.');
    manifest.runs.sort((a,b)=>String(a.summary?.metadata?.actual_selected_utc||'').localeCompare(String(b.summary?.metadata?.actual_selected_utc||'')));
    $('dayRange').max=String(manifest.runs.length-1);
    const video=$('sequenceVideo');
    if(manifest.sequence_video){video.src=baseUrl(manifest.sequence_video);video.hidden=false;$('noVideo').hidden=true;}
    else{video.pause();video.removeAttribute('src');video.hidden=true;$('noVideo').hidden=false;}
    const nearest=manifest.runs.map(r=>Date.parse(r.summary?.metadata?.actual_selected_utc||'')).reduce((a,t,i,arr)=>{
      const dist=Number.isFinite(t)?Math.abs(t-Date.now()):Infinity;
      return dist<a.d?{d:dist,i}:a;
    },{d:Infinity,i:0}).i;
    await setRun(nearest);
    const report=manifest.report;
    $('runReport').textContent=report?.outcomes?.length
      ?`${report.outcomes.filter(o=>o.status==='success').length} روز موفق / ${report.outcomes.filter(o=>o.status!=='success').length} ردشده`
      :`${manifest.runs.length} خروجی`;
    loadedSource=$('projectSelect').value;
  }
  $('projectSelect').addEventListener('change',async()=>{
    const second=$('projectSelect').value==='second';$('secondSourceRow').hidden=!second;
    if(second){$('secondSource').value=localStorage.getItem('lcs_second_project_url')||'';
      if(!$('secondSource').value)return;
      try{await loadManifest($('secondSource').value);}catch(e){uiError(e);}}
    else {try{await loadManifest('./');}catch(e){uiError(e);}}
  });
  $('loadSecond').addEventListener('click',async()=>{
    const input=$('secondSource').value.trim();
    try{const u=new URL(input,document.baseURI);if(!['https:','http:'].includes(u.protocol))throw Error('آدرس باید HTTP/HTTPS باشد.');
      const base=u.href.endsWith('/')?u.href:u.href+'/';
      await loadManifest(base);localStorage.setItem('lcs_second_project_url',base);clearError();
    }catch(e){uiError('بارگذاری پروژه دوم ممکن نشد؛ آدرس و CORS را بررسی کن. '+String(e.message||e));}
  });
  async function init(){
    try{await loadManifest('./');scheduleGrid();}
    catch(e){uiError(e);map.setView([15,58],5);scheduleGrid();}
  }
  init();
})();
