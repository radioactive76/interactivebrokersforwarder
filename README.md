
# **BrokerSiteHelper**

  

**BrokerSiteHelper** is a Python script and Chrome extension generator for probing Interactive Brokers domains in the European Economic Area and automatically selecting the IE entity and rejecting cookies.

----------

## **Supported Domains**

-   **Primary pinned CNs:**
    
    -   interactivebrokers.com
        
    -   ibkr.eu
        
    

  

Interactive Brokers in the EEA serves either interactivebrokers.com or ibkr.eu based on your locale. The script pins certificate common names (CNs) to avoid trusting unexpected redirects. Recent observations show redirections to additional country TLDs (e.g., .cz, .ro), and the previous .hu endpoint (formerly serviced by IBCE) has disappeared.

----------

## **How It Works**

1.  DNS + TLS handshake to interactivebrokers.<tld>.
    
2.  Certificate pinning: passes only if the certificate CN matches one of the pinned set.
    
3.  Results summary: prints a table sorted with known TLDs first, then extended.
    
4.  Extension build (optional): generates a Manifest V3 Chrome extension and packages it as a ZIP.
    

----------

## **Installation & Dependencies**

```
pip install tabulate urllib3 pillow
```

> _Pillow is optional; without it, the script falls back to a 1×1 transparent icon._

----------

## **Usage**

```
./generateFiles.py [--timeoutSeconds N] [--workerCount N] \
                   [--includeExtended] [--buildExtension] \
                   [--extensionDir PATH] [--zipOutput PATH]
```

Run ./generateFiles.py --help to see all flags:

```
usage: generateFiles.py [-h] [--timeoutSeconds TIMEOUTSECONDS]
                        [--workerCount WORKERCOUNT]
                        [--includeExtended] [--buildExtension]
                        [--extensionDir EXTENSIONDIR]
                        [--zipOutput ZIPOUTPUT]

Probe IBKR TLDs with certificate pinning & build a Chrome extension.

optional arguments:
  -h, --help            show this help message and exit
  -t TIMEOUTSECONDS, --timeoutSeconds TIMEOUTSECONDS
                        TLS connect timeout in seconds
  -w WORKERCOUNT, --workerCount WORKERCOUNT
                        number of parallel probes
  --includeExtended     also test extended TLDs
  --buildExtension      generate the Chrome extension bundle
  --extensionDir EXTENSIONDIR
                        output directory for extension files
  --zipOutput ZIPOUTPUT
                        path for the packaged extension ZIP
```

----------

## **Generating the Chrome Extension**

```
./generateFiles.py --buildExtension
```

-   Extension files appear under dist/extension.
    
-   A ZIP package is created at dist/brokersitehelper.zip by default.
    
-   Load in Chrome via chrome://extensions → **Load unpacked**, or import the ZIP.
    

----------

## **Disclaimers**

-   No warranty. Use at your own risk.
    
-   No affiliation with Interactive Brokers.
    
-   Happy customer coding on weekends—feel free to fork and modify.
    

----------

## **License**

  

This project is licensed under the MIT License. See LICENSE.
