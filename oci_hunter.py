#!/usr/bin/env python3
"""
OCI Always Free Instance Hunter Daemon.
Continuously attempts to launch OCI Compute instances (ARM/AMD)
with rate-limit backoff and automatic safety auto-stop once launched.
"""
import os
import sys
import time
import json
import random
import subprocess
from datetime import datetime

# Load configuration from environment or .env file
def load_env():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

OCI = os.getenv("OCI_CLI_PATH", "/opt/oci-venv/bin/oci")
COMPARTMENT = os.getenv("COMPARTMENT_ID")
AD = os.getenv("AVAILABILITY_DOMAIN")
SUBNET = os.getenv("SUBNET_ID")
IMAGE = os.getenv("IMAGE_ID")
SHAPE = os.getenv("SHAPE", "VM.Standard.A1.Flex")
OCPUS = os.getenv("OCPUS", "2")
MEMORY_GB = os.getenv("MEMORY_GB", "12")
BOOT_VOL_GB = os.getenv("BOOT_VOL_GB", "50")
NAME = os.getenv("INSTANCE_NAME", "my-oci-instance")
SSH_KEY = os.getenv("SSH_PUBLIC_KEY")

POLL_MIN = int(os.getenv("POLL_INTERVAL_MIN", "45"))
POLL_MAX = int(os.getenv("POLL_INTERVAL_MAX", "60"))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TG_THREAD_ID = os.getenv("TELEGRAM_THREAD_ID")

LOG_FILE = os.getenv("LOG_FILE", "/var/log/oci_hunter.log")
STATE_FILE = os.path.expanduser("~/.oci/launched_instance.json")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def notify_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}
        if TG_THREAD_ID:
            payload["message_thread_id"] = TG_THREAD_ID
        requests.post(url, json=payload, timeout=15)
        log("Telegram notification sent.")
    except Exception as e:
        log(f"Failed to send Telegram notification: {e}")

def check_existing():
    try:
        cmd = [
            OCI, "compute", "instance", "list",
            "--compartment-id", COMPARTMENT,
            "--display-name", NAME,
            "--query", "data[?\"lifecycle-state\"!='TERMINATED'].{id:id,state:\"lifecycle-state\"}",
            "--output", "json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(res.stdout or "[]")
        return data[0] if data else None
    except Exception as e:
        log(f"Check existing error: {e}")
        return None

def attempt_launch():
    cmd = [
        OCI, "--no-retry", "compute", "instance", "launch",
        "--compartment-id", COMPARTMENT,
        "--availability-domain", AD,
        "--shape", SHAPE,
        "--shape-config", f'{{"ocpus":{OCPUS},"memoryInGBs":{MEMORY_GB}}}',
        "--image-id", IMAGE,
        "--subnet-id", SUBNET,
        "--assign-public-ip", "true",
        "--metadata", json.dumps({"ssh_authorized_keys": SSH_KEY}),
        "--boot-volume-size-in-gbs", BOOT_VOL_GB,
        "--display-name", NAME,
        "--output", "json"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return res.returncode, res.stdout or "", res.stderr or ""

def main():
    log("=== OCI Instance Hunter Started ===")
    if not COMPARTMENT or not AD or not SUBNET or not IMAGE:
        log("ERROR: Missing required configuration variables. Check your .env file.")
        sys.exit(1)

    existing = check_existing()
    if existing:
        log(f"Instance '{NAME}' is already active: {existing['id']} ({existing['state']}). Stopping hunter.")
        return 0

    attempt_count = 0
    while True:
        attempt_count += 1
        code, out, err = attempt_launch()
        combined = (out + " " + err).lower()

        if code == 0 and "ocid1.instance.oc1" in combined:
            log(f"SUCCESS! Instance successfully created on attempt #{attempt_count}.")
            try:
                data = json.loads(out)
                with open(STATE_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

            notify_telegram(
                "🎉 <b>OCI INSTANCE SUCCESSFULLY LAUNCHED!</b>\n\n"
                f"⚙️ <b>Specs:</b> {OCPUS} OCPU / {MEMORY_GB} GB RAM\n"
                f"🏷️ <b>Name:</b> {NAME}\n"
                f"🔢 <b>Attempts:</b> #{attempt_count}\n\n"
                "Check your OCI Console for Public IP details."
            )
            break

        elif "outofhostcapacity" in combined.replace(" ", "") or "out of capacity" in combined:
            sleep_sec = random.randint(POLL_MIN, POLL_MAX)
            if attempt_count % 15 == 1:
                log(f"[#{attempt_count}] Out of capacity. Retrying in {sleep_sec}s...")
            time.sleep(sleep_sec)

        elif "toomanyrequests" in combined.replace(" ", "") or "too many requests" in combined:
            log(f"[#{attempt_count}] Rate limit (TooManyRequests) hit. Cooling down for 3 minutes...")
            time.sleep(180)

        elif "already exists" in combined:
            log(f"Instance '{NAME}' already exists. Stopping hunter.")
            break

        else:
            log(f"[#{attempt_count}] Error: {err[:300] or out[:300]}")
            time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Hunter stopped by user.")
    except Exception as e:
        log(f"Fatal error: {e}")
