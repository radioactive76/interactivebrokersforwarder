#!/usr/bin/env python3
"""
generateFiles.py — Probes IBKR TLDs, pins certs, builds Chrome extension ZIP.

1. Probes TLDs for DNS/TLS/HTTP and outputs a summary.
2. Only ibkr.eu and interactivebrokers.com are trusted cert CNs.
3. Builds Chrome extension with manifest.json at root.
"""

import argparse, os, json, zipfile, socket, ssl, shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tabulate import tabulate
from urllib3.exceptions import InsecureRequestWarning
import warnings

warnings.simplefilter("ignore", InsecureRequestWarning)

PINNED_CNS = ["ibkr.eu", "interactivebrokers.com"]
TRUSTED_TLDS = [
    "ch", "co.uk", "com", "de", "ee", "es", "eu", "fr", "ie", "it", "lu"
]
EXTENDED_TLDS = sorted([
    "ad","al","am","at","az","ba","bg","by","cy","cz","dk","fo","ge","gi","gr",
    "hr","hu","il","im","is","je","li","lt","lv","mc","md","me","mk","mt","nl",
    "no","pl","pt","ro","rs","se","si","sk","tr","ua","va"
])

def get_cert_cn(domain, timeout):
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
    except Exception:
        return None
    return None

def probe(domain, timeout):
    res = {
        "domain": domain,
        "cert_cn": None,
        "status": None,
        "final_url": None,
        "result": "FAIL",
        "reason": "",
        "scope": ""
    }
    tld = domain.split('.', 1)[1]
    res["scope"] = "TRUSTED" if tld in TRUSTED_TLDS else "EXTENDED"
    cert_cn = get_cert_cn(domain, timeout)
    res["cert_cn"] = cert_cn
    try:
        r = requests.get(f"https://{domain}/", timeout=timeout, allow_redirects=True)
        res["status"] = r.status_code
        res["final_url"] = r.url
    except requests.exceptions.ConnectionError as e:
        msg = str(e).lower()
        if "name or service not known" in msg or "failed to resolve" in msg:
            res["reason"] = "no dns"
        elif "refused" in msg:
            res["reason"] = "connection refused"
        elif "reset by peer" in msg:
            res["reason"] = "connection reset"
        else:
            res["reason"] = "connection error"
        return res
    except requests.exceptions.Timeout:
        res["reason"] = "timeout"
        return res
    except requests.exceptions.SSLError:
        res["reason"] = "tls handshake failed"
        return res
    except Exception:
        res["reason"] = "request error"
        return res
    # Cert validation
    if cert_cn in PINNED_CNS:
        res["result"] = "PASS"
        res["reason"] = "certificate pinned"
    elif cert_cn:
        res["reason"] = f"untrusted cert: {cert_cn}"
    else:
        res["reason"] = "no tls available"
    return res

def build_extension(extension_path):
    if os.path.isdir(extension_path):
        shutil.rmtree(extension_path)
    os.makedirs(os.path.join(extension_path, "icons"), exist_ok=True)
    # Minimal icon: 48x48 px PNG (redirect arrow with a cookie)
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (48, 48), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    # Arrow
    d.line((6, 24, 38, 24), fill=(31, 120, 225, 255), width=8)
    d.polygon([(32,20),(38,24),(32,28)], fill=(31,120,225,255))
    # Cookie
    d.ellipse((12,32,28,44), fill=(200,170,100,255), outline="saddlebrown", width=3)
    d.ellipse((17,36,19,38), fill="saddlebrown")
    d.ellipse((22,39,24,41), fill="saddlebrown")
    d.ellipse((25,35,27,37), fill="saddlebrown")
    img.save(os.path.join(extension_path, "icons", "icon.png"))
    # Manifest
    trusted_hosts = [f"*://*.interactivebrokers.{tld}/*" for tld in TRUSTED_TLDS]
    manifest = {
        "manifest_version": 3,
        "name": "BrokerSiteHelper",
        "version": "1.0.0",
        "description": "Auto-select IE entity & reject cookies on Interactive Brokers EU/IE.",
        "permissions": [ "scripting" ],
        "host_permissions": trusted_hosts,
        "icons": { "48": "icons/icon.png" },
        "content_scripts": [{
            "matches": trusted_hosts,
            "js": [ "content.js" ],
            "run_at": "document_idle"
        }]
    }
    with open(os.path.join(extension_path, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    # Content script
    js = """(() => {
  const action = () => {
    for (const el of document.querySelectorAll('button,a')) {
      const t = el.textContent.trim().toLowerCase();
      if (t==='go to ie website'){el.click();return;}
      if (['reject all cookies','reject cookies','ablehnen'].includes(t)){el.click();return;}
    }
  };
  action();
  const o = new MutationObserver(action);
  o.observe(document.body,{childList:true,subtree:true});
  setTimeout(()=>o.disconnect(),15000);
})();"""
    with open(os.path.join(extension_path, "content.js"), "w") as f:
        f.write(js)

def zipdir(basedir, zipfile_path):
    # Zips CONTENTS of basedir, not the dir itself
    with zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(basedir):
            for file in files:
                full = os.path.join(root, file)
                rel = os.path.relpath(full, basedir)
                zipf.write(full, rel)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--includeExtended", action="store_true")
    parser.add_argument("--buildExtension", action="store_true")
    parser.add_argument("--extensionDir", default="dist/extension")
    parser.add_argument("--zipOutput", default="dist/brokersitehelper.zip")
    args = parser.parse_args()

    # Sorted: TRUSTED first, then EXTENDED (alpha)
    domains = [f"interactivebrokers.{tld}" for tld in sorted(TRUSTED_TLDS)] + (
        [f"interactivebrokers.{tld}" for tld in EXTENDED_TLDS] if args.includeExtended else []
    )

    print("Probing domains...\n")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe, d, args.timeout): d for d in domains}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"{r['scope']} {r['domain']:28s} {r['cert_cn'] or 'NO_CERT':24s} {r['result']:4s}: {r['reason']}")

    # Summary table
    table = [[r["scope"], r["domain"], r["cert_cn"] or "NO_CERT", r["result"], r["reason"]] for r in results]
    print("\n"+tabulate(table, headers=["SCOPE","DOMAIN","CN","RESULT","REASON"], tablefmt="github"))

    if args.buildExtension:
        print(f"\nBuilding extension in {args.extensionDir}/ …")
        build_extension(args.extensionDir)
        os.makedirs(os.path.dirname(args.zipOutput), exist_ok=True)
        zipdir(args.extensionDir, args.zipOutput)
        print(f"Extension ZIP created at {args.zipOutput}")

if __name__ == "__main__":
    main()
