import http.server
import socketserver
import subprocess
import json
import threading
import time
import re
import sys
import io

# Fix Windows cp1252 crash when printing Devanagari/Hindi characters.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf-8-sig'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PORT = 8000
scrape_status = {
    "status": "idle",
    "last_run": None,
    "message": "",
    "error": None,
    "progress": None
}
scrape_lock = threading.Lock()

# Regex to capture progress from scraper stdout
info_re = re.compile(r'\[INFO\]\s+([^:]+):\s+Found\s+\d+\s+jobs')
error_re = re.compile(r'\[ERROR\]\s+Failed\s+to\s+scrape\s+([^:]+):')

def run_scraper_background():
    global scrape_status
    with scrape_lock:
        scrape_status["status"] = "running"
        scrape_status["message"] = "Scraping in progress..."
        scrape_status["progress"] = {"current": "Initializing...", "done": 0, "total": 36}
        scrape_status["error"] = None

    try:
        print("\n[INFO] Scraper run started...")
        process = subprocess.Popen(
            ["python", "-u", "scraper.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )

        # Read output line by line and update progress in real time
        for line in iter(process.stdout.readline, ''):
            print(line, end='', flush=True)

            # Check for current scraping task start messages
            if "Scraping KVS..." in line:
                with scrape_lock:
                    if scrape_status["progress"]:
                        scrape_status["progress"]["current"] = "KVS"
            elif "Scraping NVS..." in line:
                with scrape_lock:
                    if scrape_status["progress"]:
                        scrape_status["progress"]["current"] = "NVS"
            elif "Scraping EMRS..." in line:
                with scrape_lock:
                    if scrape_status["progress"]:
                        scrape_status["progress"]["current"] = "EMRS"

            # Check for finished sources (district/central)
            info_match = info_re.search(line)
            error_match = error_re.search(line)

            source_name = None
            if info_match:
                source_name = info_match.group(1).strip()
            elif error_match:
                source_name = error_match.group(1).strip()

            if source_name and source_name not in ("Starting parallel state scrape", "Starting parallel central scrape", "Starting parallel central scrape..."):
                with scrape_lock:
                    if scrape_status["progress"]:
                        scrape_status["progress"]["done"] = min(scrape_status["progress"]["done"] + 1, 36)
                        scrape_status["progress"]["current"] = source_name

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, ["python", "scraper.py"])

        with scrape_lock:
            scrape_status["status"] = "idle"
            scrape_status["last_run"] = time.time()
            scrape_status["message"] = "Success"
            scrape_status["progress"] = {"current": "Done", "done": 36, "total": 36}
        print("[INFO] Scrape completed successfully.")
    except subprocess.CalledProcessError as e:
        with scrape_lock:
            scrape_status["status"] = "error"
            scrape_status["message"] = f"Error: Scrape script failed with exit code {e.returncode}"
            scrape_status["error"] = True
            scrape_status["progress"] = None
        print(f"[ERROR] Scrape failed with exit code {e.returncode}")
    except Exception as e:
        with scrape_lock:
            scrape_status["status"] = "error"
            scrape_status["message"] = f"Error: {str(e)}"
            scrape_status["error"] = True
            scrape_status["progress"] = None
        print(f"[ERROR] Scrape exception: {e}")

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-type')
        super().end_headers()
        
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/api/refresh/status'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            with scrape_lock:
                self.wfile.write(json.dumps(scrape_status).encode())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/refresh'):
            try:
                with scrape_lock:
                    is_running = scrape_status["status"] == "running"
                if not is_running:
                    threading.Thread(target=run_scraper_background, daemon=True).start()
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def start_scheduler():
    def scheduler_loop():
        # Interval is 6 hours
        interval = 6 * 60 * 60
        while True:
            time.sleep(interval)
            print("\n[INFO] Scheduled auto-refresh triggered (every 6 hours).")
            with scrape_lock:
                is_running = scrape_status["status"] == "running"
            if not is_running:
                threading.Thread(target=run_scraper_background, daemon=True).start()
                
    threading.Thread(target=scheduler_loop, daemon=True).start()

if __name__ == "__main__":
    start_scheduler()
    with http.server.ThreadingHTTPServer(("", PORT), CustomHandler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        print("Use Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

