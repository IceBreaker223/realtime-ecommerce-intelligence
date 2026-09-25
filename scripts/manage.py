"""Dependency-free host entry point. Requires Python 3.11+ and Docker Compose."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True)


def tool(*args):
    # Bind-mounted reports must remain writable by both the host and tools.
    (ROOT / "runtime").mkdir(parents=True, exist_ok=True)
    identity = ["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform.startswith("linux") else []
    compose("run", "--rm", "--no-deps", *identity, "tools", "python", *args)


def ready():
    port = api_port()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://localhost:{port}/health/ready", timeout=5) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    raise TimeoutError("API readiness timed out. Run docker compose logs spark api")


def api_port():
    config = json.loads(subprocess.check_output(["docker", "compose", "config", "--format", "json"], cwd=ROOT, text=True))
    return config["services"]["api"]["ports"][0]["published"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "demo", "check", "benchmark", "recovery", "stop"])
    args, extra = parser.parse_known_args()
    if args.command == "stop":
        compose("stop")
        return
    if args.command in ("start", "demo"):
        compose("config", "--quiet")
        compose("build", "spark", "api", "detector", "tools")
        compose("up", "-d")
    if args.command == "demo":
        tool("-m", "scripts.demo", *extra)
    elif args.command == "benchmark":
        raw = subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True)
        info = json.loads(raw)
        output = ROOT / "runtime/evidence/environment.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({key: info[key] for key in ("NCPU", "MemTotal", "OperatingSystem", "Architecture", "ServerVersion")}, indent=2))
        tool("-m", "scripts.benchmark", *extra)
    elif args.command == "recovery":
        compose("kill", "-s", "SIGKILL", "spark")
        try:
            tool("-m", "scripts.recovery", "queue")
        finally:
            began = time.perf_counter()
            compose("start", "spark")
        tool("-m", "scripts.recovery", "verify")
        report = ROOT / "runtime/evidence/recovery.json"
        data = json.loads(report.read_text())
        data["restart_command_to_verified_seconds"] = round(time.perf_counter() - began, 3)
        report.write_text(json.dumps(data, indent=2))
        tool("-m", "scripts.reconcile")
    elif args.command == "check":
        for folder in ("tests", "api/tests", "detection"):
            tool("-m", "unittest", "discover", "-s", folder, "-v")
        for test in ("test_analytics.py", "test_persistence.py"):
            compose("run", "--rm", "--no-deps", "spark", "/opt/spark/bin/spark-submit", f"/opt/spark-apps/{test}")
        tool("-m", "scripts.reconcile")
        tool("-m", "detection.evaluate")
        report = ROOT / "runtime/evidence/checks.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(dict(result="passed", completed_at=datetime.now(timezone.utc).isoformat(),
            groups=["unit", "api_postgres", "detector_postgres", "spark_analytics", "spark_postgres", "sql_reconciliation", "synthetic_evaluation"]), indent=2))
    if args.command in ("start", "demo"):
        if args.command == "demo":
            ready()
        print(f"Dashboard: http://localhost:{api_port()}/")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, TimeoutError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
