#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generateFiles.py — probe IBKR TLDs, pin certs, build Chrome extension & store assets.

Usage:
  ./generateFiles.py --buildExtension [--includeExtended]
                     [--extensionDir dist/extension]
                     [--zipOutput dist/brokersitehelper.zip]
                     [--timeout 5.0] [--workers 10]
"""

import argparse, os, json, zipfile, socket, ssl, shutil, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from tabulate import tabulate
import requests
from urllib3.exceptions import InsecureRequestWarning, NotOpenSSLWarning

# suppress urllib3 TLS + LibreSSL warnings
warnings.simplefilter("ignore", InsecureRequestWarning)
warnings.simplefilter("ignore", NotOpenSSLWarning)

# ── Pinning: allow EU and US certs (co.uk presents *.interactivebrokers.com)
PINNED_CNS = {
    "ibkr.eu",
    "interactivebrokers.com",
    "www.interactivebrokers.com",
}

# Domains we actually run on (sorted; .com included)
TRUSTED_TLDS = sorted(["ch","co.uk","com","de","ee","es","eu","fr","ie","it","lu"])

# Optional exploration set
EXTENDED_TLDS = sorted([
    "ad","al","am","at","az","ba","bg","by","cy","cz","dk","fo","ge","gi","gr",
    "hr","hu","il","im","is","je","li","lt","lv","mc","md","me","mk","mt","nl",
    "no","pl","pt","ro","rs","se","si","sk","tr","ua","va"
])

EXT_NAME        = "BrokerSiteHelper"
EXT_VERSION     = "1.0.1"
EXT_DESCRIPTION = "Auto-select IE/EU entity & reject cookie prompts on Interactive Brokers sites."

# ──────────────────────────────────────────────────────────────────────────────

def get_cert_cn(domain: str, timeout: float):
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(timeout)
            s.connect((domain, 443))
            cert = s.getpeercert()
        for part in cert.get("subject", ()):
            for k, v in part:
                if k.lower() == "commonname":
                    return v
    except socket.gaierror:
        return None
    except (socket.timeout, ssl.SSLError, OSError):
        return None
    except Exception:
        return None

def probe(domain: str, timeout: float):
    cn = get_cert_cn(domain, timeout)
    scope = "TRUSTED" if domain.split(".",1)[1] in TRUSTED_TLDS else "EXTENDED"

    # Try a simple HTTPS GET mainly to classify network errors
    reason = ""
    try:
        requests.get(f"https://{domain}/", timeout=timeout, allow_redirects=True)
    except requests.exceptions.ConnectionError as e:
        msg = str(e).lower()
        if "failed to resolve" in msg or "name or service not known" in msg:
            reason = "no dns"
        elif "refused" in msg:
            reason = "connection refused"
        elif "reset by peer" in msg:
            reason = "connection reset"
        else:
            reason = "connection error"
    except requests.exceptions.Timeout:
        reason = "timeout"
    except requests.exceptions.SSLError:
        reason = "tls handshake failed"

    if not cn:
        return scope, domain, "NO_CERT", "FAIL", (reason or "dns/tls error")

    if cn in PINNED_CNS:
        return scope, domain, cn, "PASS", "certificate pinned"

    return scope, domain, cn, "FAIL", f"untrusted cert: {cn}"

# ── icon drawing (48px for extension, 128px for store)
def _draw_icon(path: str, size: int):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("Pillow is required to draw icons: pip install pillow")

    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    # arrow
    y = size//2
    d.line((size*0.12, y, size*0.66, y), fill=(31,120,225,255), width=max(2, size//12))
    d.polygon([(size*0.60, y - size*0.10),
               (size*0.84, y),
               (size*0.60, y + size*0.10)], fill=(31,120,225,255))
    # cookie
    r = int(size*0.18)
    cx, cy = int(size*0.72), int(size*0.72)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(200,170,100,255), outline="saddlebrown", width=max(1,size//40))
    for dx,dy in [(-r//2,-r//2),(r//3,-r//4),(-r//4,r//3)]:
        d.ellipse((cx+dx- r//6, cy+dy- r//6, cx+dx+ r//6, cy+dy+ r//6), fill="saddlebrown")
    img.convert("RGB").save(path, "PNG")  # no alpha for store if you want JPG later

def build_extension(extension_dir: str, store_dir: str):
    # clean & mkdirs
    if os.path.isdir(extension_dir):
        shutil.rmtree(extension_dir)
    os.makedirs(os.path.join(extension_dir, "icons"), exist_ok=True)
    os.makedirs(store_dir, exist_ok=True)

    # icons
    _draw_icon(os.path.join(extension_dir, "icons", "icon.png"), 48)
    _draw_icon(os.path.join(store_dir, "icon-128.png"), 128)  # store upload asset

    # manifest WITHOUT "scripting" permission
    hosts = [f"*://*.interactivebrokers.{t}/*" for t in TRUSTED_TLDS]
    manifest = {
        "manifest_version": 3,
        "name": EXT_NAME,
        "version": EXT_VERSION,
        "description": EXT_DESCRIPTION,
        "permissions": [],
        "host_permissions": hosts,
        "icons": {"48": "icons/icon.png"},
        "content_scripts": [{
            "matches": hosts,
            "js": ["content.js"],
            "run_at": "document_idle"
        }]
    }
    with open(os.path.join(extension_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # content.js (simple, deterministic)
    js = """(() => {
  const click = labels => {
    for (const el of document.querySelectorAll('button,a')) {
      const t = el.textContent.trim().toLowerCase();
      if (labels.includes(t)) { el.click(); return true; }
    }
    return false;
  };
  const act = () => {
    click(['go to ie website']);
    click(['reject all cookies','reject cookies','ablehnen']);
  };
  act();
  const o = new MutationObserver(act);
  o.observe(document.body,{ childList:true, subtree:true });
  setTimeout(() => o.disconnect(), 15000);
})();"""
    with open(os.path.join(extension_dir, "content.js"), "w", encoding="utf-8") as f:
        f.write(js)

def zip_extension(src_dir: str, zip_path: str):
    # zip *contents* of src_dir so manifest.json is at zip root
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.relpath(full, src_dir)
                z.write(full, arc)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--includeExtended", action="store_true")
    ap.add_argument("--buildExtension", action="store_true")
    ap.add_argument("--extensionDir", default="dist/extension")
    ap.add_argument("--storeAssetsDir", default="dist/store-assets")
    ap.add_argument("--zipOutput", default="dist/brokersitehelper.zip")
    args = ap.parse_args()

    # probe list
    domains = [f"interactivebrokers.{t}" for t in TRUSTED_TLDS] + (
        [f"interactivebrokers.{t}" for t in EXTENDED_TLDS] if args.includeExtended else []
    )

    print("Probing domains...\n")
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe, d, args.timeout): d for d in domains}
        for f in as_completed(futs):
            rows.append(f.result())

    # sort: trusted first, alphabetical
    rows.sort(key=lambda r: (0 if r[0]=="TRUSTED" else 1, r[1]))

    print(tabulate(rows, headers=["SCOPE","DOMAIN","CN","RESULT","REASON"], tablefmt="github"))

    if args.buildExtension:
        print(f"\nBuilding extension at {args.extensionDir} …")
        build_extension(args.extensionDir, args.storeAssetsDir)
        zip_extension(args.extensionDir, args.zipOutput)
        print(f"Extension ZIP → {args.zipOutput}")
        print(f"Store icon     → {os.path.join(args.storeAssetsDir,'icon-128.png')}")


if __name__ == "__main__":
    main()
