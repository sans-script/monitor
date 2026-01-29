import argparse
import concurrent.futures
import socket
import requests


def check_host(ip, port, conn_timeout, http_timeout):
    addr = (ip, port)
    try:
        with socket.create_connection(addr, timeout=conn_timeout):
            # Port is open — try HTTP fetch to confirm dashboard
            try:
                url = f"http://{ip}:{port}/dashboard.html"
                r = requests.get(url, timeout=http_timeout)
                text = r.text.lower()
                if "painel de monitoramento" in text or "sentinela" in text or "dashboard" in text:
                    return ip, True, True
                return ip, True, False
            except Exception:
                return ip, True, False
    except Exception:
        return ip, False, False


def main(prefix, port, workers, conn_timeout, http_timeout, start, end):
    ips = [f"{prefix}.{i}" for i in range(start, end + 1)]
    found = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_host, ip, port, conn_timeout, http_timeout): ip for ip in ips}
        for fut in concurrent.futures.as_completed(futures):
            ip = futures[fut]
            try:
                ip, open_port, is_dashboard = fut.result()
                if open_port:
                    marker = "DASHBOARD" if is_dashboard else "OPEN"
                    print(f"{ip}: {marker}")
                    found.append((ip, marker))
            except Exception as e:
                print(f"{ip}: error {e}")

    if not found:
        print("No hosts found with open port / dashboard detected.")
    else:
        print("\nSummary:")
        for ip, marker in found:
            print(f" - {ip}: {marker}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Discover dashboard hosts on local network (192.* scanner)")
    p.add_argument("--prefix", default="192.168.200", help="IP prefix to scan (e.g. 192.168.200)")
    p.add_argument("--port", type=int, default=8000, help="Port to test (default 8000)")
    p.add_argument("--workers", type=int, default=80, help="Parallel workers")
    p.add_argument("--conn-timeout", type=float, default=0.4, help="TCP connect timeout seconds")
    p.add_argument("--http-timeout", type=float, default=2.0, help="HTTP request timeout seconds")
    p.add_argument("--start", type=int, default=1, help="Start host number (inclusive)")
    p.add_argument("--end", type=int, default=254, help="End host number (inclusive)")
    args = p.parse_args()

    main(args.prefix, args.port, args.workers, args.conn_timeout, args.http_timeout, args.start, args.end)
