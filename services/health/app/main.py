"""Aggregated health check service."""

import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

SERVICES = {
    "kreditkarten": "http://kreditkarten:5000/health",
}


def check_service(name: str, url: str) -> dict:
    """Check health of a single service."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return {"name": name, "status": "healthy", "details": data}
    except Exception as e:
        return {"name": name, "status": "unhealthy", "error": str(e)}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            results = [check_service(name, url) for name, url in SERVICES.items()]
            all_healthy = all(r["status"] == "healthy" for r in results)

            response = {
                "status": "healthy" if all_healthy else "degraded",
                "services": results,
            }

            self.send_response(200 if all_healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    print("Health check service running on port 8080")
    server.serve_forever()
