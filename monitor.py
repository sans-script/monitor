import time
import concurrent.futures
import random
import warnings
import urllib3
import requests
import socket
import threading
import http.server
import socketserver
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# Suppress SSL warnings
warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SITES = [
    # G1: Hero
    ("Prefeitura São Luís", "https://saoluis.ma.gov.br"),
    ("Gov Maranhão", "https://ma.gov.br"),

    # G2: Priority
    ("SEI", "https://sei.saoluis.ma.gov.br"),
    ("Diário Oficial", "https://diariooficial.saoluis.ma.gov.br"),
    ("GIAP", "https://saoluis.giap.com.br"),
    ("E-OUV", "https://eouv.saoluis.ma.gov.br"),
    ("E-SIC", "https://esic.saoluis.ma.gov.br"),
    ("PCA Contratos", "https://pcacontratos.saoluis.ma.gov.br"),
    ("Conecta São Luís", "https://conecta.saoluis.ma.gov.br"),
    ("BI", "https://bi.saoluis.ma.gov.br/"),
    ("Portal da Transparência", "https://transparencia.saoluis.ma.gov.br"),
    ("Transparência BI", "https://transparenciabi.saoluis.ma.gov.br"),

    # G3: Standard
    ("Precatório FUNDEF", "https://precatoriofundef.saoluis.ma.gov.br"),
    ("1Doc Legado", "https://1doc-legado.saoluis.ma.gov.br/auth/login"),
    ("Cidadão Seguro", "https://cidadaoseguro.saoluis.ma.gov.br/"),
    ("Link Verde", "https://linkverde.saoluis.ma.gov.br/"),
    ("Reurb App", "https://reurbapp.saoluis.ma.gov.br/ping"),
    ("Prod SEMAPA", "https://prodsemapa.saoluis.ma.gov.br/ping"),
    ("Câmeras", "https://cameras.saoluis.ma.gov.br"),

    # G4: Priority 2
    ("São Luís Online", "https://saoluisonline.saoluis.ma.gov.br"),
    ("Chat App", "https://chatapp.saoluis.ma.gov.br/webchat/"),
    ("SAE", "https://sae.saoluis.ma.gov.br/"),
    ("ADI", "https://adi.saoluis.ma.gov.br"),
    ("EGGEM (Homolog)", "https://homolog-eggem.saoluis.ma.gov.br/"),
    ("Siscon QA", "https://sisconqa.saoluis.ma.gov.br/"),
    ("Negócio Legal", "https://negociolegal.saoluis.ma.gov.br/"),
    ("Queridômetro", "https://queridometro.saoluis.ma.gov.br/questionario/id"),
    ("Voucher SLZ", "https://voucher.saoluis.ma.gov.br/"),

    # G5: Footer
    ("Suporte", "https://suporte.saoluis.ma.gov.br"),
    ("Webmail", "https://mail.saoluis.ma.gov.br"),
    ("SEMIT Cloud", "https://cloudsemit.saoluis.ma.gov.br/"),
]

# Polling interval (seconds) between cycles. Lower -> faster detection, but more CPU/network.
INTERVAL_SECONDS = 5
MAX_WORKERS = 10

# Timeouts
REQUEST_TIMEOUT = 5  # seconds for lightweight HTTP checks
SELENIUM_PAGE_LOAD_TIMEOUT = 10  # seconds for Selenium page loads
SELENIUM_MAX_ATTEMPTS = 1

# Only use Selenium for sites that require JS rendering. Leave empty to avoid heavy browser starts.
# Add exact hostnames or full URLs that need Selenium, e.g. {"https://example.com"}
# `https://ma.gov.br` is slow/has cert issues — handle it with Selenium.
SELENIUM_REQUIRED = {"https://ma.gov.br"}

# Selenium worker pool size and per-site overrides
SELENIUM_WORKERS = 2
SELENIUM_OVERRIDES = {
    "https://ma.gov.br": {"page_load_timeout": 30, "attempts": 2}
}

# HTTP server settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Ensure browsers do not cache the dashboard
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        # Serve dashboard.html for root
        if self.path in ('', '/', '/index.html'):
            self.path = '/dashboard.html'
        return super().do_GET()

def start_http_server(host=SERVER_HOST, port=SERVER_PORT):
    # Serve files from this script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    handler = NoCacheHandler
    with socketserver.ThreadingTCPServer((host, port), handler) as httpd:
        httpd.allow_reuse_address = True
        local_ip = get_local_ip()
        print(f"HTTP server: http://{local_ip}:{port}/ (listening on {host}:{port})")
        try:
            httpd.serve_forever()
        except Exception as e:
            print(f"HTTP server stopped: {e}")


def get_chrome_options():
    """Optimized Chrome options for headless mode"""
    opt = Options()
    opt.add_argument('--headless=new')
    opt.add_argument('--no-sandbox')
    opt.add_argument('--disable-dev-shm-usage')
    opt.add_argument('--disable-gpu')
    opt.add_argument('--disable-blink-features=AutomationControlled')
    opt.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opt.add_experimental_option('useAutomationExtension', False)
    opt.add_argument('--disable-web-security')
    opt.add_argument('--allow-running-insecure-content')
    opt.add_argument('--lang=pt-BR,pt,en-US,en')
    opt.add_argument('--window-size=1920,1080')
    opt.add_argument('--disable-infobars')
    opt.add_argument('--ignore-certificate-errors')
    opt.add_argument('--allow-insecure-localhost')
    opt.page_load_strategy = 'eager' # Don't wait for all resources
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    ]
    opt.add_argument(f'--user-agent={random.choice(user_agents)}')
    return opt

def check(url):
    """
    Checks URL status using Selenium (same logic as sentinel.py).
    Returns: ok (bool), status_code (str/int), latency_ms (int), error_msg (str)
    """
    t0 = time.perf_counter()
    ms = 0
    
    # 1. Fast path: try requests first to get HTTP status code quickly
    http_code = None
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, verify=False, allow_redirects=True, headers={
             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        http_code = r.status_code
        if http_code >= 500:
             ms = int((time.perf_counter() - t0) * 1000)
             return False, http_code, ms, f"HTTP {http_code} - Erro do Servidor"
        # If requests succeeded and returned a non-5xx code, consider site up.
        ms = int((time.perf_counter() - t0) * 1000)
        return True, http_code, ms, ""
    except requests.RequestException as e:
        # If the site is known to require Selenium rendering, try the heavy path.
        if url not in SELENIUM_REQUIRED:
            ms = int((time.perf_counter() - t0) * 1000)
            return False, "-", ms, f"Request error: {str(e)}"
        # else: fall through to Selenium for JS-heavy sites

    # 2. Heavy path: Selenium
    driver = None
    attempts = 0
    max_attempts = SELENIUM_MAX_ATTEMPTS
    
    while attempts < max_attempts:
        try:
            attempts += 1
            service = Service()
            driver = webdriver.Chrome(service=service, options=get_chrome_options())
            
            driver.set_page_load_timeout(SELENIUM_PAGE_LOAD_TIMEOUT)
            driver.set_script_timeout(SELENIUM_PAGE_LOAD_TIMEOUT)
            
            driver.get(url)
            # Small short sleep to allow minimal JS execution (keep small)
            time.sleep(random.uniform(0.2, 0.5))
            
            page_text = driver.page_source
            title = driver.title if driver.title else "Sem título"
            
            # Check for generic browser error pages
            error_codes = [
                "DNS_PROBE_FINISHED_NXDOMAIN",
                "ERR_NAME_NOT_RESOLVED",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_CONNECTION_CLOSED",
                "ERR_SSL_PROTOCOL_ERROR",
                "ERR_CERT_AUTHORITY_INVALID"
            ]
            
            for error_code in error_codes:
                if error_code in page_text:
                    if driver: driver.quit()
                    ms = int((time.perf_counter() - t0) * 1000)
                    return False, "-", ms, error_code

            # Check for Gateway errors (Nginx/Apache default pages often reflect in title)
            title_lower = title.lower()
            if any(err in title_lower for err in ["502", "503", "504", "bad gateway", "service unavailable"]):
                if driver: driver.quit()
                ms = int((time.perf_counter() - t0) * 1000)
                return False, http_code if http_code else "50x", ms, f"HTTP Error via Browser ({title})"

            # Success
            if driver: driver.quit()
            ms = int((time.perf_counter() - t0) * 1000)
            
            final_code = http_code if http_code else 200
            return True, final_code, ms, ""
        
        except TimeoutException:
            if driver: driver.quit()
            if attempts < max_attempts: continue
            ms = int((time.perf_counter() - t0) * 1000)
            return False, "-", ms, "Timeout (Selenium)"
            
        except WebDriverException as e:
            if driver: driver.quit()
            error_str = str(e).upper()
            
            # Map common selenium errors to short strings
            short_err = "WebDriver Error"
            if "NXDOMAIN" in error_str: short_err = "DNS_PROBE_FINISHED_NXDOMAIN"
            elif "NAME_NOT_RESOLVED" in error_str: short_err = "ERR_NAME_NOT_RESOLVED"
            elif "REFUSED" in error_str: short_err = "ERR_CONNECTION_REFUSED"
            elif "TIMED_OUT" in error_str: short_err = "ERR_CONNECTION_TIMED_OUT"
            elif "UNREACHABLE" in error_str: short_err = "ERR_ADDRESS_UNREACHABLE"
            else:
                # If unknown, show a bit more detail
                short_err = f"Erro: {str(e).splitlines()[0][:40]}"
            
            if "ERR_" in short_err and attempts < max_attempts:
                continue
                
            ms = int((time.perf_counter() - t0) * 1000)
            return False, "-", ms, short_err
            
        except Exception as e:
            if driver: driver.quit()
            ms = int((time.perf_counter() - t0) * 1000)
            return False, "-", ms, str(e)
            
    if driver: driver.quit()
    return False, "-", int((time.perf_counter() - t0) * 1000), "Erro desconhecido"

def check_wrapper(site_tuple):
    """Wrapper for parallel execution"""
    name, url = site_tuple
    ok, code, ms, err = check(url)
    return name, url, ok, code, ms, err


def fast_check(site_tuple):
    name, url = site_tuple
    t0 = time.perf_counter()
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, verify=False, allow_redirects=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        code = r.status_code
        if code >= 500:
            ms = int((time.perf_counter() - t0) * 1000)
            return name, url, False, code, ms, f"HTTP {code} - Erro do Servidor"
        ms = int((time.perf_counter() - t0) * 1000)
        return name, url, True, code, ms, ""
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return name, url, False, "-", ms, f"Request error: {str(e)}"


def selenium_check(site_tuple, page_load_timeout=None, attempts_override=None):
    name, url = site_tuple
    t0 = time.perf_counter()
    attempts = attempts_override if attempts_override is not None else SELENIUM_MAX_ATTEMPTS
    page_timeout = page_load_timeout if page_load_timeout is not None else SELENIUM_PAGE_LOAD_TIMEOUT

    driver = None
    tries = 0
    while tries < attempts:
        try:
            tries += 1
            service = Service()
            driver = webdriver.Chrome(service=service, options=get_chrome_options())
            driver.set_page_load_timeout(page_timeout)
            driver.set_script_timeout(page_timeout)
            driver.get(url)
            time.sleep(random.uniform(0.2, 0.5))
            page_text = driver.page_source
            title = driver.title if driver.title else "Sem título"

            # check for common browser error markers
            error_codes = [
                "DNS_PROBE_FINISHED_NXDOMAIN",
                "ERR_NAME_NOT_RESOLVED",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_CONNECTION_CLOSED",
                "ERR_SSL_PROTOCOL_ERROR",
                "ERR_CERT_AUTHORITY_INVALID"
            ]
            for ec in error_codes:
                if ec in page_text:
                    if driver: driver.quit()
                    ms = int((time.perf_counter() - t0) * 1000)
                    return name, url, False, "-", ms, ec

            title_lower = title.lower()
            if any(err in title_lower for err in ["502", "503", "504", "bad gateway", "service unavailable"]):
                if driver: driver.quit()
                ms = int((time.perf_counter() - t0) * 1000)
                return name, url, False, "50x", ms, f"HTTP Error via Browser ({title})"

            if driver: driver.quit()
            ms = int((time.perf_counter() - t0) * 1000)
            return name, url, True, 200, ms, ""

        except TimeoutException:
            if driver: driver.quit()
            if tries < attempts: continue
            ms = int((time.perf_counter() - t0) * 1000)
            return name, url, False, "-", ms, "Timeout (Selenium)"
        except WebDriverException as e:
            if driver: driver.quit()
            err = str(e)
            ms = int((time.perf_counter() - t0) * 1000)
            return name, url, False, "-", ms, err
        except Exception as e:
            if driver: driver.quit()
            ms = int((time.perf_counter() - t0) * 1000)
            return name, url, False, "-", ms, str(e)

def render_html(rows, generated_at):
    cards = []
    
    # 1. Define categorization based on URL substrings or full matches
    
    # Hero: Very large/prominent
    hero_urls = ["https://saoluis.ma.gov.br", "https://ma.gov.br"]
    
    # Priority: Standard prominent size ("Highlighted" in user terms = normal but important)
    # The default for everything else in the top blocks
    
    # Small: Condensed size
    small_keywords = [
        "precatoriofundef", "1doc-legado", "cidadaoseguro", "linkverde",
        "reurbapp", "prodsemapa", "cameras", "suporte", "mail", "cloudsemit"
    ]
    
    # Reconstruct dictionary from results for O(1) access
    # But wait, user wants EXACT ORDER from SITES list.
    # The 'rows' might be out of order due to threading.
    # We must sort 'rows' to match 'SITES'.
    
    results_map = {item[1]: item for item in rows} # url -> result tuple
    
    sorted_rows = []
    for site_name, site_url in SITES:
        if site_url in results_map:
            sorted_rows.append(results_map[site_url])
        else:
            # Fallback if somehow missing
            sorted_rows.append((site_name, site_url, False, "-", 0, "Not checked"))

    for name, url, ok, code, ms, err in sorted_rows:
        status_cls = "status-up" if ok else "status-down"
        
        # Determine Card Style
        card_size_cls = "card-highlight" # Default
        
        if url in hero_urls:
            card_size_cls = "card-hero"
        elif any(k in url.lower() for k in small_keywords):
            card_size_cls = "card-small"

        # Error tooltip
        title_attr = f"{name} - ONLINE ({ms}ms)"
        if not ok:
            err_clean = str(err).replace('"', "'")
            title_attr = f"{name} - OFFLINE: {err_clean}"

        cards.append(f"""
        <a href="{url}" target="_blank" class="card {card_size_cls} {status_cls}" title="{title_attr}">
            <div class="site-name">{name}</div>
        </a>
        """)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sentinela - São Luís</title>
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <style>
        :root {{
            --bg-body: #0f172a;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --border: #334155;
            
            /* Status Colors */
            --bg-up: #064e3b;      /* Dark Green */
            --bg-down: #7f1d1d;    /* Dark Red */
            --border-up: #059669;
            --border-down: #dc2626;
            --text-up: #ecfdf5;
            --text-down: #fef2f2;
        }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg-body);
            color: var(--text-main);
            margin: 0;
            padding: 2rem;
            min-height: 100vh;
        }}
        h1 {{ margin:0 0 6px 0; font-size:18px; }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1rem;
        }}
        .meta {{ color: var(--text-muted); font-size: 0.875rem; font-family: monospace; }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
            gap: 1rem;
            grid-auto-flow: row;
        }}
        
        .card {{
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            text-decoration: none;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            min-height: 80px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            cursor: pointer;
            overflow: hidden; /* Prevent spill */
        }}
        
        .card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 12px 20px -5px rgba(0, 0, 0, 0.3);
            filter: brightness(1.15);
            z-index: 10;
        }}

        /* Status Styles */
        .status-up {{
            background-color: var(--bg-up);
            border-color: var(--border-up);
            color: var(--text-up);
        }}
        
        .status-down {{
            background-color: var(--bg-down);
            border-color: var(--border-down);
            color: var(--text-down);
            animation: pulse 2s infinite;
        }}
        
        .site-name {{
            font-weight: 700;
            font-size: 1.1rem;
            line-height: 1.25;
            word-wrap: break-word; /* Ensure long words wrap */
            max-width: 100%;
        }}
        
        /* Sizes */
        .card-hero {{
            grid-column: span 2;
            min-height: 120px;
            font-size: 1.3em;
        }}
        
        .card-highlight {{
            min-height: 90px;
            /* Default column span is 1 */
        }}

        .card-small {{
            min-height: 60px;
            opacity: 0.9;
            font-size: 0.9em;
        }}
        
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
            100% {{ opacity: 1; }}
        }}

        @media (max-width: 640px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .card-hero {{ grid-column: span 1; }}
            body {{ padding: 1rem; }}
        }}
    </style>
</head>
<body>
    <h1>🛰️ Painel de Monitoramento</h1>
    <div class="meta">Última checagem: {generated_at} (a página recarrega a cada 5s)</div>
    <br>
    <div class="grid">
        {''.join(cards)}
    </div>
    <script>
        (function refreshNoCache(){{
            setTimeout(function(){{
                try {{
                    const url = new URL(window.location.href);
                    url.searchParams.set('_', Date.now());
                    window.location.replace(url.toString());
                }} catch (e) {{
                    // Fallback: simple reload
                    window.location.reload();
                }}
            }}, 5000);
        }})();
    </script>
</body>
</html>
"""

def main():
    print(f"Iniciando monitoramento de {len(SITES)} sites...")
    print(f"Modo: Headless Chrome (Selenium)")
    print(f"Paralelismo: {MAX_WORKERS} workers")
    print(f"Intervalo: {INTERVAL_SECONDS} segundos")
    print("-" * 50)

    # Start HTTP server in background thread so others on the LAN can access dashboard.html
    server_thread = threading.Thread(target=start_http_server, args=(SERVER_HOST, SERVER_PORT), daemon=True)
    server_thread.start()

    while True:
        try:
            start_check = time.time()
            rows = []
            
            # Split sites between fast checks and Selenium-required checks so slow Selenium
            # jobs don't occupy the main thread-pool slots needed for lightweight requests.
            selenium_sites = [s for s in SITES if s[1] in SELENIUM_REQUIRED]
            fast_sites = [s for s in SITES if s[1] not in SELENIUM_REQUIRED]

              # Executors
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as fast_executor, \
                  concurrent.futures.ThreadPoolExecutor(max_workers=SELENIUM_WORKERS) as selenium_executor:

                # submit fast checks
                fast_futures = {fast_executor.submit(fast_check, site): site for site in fast_sites}

                # submit selenium checks with overrides when present
                selenium_futures = {}
                for site in selenium_sites:
                    url = site[1]
                    overrides = SELENIUM_OVERRIDES.get(url, {})
                    selenium_futures[selenium_executor.submit(
                        selenium_check, site,
                        overrides.get('page_load_timeout'),
                        overrides.get('attempts'))] = site

                # process completed futures from both pools as they finish
                all_futures = list(fast_futures.keys()) + list(selenium_futures.keys())
                for future in concurrent.futures.as_completed(all_futures):
                    try:
                        result = future.result()
                        rows.append(result)
                        name, _, ok, _, ms, _ = result
                        status = "ONLINE" if ok else "OFFLINE"
                        print(f"Checked: {name:<20} -> {status} ({ms}ms)")
                    except Exception as exc:
                        print(f"Generated an exception: {exc}")

            generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            html = render_html(rows, generated_at)
            
            with open("dashboard.html", "w", encoding="utf-8") as f:
                f.write(html)

            elapsed = time.time() - start_check
            print(f"[{generated_at}] Ciclo completo em {elapsed:.2f}s. dashboard.html atualizado.")
            print("-" * 50)
            
            # Sleep logic
            time.sleep(INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            print("\nMonitoramento interrompido.")
            break
        except Exception as e:
            print(f"\nErro no loop principal: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
