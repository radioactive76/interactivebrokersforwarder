#!/usr/bin/env python3
"""
generateFiles.py — probe IBKR TLDs with pinning & build Chrome extension.

Usage:
  python generateFiles.py [--timeoutSeconds FLOAT] [--workerCount INT]
                          [--includeExtended] [--buildExtension]
                          [--extensionDir PATH] [--zipOutput PATH]
"""
import argparse, os, socket, ssl, json, zipfile, shutil, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from tabulate import tabulate
from urllib3.exceptions import InsecureRequestWarning, NotOpenSSLWarning

warnings.simplefilter("ignore", InsecureRequestWarning)
warnings.simplefilter("ignore", NotOpenSSLWarning)

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    import base64

# ─── CONFIG ────────────────────────────────────────────────────────────
PINNED_CNS = {"ibkr.eu", "interactivebrokers.com", "www.interactivebrokers.com"}
KNOWN_TLDS = sorted(["com","co.uk","ee","eu","ch","de","es","fr","ie","it","lu"])
EXTENDED_TLDS = sorted([
  "ad","al","am","at","az","ba","bg","by","cy","cz","dk","fo","ge","gi","gr",
  "hr","hu","im","is","je","li","lt","lv","mc","md","me","mk","mt","nl","no",
  "pl","pt","ro","rs","se","si","sk","tr","ua","va"
])
EXT_NAME        = "BrokerSiteHelper"
EXT_VERSION     = "1.0.0"
EXT_DESCRIPTION = "Auto-select IE entity & reject cookies on Interactive Brokers EU/IE."
# ────────────────────────────────────────────────────────────────────────

def get_cert_cn(domain, timeout):
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(timeout)
            s.connect((domain,443))
            cert = s.getpeercert()
        for part in cert.get("subject",()):
            for k,v in part:
                if k.lower()=="commonname": return v
    except: pass
    return None

def probe(domain, timeout):
    cn = get_cert_cn(domain, timeout)
    if not cn: return domain, "-", False, "DNS/TLS error"
    if cn in PINNED_CNS: return domain, cn, True, "TLS pinning OK"
    return domain, cn, False, f"untrusted CN: {cn}"

def build_extension(dir_out):
    # clean
    if os.path.isdir(dir_out): shutil.rmtree(dir_out)
    os.makedirs(os.path.join(dir_out,"icons"), exist_ok=True)

    # draw icon.png (48×48)
    ico = os.path.join(dir_out,"icons","icon.png")
    if HAS_PIL:
        img = Image.new("RGBA",(48,48),(29,101,189,255))
        d = ImageDraw.Draw(img)
        # arrow
        d.rectangle([8,22,32,26], fill="white")
        d.polygon([(32,18),(44,24),(32,30)], fill="white")
        # cookie
        cx,cy,r = 36,36,10
        d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=(210,180,140,255))
        for dx,dy in [(-4,-4),(4,-2),(-2,4)]:
            d.ellipse([cx+dx-2,cy+dy-2,cx+dx+2,cy+dy+2], fill=(139,69,19,255))
        img.save(ico)
    else:
        with open(ico,"wb") as f:
            f.write(base64.b64decode(
              "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA"
              "AAC0lEQVR42mP8/w8AAgMBgGO216sAAAAASUVORK5CYII="))

    # manifest.json
    hosts = [f"*://*.interactivebrokers.{t}/*" for t in KNOWN_TLDS]
    manifest = {
      "manifest_version":3,
      "name":EXT_NAME,
      "version":EXT_VERSION,
      "description":EXT_DESCRIPTION,
      "permissions":["scripting"],
      "host_permissions":hosts,
      "icons":{"48":"icons/icon.png"},
      "content_scripts":[{
        "matches":hosts,
        "js":["content.js"],
        "run_at":"document_idle"
      }]
    }
    with open(os.path.join(dir_out,"manifest.json"),"w") as f:
        json.dump(manifest,f,indent=2)

    # content.js
    js = """(() => {
  const click = toks => {
    for (const el of document.querySelectorAll('button,a')) {
      const t=el.textContent.trim().toLowerCase();
      if (toks.includes(t)){ el.click(); return; }
    }
    return false;
  };
  const act = () => {
    click(['go to ie website']);
    click(['reject all cookies','reject cookies','ablehnen']);
  };
  act();
  const o=new MutationObserver(act);
  o.observe(document.body,{childList:true,subtree:true});
  setTimeout(()=>o.disconnect(),15000);
})();"""
    with open(os.path.join(dir_out,"content.js"),"w") as f:
        f.write(js)

def zip_extension(src, dst):
    with zipfile.ZipFile(dst,"w") as z:
        for root,_,files in os.walk(src):
            for name in files:
                full = os.path.join(root,name)
                z.write(full, os.path.relpath(full, src))

def main():
    p=argparse.ArgumentParser(description=__doc__,
       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-t","--timeoutSeconds", type=float, default=5.0)
    p.add_argument("-w","--workerCount",   type=int, default=10)
    p.add_argument("--includeExtended", action="store_true")
    p.add_argument("--buildExtension", action="store_true")
    p.add_argument("--extensionDir", default="dist/extension")
    p.add_argument("--zipOutput",   default="dist/brokersitehelper.zip")
    args = p.parse_args()

    tlds = KNOWN_TLDS + (EXTENDED_TLDS if args.includeExtended else [])
    domains = [f"interactivebrokers.{t}" for t in tlds]

    results=[]
    with ThreadPoolExecutor(max_workers=args.workerCount) as ex:
        futs={ex.submit(probe,d,args.timeoutSeconds):d for d in domains}
        for f in as_completed(futs):
            domain,cn,ok,reason=f.result()
            scope = "KNOWN" if domain.split(".",1)[1] in KNOWN_TLDS else "EXTENDED"
            results.append((scope,domain,cn,"PASS" if ok else "FAIL",reason))

    results.sort(key=lambda r:(0 if r[0]=="KNOWN" else 1, r[1]))
    print(tabulate(results,
      headers=["SCOPE","DOMAIN","CN","RESULT","REASON"], tablefmt="github"))

    if args.buildExtension:
        build_extension(args.extensionDir)
        os.makedirs(os.path.dirname(args.zipOutput),exist_ok=True)
        zip_extension(args.extensionDir,args.zipOutput)
        # sanity‐check
        print("\nZIP contents:")
        print(os.popen(f"unzip -l {args.zipOutput}").read())
        print(f"→ extension ZIP is {args.zipOutput}")

if __name__=="__main__":
    main()
