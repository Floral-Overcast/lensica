#!/usr/bin/env python3
"""Lensica web MVP — one app, LAN-only (Milestone 1).

Serves the landing, test wizard (+QR), target viewer (ES5), session upload +
ingestion, profile pages, library, and try-a-look. Binds 0.0.0.0:8080.

    python3 web/server.py            # or: uvicorn web.server:app --host 0.0.0.0 --port 8080
"""
import asyncio
import io
import json
import os
import sys

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import (HTMLResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from web.app import ingestion, looks, profiles, viewer  # noqa: E402

app = FastAPI(title="Lensica")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

NAV = [("/", "Home"), ("/wizard", "Test"), ("/viewer", "Viewer"),
       ("/upload", "Upload"), ("/library", "Library"), ("/try", "Try a look")]


def page(request, name, **ctx):
    ctx.update({"nav": NAV, "path": request.url.path})
    return templates.TemplateResponse(request, name, ctx)


# ---------------- pages ----------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return page(request, "landing.html")


@app.get("/wizard", response_class=HTMLResponse)
def wizard(request: Request):
    displays = sorted(viewer.cut.DISPLAYS.items())
    return page(request, "wizard.html", displays=displays)


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return page(request, "upload.html", sizes=ingestion.SIZES, default_size=ingestion.DEFAULT_SIZE)


@app.get("/library", response_class=HTMLResponse)
def library(request: Request):
    return page(request, "library.html", profiles=profiles.list_profiles(),
                dirs=profiles.existing_dirs())


@app.get("/profile/{pid}", response_class=HTMLResponse)
def profile(request: Request, pid: str):
    prof = profiles.get_profile(pid)
    if not prof:
        return HTMLResponse("<h1>404</h1>profile not found", status_code=404)
    sections = profiles.render_sections(prof)
    return page(request, "profile.html", prof=prof, sections=sections,
                tip_js=profiles.TIP_JS)


@app.get("/try", response_class=HTMLResponse)
def try_page(request: Request):
    return page(request, "try.html", looks=looks.list_looks())


# ---------------- QR ----------------
@app.get("/api/qr")
def qr(data: str):
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=11, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# ---------------- target viewer (ES5) ----------------
@app.get("/viewer", response_class=HTMLResponse)
def viewer_index():
    return HTMLResponse(viewer.INDEX)


@app.get("/viewer/view", response_class=HTMLResponse)
def viewer_view():
    return HTMLResponse(viewer.VIEW)


@app.get("/viewer/save", response_class=HTMLResponse)
def viewer_save():
    return HTMLResponse(viewer.SAVE)


@app.get("/viewer/cut/{label}/{fname}")
def viewer_cut(label: str, fname: str):
    try:
        outdir = viewer.ensure(label)
    except ValueError:
        return Response("bad resolution", status_code=404)
    if fname == "all.zip":
        data = viewer.zip_bytes(outdir, label)
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="lensica-{label}.zip"'})
    path = os.path.join(outdir, os.path.basename(fname))
    if not os.path.exists(path):
        return Response("not found", status_code=404)
    is_json = fname.endswith(".json")
    with open(path, "rb") as f:
        data = f.read()
    return Response(data, media_type="application/json" if is_json else "image/png",
                    headers={"Cache-Control": "no-store" if is_json else "max-age=86400"})


# ---------------- upload + ingestion ----------------
@app.post("/api/upload")
async def api_upload(files: list[UploadFile]):
    sid, folder = ingestion.new_session()
    accepted, rejected = [], []
    for f in files:
        data = await f.read()
        name = ingestion.safe_name(f.filename)
        ok, reason = ingestion.validate(name, data)
        if not ok:
            rejected.append({"name": name, "reason": reason})
            continue
        with open(os.path.join(folder, name), "wb") as out:
            out.write(data)
        accepted.append({"name": name, "reason": reason})
    return {"session": sid, "accepted": accepted, "rejected": rejected}


@app.get("/api/ingest/{sid}")
async def api_ingest(sid: str, size: str = ingestion.DEFAULT_SIZE):
    folder = ingestion.session_folder(sid)
    if not folder:
        return JSONResponse({"error": "unknown session"}, status_code=404)

    async def gen():
        cmd = ingestion.run_session_cmd(folder, size)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace")
            v = ingestion.parse_line(line)
            if v is not None:
                yield "data: " + json.dumps(v) + "\n\n"
        await proc.wait()
        yield "data: " + json.dumps({"done": True}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- try a look ----------------
@app.post("/api/try")
async def api_try(look: str, photo: UploadFile):
    data = await photo.read()
    name = ingestion.safe_name(photo.filename)
    ok, reason = ingestion.validate(name, data)
    if not ok:
        return JSONResponse({"error": reason}, status_code=400)
    try:
        result = await asyncio.to_thread(looks.apply_look, look, data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        del data  # session-only: nothing kept on disk
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
