"""Offline browser acceptance for bundled typography, not source business logic.

Captured provider inputs plus all complete bundled poems exercise every built-in
text layout at all panel sizes. This catches real font fallback, fractional
pixel scaling and clipped text that HTML-string assertions cannot detect.
"""

import asyncio
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fontTools.ttLib import TTFont
from PIL import Image

from inkage.fonts import FONT_DIR, FONTS
from inkage.panel import PRESETS
from inkage.quotes import parse_tencent_many
from inkage.render import Renderer, _inject_head
from inkage.source import Context, load_sources
from inkage.sources.github_profile.calendar import parse_calendar

FIX = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-10-13T11:30:00+08:00")
GRIDS = {"Fusion Pixel 12": 12, "Fusion Pixel 10": 10, "Unifont": 16, "Departure Mono": 11}


def read_json(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


async def samples(registry):
    frozen = read_json("typography/samples.json")
    cases = [sample for sample in frozen if sample["source"] != "poetry"]

    def add(name, data, variant="", **params):
        cases.append({"id": f"{name}{variant}", "source": name, "params": params, "data": data})

    def context(name, **params):
        return Context(now=NOW, tz=ZoneInfo("Asia/Shanghai"), params={**registry[name].params, **params})

    # All six complete poems: their different line lengths previously exposed wrapping.
    for poem in registry["poetry"].fetch.__globals__["POEMS"]:
        add("poetry", poem, f"-{poem['id']}")
    for name in ("astro", "countdown"):
        add(name, await registry[name]().fetch(context(name)))
    # Six-week calendar and festival text supplement the accepted five-week October sample.
    calendar_ctx = Context(now=datetime.fromisoformat("2026-08-01T12:00:00+08:00"), tz=ZoneInfo("Asia/Shanghai"))
    add("calendar", await registry["calendar"]().fetch(calendar_ctx), "-six-weeks")
    funcs = registry["air_quality"].fetch.__globals__
    add(
        "air_quality",
        {"label": "Shanghai", **funcs["parse_air_quality"](read_json("air_quality/open_meteo_shanghai.json"), NOW)},
    )
    funcs = registry["fx"].fetch.__globals__
    add(
        "fx",
        funcs["parse_series"](
            read_json("fx/frankfurter_usd_series.json"), "USD", ["CNY", "EUR", "JPY", "GBP"], NOW.date()
        ),
    )
    funcs = registry["github"].fetch.__globals__
    add(
        "github",
        funcs["summarize"](
            read_json("github/repo.json"),
            read_json("github/commits.json"),
            read_json("github/release_uv.json"),
            context("github"),
        ),
    )
    for name, fixture in (("github_ci", "github_ci/runs.json"), ("status", "status/github_summary.json")):
        parser = registry[name].fetch.__globals__["parse_runs" if name == "github_ci" else "parse_summary"]
        add(name, parser(read_json(fixture), context(name)))
    funcs = registry["github_profile"].fetch.__globals__
    profile = funcs["profile_data"](read_json("github_profile/user.json"), "RoCry")
    del profile["avatar_url"]
    profile.update(
        avatar=funcs["avatar_data"]((FIX / "github_profile/avatar.jpg").read_bytes()),
        calendar=parse_calendar((FIX / "github_profile/contributions.html").read_text()),
    )
    for layout in ("profile", "isometric"):
        add("github_profile", profile, f"-{layout}", layout=layout)
    # Only the artwork caption is under test; reuse an offline image rather than download art.
    funcs = registry["art"].fetch.__globals__
    art = funcs["parse_artwork"](read_json("art/met_wheat.json"), 436535)
    add("art", {**art, "image": (FIX / "github_profile/avatar.jpg").read_bytes()})
    # The six-coin maximum was not represented by the accepted three-coin gallery.
    crypto = next(c for c in cases if c["source"] == "crypto")
    # Explicit synthetic extra rows reuse captured prices, solely to fill the max layout.
    coins = crypto["data"]["coins"] + [
        {**coin, "symbol": symbol} for coin, symbol in zip(crypto["data"]["coins"], ["XRP", "DOGE", "ADA"], strict=True)
    ]
    add("crypto", {**crypto["data"], "coins": coins}, "-six")
    captured = (FIX / "quotes/tencent_multi.txt").read_bytes().decode("gbk")
    for name, codes, market in (("index", ["sh000300", "sh000001"], "cn"), ("stock", ["usAAPL", "usNVDA"], "us")):
        src = registry[name]()
        rows = []
        for symbol, quote in zip(codes, parse_tencent_many(captured, codes, market), strict=True):
            rows.append(
                {
                    "name": src.label(symbol, quote),
                    "code": quote.code,
                    "price": f"{quote.price:,.2f}",
                    "change": f"{quote.change:+,.2f}",
                    "change_pct": f"{quote.change_pct:+.2f}%",
                    "direction": "up" if quote.change > 0 else "down",
                    "high": f"{quote.high:,.2f}",
                    "low": f"{quote.low:,.2f}",
                    "prev_close": f"{quote.prev_close:,.2f}",
                    "time": quote.time.strftime("%Y-%m-%d %H:%M %Z"),
                }
            )
        for mode, selected in (("single", rows[:1]), ("watch", rows)):
            add(name, {**selected[0], "quotes": selected}, f"-{mode}")
    # News accepts up to 30 stories; portrait must show a readable first eight
    # and an explicit count, rather than squeeze 30 rows below the panel edge.
    title, items = registry["news"].fetch.__globals__["feed_items"](
        (FIX / "news/hn_rss.xml").read_bytes(), 30, context("news")
    )
    add("news", {"label": title, "items": items}, "-thirty")
    cases[-1]["panels"] = ("528x792-bw",)
    return cases


# Range rectangles expose text outside the panel even when the browser screenshot
# silently crops it. CSS ellipsis/line-clamp are deliberate truncation; intersect
# those rectangles with their declared clipping box before checking panel bounds.
INSPECT = """() => {
 const runs=[];const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while(walker.nextNode()){
  const n=walker.currentNode,p=n.parentElement;if(!n.textContent.trim())continue;
  if(p.closest('script,style,title,defs'))continue;
  const s=getComputedStyle(p);const range=new Range();range.selectNode(n);
  let rects=[...range.getClientRects()].map(r=>({x:r.x,y:r.y,right:r.right,bottom:r.bottom}));
  if(!rects.length)continue;
  const issues=[];let hidden=false;
  for(let a=p;a;a=a.parentElement){
   const c=getComputedStyle(a),b=a.getBoundingClientRect();
   if(c.display==='none'||c.visibility==='hidden'){hidden=true;break;}
   const truncate=c.textOverflow==='ellipsis'||Number(c.webkitLineClamp)>0;
   const clipX=['hidden','clip'].includes(c.overflowX),clipY=['hidden','clip'].includes(c.overflowY);
   for(const r of rects){
    if(truncate){
     if(clipX){r.x=Math.max(r.x,b.x);r.right=Math.min(r.right,b.right);}
     if(clipY){r.y=Math.max(r.y,b.y);r.bottom=Math.min(r.bottom,b.bottom);}
    }else if(a!==document.body&&a!==document.documentElement&&
      ((clipX&&(r.x<b.x-1||r.right>b.right+1))||(clipY&&(r.y<b.y-1||r.bottom>b.bottom+1)))){
      issues.push('clipped by '+((a.className.baseVal??a.className)||a.tagName));
    }
   }
  }
  if(hidden)continue;
  rects=rects.filter(r=>r.right>r.x&&r.bottom>r.y);
  runs.push({text:n.textContent.trim(),family:s.fontFamily.split(',')[0].replaceAll('"',''),
    size:parseFloat(s.fontSize),weight:s.fontWeight,rects,issues});
 }
 return runs;
}"""


async def check_page(renderer, html, panel, folder, faces, complete_lines=()):
    # Use production launch flags and CSS, then inspect the exact loaded document.
    if renderer._browser is None:
        await renderer.html_to_image("<html><head></head><body></body></html>", 250, 122, folder)
    path = folder / "typography.html"
    path.write_text(_inject_head(html, f"<style>{renderer._css}</style>"), encoding="utf-8")
    page = await renderer._browser.new_page(viewport={"width": panel.width, "height": panel.height})
    try:
        await page.route("http://**", lambda route: route.abort())
        await page.route("https://**", lambda route: route.abort())
        await page.goto(path.as_uri(), wait_until="load")
        await page.evaluate("document.fonts.ready")
        runs = await page.evaluate(INSPECT)
        errors = []
        rendered_text = [run["text"] for run in runs]
        for line in complete_lines:
            if line not in rendered_text:
                errors.append(f"complete poem line omitted: {line!r}")
        for run in runs:
            text, family = run["text"], run["family"]
            if family not in faces:
                errors.append(f"unbundled font {family!r}: {text!r}")
                continue
            if run["size"] % GRIDS[family]:
                errors.append(f"fractional grid {family} {run['size']}px: {text!r}")
            if run["weight"] != "400":
                errors.append(f"synthetic weight {run['weight']}: {text!r}")
            if missing := sorted(c for c in set(text) if not c.isspace() and ord(c) not in faces[family][0]):
                errors.append(f"{family} missing glyphs {missing}: {text!r}")
            errors.extend(f"{issue}: {text!r}" for issue in run["issues"])
            if any(
                r["x"] < -1 or r["y"] < -1 or r["right"] > panel.width + 1 or r["bottom"] > panel.height + 1
                for r in run["rects"]
            ):
                errors.append(f"outside {panel.width}x{panel.height}: {text!r} {run['rects']}")
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("DOM.enable")
        await cdp.send("CSS.enable")
        document = await cdp.send("DOM.getDocument")
        nodes = await cdp.send("DOM.querySelectorAll", {"nodeId": document["root"]["nodeId"], "selector": "body *"})
        used = []
        for node_id in nodes["nodeIds"]:
            used.extend((await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node_id}))["fonts"])
        expected = {font[1] for font in faces.values()}
        if not used or any(not f["isCustomFont"] or f["postScriptName"] not in expected for f in used):
            errors.append(f"font failed to load or system fallback: {used}")
        # Also exercise screenshot capture; real content must paint, not just load CSS.
        png = Image.open(io.BytesIO(await page.screenshot(type="png"))).convert("RGB")
        if png.size != (panel.width, panel.height) or png.getextrema() == ((255, 255),) * 3:
            errors.append("empty or incorrectly sized rendered frame")
        return errors
    finally:
        await page.close()


def test_builtin_pixel_typography_renders_offline_without_fallback_or_clipping(tmp_path):
    faces = {}
    for family, filename in FONTS.items():
        with TTFont(FONT_DIR / filename) as font:
            faces[family] = (set(font.getBestCmap()), font["name"].getDebugName(6))

    async def verify():
        registry = load_sources()
        failures = []
        async with Renderer() as renderer:
            cases = await samples(registry)
            expected_sources = {name for name, cls in registry.items() if cls().template_dir.is_dir()}
            assert {sample["source"] for sample in cases} == expected_sources, (
                "add new text sources to acceptance matrix"
            )
            for sample in cases:
                source = registry[sample["source"]]()
                ctx = Context(now=NOW, tz=ZoneInfo("Asia/Shanghai"), params={**source.params, **sample["params"]})
                for size in sample.get("panels", ("250x122-bwr", "800x480-bwr", "528x792-bw")):
                    panel = PRESETS[size]
                    html = source.render(ctx, panel, sample["data"])
                    complete_lines = sample["data"]["lines"] if sample["source"] == "poetry" else ()
                    errors = await check_page(renderer, html, panel, tmp_path, faces, complete_lines)
                    failures.extend(f"{sample['id']} {size}: {error}" for error in errors)
        assert not failures, "\n".join(failures)

    asyncio.run(verify())
