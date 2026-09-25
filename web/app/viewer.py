"""Target viewer — ported from tools/serve.py into the web app.

Runs ON THE DISPLAY DEVICE: /viewer detects native res, /viewer/view tap-cycles
the frames pixel-exact, /viewer/save gives per-frame Save buttons, all.zip bundles
the set. Pages are kept ES5-dumb so old Safari (iPhone 5s) works: no fetch(),
no arrow functions, no const/let.

The frame list is structured so dropping the copyrighted organic frame for any
public-facing set is ONE flag (PUBLIC). LAN-only today, so organic is included.
"""
import io
import json
import os
import re
import sys
import threading
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "target", "generators"))
os.chdir(ROOT)
import cut  # noqa: E402

CACHE = os.path.join(ROOT, "web", "cuts", "web")
LOCK = threading.Lock()

FRAME_ORDER = ["tone", "flat", "split", "organic", "spectrum", "skin", "edges", "points"]
PUBLIC = False  # LAN-only: keep organic. Flip to True for any public set (drops organic).


def order():
    return [f for f in FRAME_ORDER if not (PUBLIC and f == "organic")]


def ensure(label):
    """Generate (and cache) the full cut for a WxH label; returns its dir."""
    m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", label)
    if not m:
        raise ValueError(label)
    w, h = int(m[1]), int(m[2])
    if not (300 <= w <= 6144 and 300 <= h <= 6144):
        raise ValueError(label)
    outdir = os.path.join(CACHE, label)
    with LOCK:
        if not os.path.exists(os.path.join(outdir, "manifest.json")):
            os.makedirs(CACHE, exist_ok=True)
            cut.build(w, h, CACHE, label)
    return outdir


def zip_bytes(outdir, label):
    with open(os.path.join(outdir, "manifest.json")) as f:
        files = json.load(f)["files"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i, o in enumerate(order()):
            for fname in files:
                if fname.startswith(o + "-"):
                    z.write(os.path.join(outdir, fname), f"{i + 1:02d}-{fname}")
        z.write(os.path.join(outdir, "manifest.json"), "manifest.json")
    return buf.getvalue()


_ORDER_JS = "[" + ",".join("'%s'" % o for o in order()) + "]"

INDEX = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Lensica target viewer</title>
<style>body{background:#0b0a12;color:#e9e6f2;font:16px -apple-system,system-ui,sans-serif;
padding:22px;max-width:32em;margin:auto}
h2{color:#fff}code{color:#b39ddb}li{margin:7px 0;color:#b7b2c7}
a.b{display:inline-block;background:#b39ddb;color:#0a0a10;padding:12px 20px;margin:5px 4px 5px 0;
border-radius:10px;text-decoration:none;font-weight:700}
a.b.alt{background:#3d3853;color:#e9e6f2}</style></head><body>
<h2>Lensica target viewer</h2>
<p id="det">detecting display&hellip;</p>
<p><a class="b" id="go">Show frames</a>
<a class="b alt" id="sv">Save to Photos</a>
<a class="b alt" id="zip">Download zip</a></p>
<ol>
<li><b>Easiest on iPhone:</b> "Save to Photos", long-press each image &rarr; Save Image,
then show them from the Photos app fullscreen (swipe = next frame). Photos shows each
image 1:1, no Safari bars.</li>
<li>"Show frames" = live viewer; on iPhone/iPad use Share &rarr; Add to Home Screen and
launch from the icon, or Safari bars break the 1:1 check.</li>
<li>Zip = every PNG + manifest, for Mac / AirDrop.</li>
<li>Max brightness, auto-brightness OFF, True Tone / Night Shift OFF, rotation locked, lights out.</li>
<li>All 4 corner markers fully visible, no scroll, no zoom, or it is not 1:1.</li>
</ol>
<script>
var w=Math.round(screen.width*devicePixelRatio),h=Math.round(screen.height*devicePixelRatio);
document.getElementById('det').innerHTML='detected <code>'+w+'&times;'+h+'</code> physical px @ '+devicePixelRatio+'x';
document.getElementById('go').href='/viewer/view?w='+w+'&h='+h+'&dpr='+devicePixelRatio;
document.getElementById('zip').href='/viewer/cut/'+w+'x'+h+'/all.zip';
document.getElementById('sv').href='/viewer/save?w='+w+'&h='+h;
</script></body></html>"""

SAVE = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lensica - save to Photos</title>
<style>body{background:#0b0a12;color:#e9e6f2;font:16px -apple-system,system-ui,sans-serif;
padding:16px;margin:auto;max-width:40em}h3{color:#fff}
img{width:100%;display:block;background:#000;border:1px solid #2a2740;border-radius:6px}
p.n{color:#9b96ac;margin:4px 0 18px}
a.s{background:#b39ddb;color:#0a0a10;padding:6px 16px;border-radius:8px;font-weight:700;
text-decoration:none;margin-left:10px}</style></head><body>
<h3>Tap "Save" on each frame (or long-press the image &rarr; Save Image)</h3>
<p style="color:#9b96ac">"Save" opens the share sheet &rarr; Save Image puts it in Photos.
Then open Photos, lights out, fullscreen; swipe to change frames. Saved images are
exact native resolution; Photos shows them 1:1.</p>
<div id="list">generating&hellip;</div>
<script>
var q={};location.search.slice(1).split('&').forEach(function(kv){var p=kv.split('=');q[p[0]]=p[1];});
var label=(+q.w)+'x'+(+q.h);
var order=""" + _ORDER_JS + """;
fetch('/viewer/cut/'+label+'/manifest.json').then(function(r){return r.json();}).then(function(man){
  var files={};Object.keys(man.files).forEach(function(f){
    order.forEach(function(o){if(f.indexOf(o+'-')===0)files[o]=f;});});
  var d=document.getElementById('list');d.innerHTML='';
  order.forEach(function(o,i){
    var im=document.createElement('img');im.src='/viewer/cut/'+label+'/'+files[o];
    var p=document.createElement('p');p.className='n';p.textContent=(i+1)+'. '+files[o];
    var b=document.createElement('a');b.className='s';b.textContent='Save';
    b.onclick=function(){
      fetch(im.src).then(function(r){return r.blob();}).then(function(blob){
        var f;
        try{f=new File([blob],files[o],{type:'image/png'});}catch(e){}
        if(f&&navigator.canShare&&navigator.canShare({files:[f]}))
          return navigator.share({files:[f]});
        var a=document.createElement('a');a.href=URL.createObjectURL(blob);
        a.download=files[o];document.body.appendChild(a);a.click();a.remove();
      });return false;};
    p.appendChild(b);
    d.appendChild(im);d.appendChild(p);});
}).catch(function(e){document.getElementById('list').textContent='error: '+e;});
</script></body></html>"""

VIEW = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Lensica frames</title>
<style>html,body{margin:0;padding:0;background:#000}
#f{display:block;image-rendering:pixelated}
#tag{position:fixed;top:8px;left:0;right:0;text-align:center;color:#b39ddb;
font:14px -apple-system,system-ui,sans-serif;transition:opacity .4s;pointer-events:none}
</style></head><body><img id="f" alt=""><div id="tag"></div>
<script>
var q={};location.search.slice(1).split('&').forEach(function(kv){var p=kv.split('=');q[p[0]]=decodeURIComponent(p[1]||'');});
var w=+q.w,h=+q.h,dpr=+q.dpr||window.devicePixelRatio||1;
var label=w+'x'+h;
var order=""" + _ORDER_JS + """;
var img=document.getElementById('f'),tag=document.getElementById('tag');
img.style.width=(w/dpr)+'px';img.style.height=(h/dpr)+'px';
tag.textContent='generating '+label+' \\u2026 (first visit takes a few seconds)';
fetch('/viewer/cut/'+label+'/manifest.json').then(function(r){
  if(!r.ok)throw new Error(r.status);return r.json();
}).then(function(man){
  var files={};Object.keys(man.files).forEach(function(f){
    order.forEach(function(o){if(f.indexOf(o+'-')===0)files[o]=f;});});
  var i=0,t;
  function show(){img.src='/viewer/cut/'+label+'/'+files[order[i]];
    tag.style.opacity=1;tag.textContent=(i+1)+'/'+order.length+' '+order[i];
    clearTimeout(t);t=setTimeout(function(){tag.style.opacity=0;},1500);}
  document.body.addEventListener('click',function(){i=(i+1)%order.length;show();});
  show();
}).catch(function(e){tag.textContent='error: '+e;});
</script></body></html>"""
