#!/usr/bin/env python3
"""LAN viewer: open http://10.2.1.5:8097 ON THE DISPLAY DEVICE itself.

The landing page detects the device's native resolution (screen px x
devicePixelRatio), the viewer lazily generates that exact cut server-side
(cached under cuts/web/), and shows the 7 frames pixel-exact; tap to cycle.
On iPhone/iPad, Add to Home Screen and launch from the icon for true
fullscreen (Safari's bars break the 1:1 check otherwise).
"""
import os
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.chdir(ROOT)
import cut  # noqa: E402

CACHE = os.path.join(ROOT, "cuts", "web")
PORT = 8097
LOCK = threading.Lock()

INDEX = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Lensica</title>
<style>body{background:#111;color:#eee;font:16px -apple-system,system-ui,sans-serif;
padding:24px;max-width:32em;margin:auto}
a.b{display:inline-block;background:#2a6;color:#000;padding:12px 22px;
border-radius:8px;text-decoration:none;font-weight:600}
code{color:#8cf}li{margin:6px 0;color:#aaa}</style></head><body>
<h2>Lensica target viewer</h2>
<p id="det">detecting display&hellip;</p>
<p><a class="b" id="go">Show frames</a></p>
<ol>
<li>iPhone/iPad: Share &rarr; Add to Home Screen, launch from the icon (fullscreen).</li>
<li>Max brightness, auto-brightness OFF, True Tone / Night Shift OFF, rotation locked.</li>
<li>Lights out. Tap anywhere to cycle the 8 frames.</li>
<li>All 4 corner markers must be fully visible and the page must not scroll or zoom;
otherwise the view is not 1:1 and the capture is invalid.</li>
</ol>
<script>
var w=Math.round(screen.width*devicePixelRatio),h=Math.round(screen.height*devicePixelRatio);
document.getElementById('det').innerHTML='detected <code>'+w+'&times;'+h+'</code> physical px @ '+devicePixelRatio+'x';
document.getElementById('go').href='/view?w='+w+'&h='+h+'&dpr='+devicePixelRatio;
</script></body></html>"""

VIEW = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Lensica frames</title>
<style>html,body{margin:0;padding:0;background:#000}
#f{display:block;image-rendering:pixelated}
#tag{position:fixed;top:8px;left:0;right:0;text-align:center;color:#999;
font:14px -apple-system,system-ui,sans-serif;transition:opacity .4s;pointer-events:none}
</style></head><body><img id="f" alt=""><div id="tag"></div>
<script>
var q={};location.search.slice(1).split('&').forEach(function(kv){var p=kv.split('=');q[p[0]]=decodeURIComponent(p[1]||'');});
var w=+q.w,h=+q.h,dpr=+q.dpr||window.devicePixelRatio||1;
var label=w+'x'+h;
var order=['tone','flat','split','organic','spectrum','skin','edges','points'];
var img=document.getElementById('f'),tag=document.getElementById('tag');
img.style.width=(w/dpr)+'px';img.style.height=(h/dpr)+'px';
tag.textContent='generating '+label+' \\u2026 (first visit takes a few seconds)';
fetch('/cut/'+label+'/manifest.json').then(function(r){
  if(!r.ok)throw new Error(r.status);return r.json();
}).then(function(man){
  var files={};Object.keys(man.files).forEach(function(f){
    order.forEach(function(o){if(f.indexOf(o+'-')===0)files[o]=f;});});
  var i=0,t;
  function show(){img.src='/cut/'+label+'/'+files[order[i]];
    tag.style.opacity=1;tag.textContent=(i+1)+'/'+order.length+' '+order[i];
    clearTimeout(t);t=setTimeout(function(){tag.style.opacity=0;},1500);}
  document.body.addEventListener('click',function(){i=(i+1)%order.length;show();});
  show();
}).catch(function(e){tag.textContent='error: '+e;});
</script></body></html>"""


def ensure(label):
    m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", label)
    if not m:
        raise ValueError(label)
    w, h = int(m[1]), int(m[2])
    if not (300 <= w <= 6144 and 300 <= h <= 6144):
        raise ValueError(label)
    outdir = os.path.join(CACHE, label)
    with LOCK:
        if not os.path.exists(os.path.join(outdir, "manifest.json")):
            cut.build(w, h, CACHE, label)
    return outdir


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path).path
            if p == "/":
                return self.html(INDEX)
            if p == "/view":
                return self.html(VIEW)
            if p.startswith("/cut/"):
                parts = p.split("/")
                if len(parts) != 4 or ".." in p:
                    raise ValueError(p)
                outdir = ensure(parts[2])
                with open(os.path.join(outdir, os.path.basename(parts[3])), "rb") as f:
                    data = f.read()
                is_json = parts[3].endswith(".json")
                self.send_response(200)
                self.send_header("Content-Type", "application/json" if is_json else "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store" if is_json else "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)
        except (ValueError, FileNotFoundError):
            self.send_error(404)
        except BrokenPipeError:
            pass

    def html(self, s):
        b = s.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"serving on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
