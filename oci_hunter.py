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
# AVAILABILITY_DOMAIN may list several comma-separated names; a single name still works.
ADS = [a.strip() for a in (os.getenv("AVAILABILITY_DOMAIN") or "").split(",") if a.strip()]
# Capacity is tracked per fault domain as well, so each attempt asks a different one.
# "auto" (or an empty entry) lets Oracle choose. Use API names (FAULT-DOMAIN-1), not the
# console's "FD-1" labels, which Oracle rejects with 400 InvalidParameter.
FAULT_DOMAINS = [
    None if f.strip().lower() in ("", "auto") else f.strip()
    for f in os.getenv("FAULT_DOMAINS", "auto,FAULT-DOMAIN-1,FAULT-DOMAIN-2,FAULT-DOMAIN-3").split(",")
]
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
UNKNOWN = object()  # check_existing() could not determine the answer

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
        if res.returncode != 0:
            log(f"Check existing failed (rc={res.returncode}): {(res.stderr or res.stdout)[:300]}")
            return UNKNOWN
        data = json.loads(res.stdout or "[]")
        return data[0] if data else None
    except Exception as e:
        log(f"Check existing error: {e}")
        return UNKNOWN

def verified_existing(tries=5, delay=30):
    """check_existing() with retries. Never guesses: if the check can't be completed,
    exit non-zero (systemd restarts us) instead of risking a duplicate launch."""
    for i in range(tries):
        result = check_existing()
        if result is not UNKNOWN:
            return result
        if i < tries - 1:
            log(f"Could not verify existing instances; retrying in {delay}s ({i + 1}/{tries})...")
            time.sleep(delay)
    log("Could not verify whether the instance already exists. Exiting instead of risking a duplicate launch.")
    sys.exit(1)

def valid_ssh_key(key):
    parts = (key or "").split()
    return (len(parts) >= 2
            and parts[0].startswith(("ssh-", "ecdsa-sha2-", "sk-"))
            and "..." not in key)

def attempt_launch(ad, fd=None):
    cmd = [
        OCI, "--no-retry", "compute", "instance", "launch",
        "--compartment-id", COMPARTMENT,
        "--availability-domain", ad,
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
    if fd:
        cmd += ["--fault-domain", fd]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "", "launch call timed out"
    return res.returncode, res.stdout or "", res.stderr or ""

def main():
    log("=== OCI Instance Hunter Started ===")
    if not COMPARTMENT or not ADS or not SUBNET or not IMAGE:
        log("ERROR: Missing required configuration variables. Check your .env file.")
        sys.exit(1)
    if not valid_ssh_key(SSH_KEY):
        log("ERROR: SSH_PUBLIC_KEY is missing, malformed or still the placeholder. An instance launched without a usable key can't be logged into.")
        sys.exit(1)

    existing = verified_existing()
    if existing:
        log(f"Instance '{NAME}' is already active: {existing['id']} ({existing['state']}). Stopping hunter.")
        return 0

    log(f"Rotating {len(ADS)} availability domain(s) x {len(FAULT_DOMAINS)} fault domain(s): "
        f"{', '.join(f or 'auto' for f in FAULT_DOMAINS)}")

    attempt_count = 0
    while True:
        idx = attempt_count
        attempt_count += 1
        # Cycle every fault domain within an AD, then advance to the next AD.
        fd = FAULT_DOMAINS[idx % len(FAULT_DOMAINS)]
        ad = ADS[(idx // len(FAULT_DOMAINS)) % len(ADS)]
        where = f"{ad} / {fd or 'auto'}"
        code, out, err = attempt_launch(ad, fd)
        if code is None:
            # The launch call timed out; it may still have gone through on Oracle's side.
            log(f"[#{attempt_count}] Launch call timed out ({where}). Checking whether it went through...")
            found = verified_existing()
            if found:
                code, out, err = 0, json.dumps(found), ""
            else:
                time.sleep(random.randint(POLL_MIN, POLL_MAX))
                continue
        combined = (out + " " + err).lower()

        if code == 0 and "ocid1.instance.oc1" in combined:
            log(f"SUCCESS! Instance successfully created on attempt #{attempt_count} ({where}).")
            try:
                data = json.loads(out)
                os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
                with open(STATE_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                log(f"Could not write state file {STATE_FILE}: {e}")

            notify_telegram(
                "🎉 <b>OCI INSTANCE SUCCESSFULLY LAUNCHED!</b>\n\n"
                f"⚙️ <b>Specs:</b> {OCPUS} OCPU / {MEMORY_GB} GB RAM\n"
                f"🏷️ <b>Name:</b> {NAME}\n"
                f"🔢 <b>Attempts:</b> #{attempt_count}\n\n"
                f"📍 <b>Placement:</b> {where}\n\n"
                "Check your OCI Console for Public IP details."
            )
            break

        elif "outofhostcapacity" in combined.replace(" ", "") or "out of capacity" in combined:
            sleep_sec = random.randint(POLL_MIN, POLL_MAX)
            if attempt_count % 15 == 1:
                log(f"[#{attempt_count}] Out of capacity ({where}). Retrying in {sleep_sec}s...")
            time.sleep(sleep_sec)

        elif "toomanyrequests" in combined.replace(" ", "") or "too many requests" in combined:
            log(f"[#{attempt_count}] Rate limit (TooManyRequests) hit. Cooling down for 3 minutes...")
            time.sleep(180)

        elif "already exists" in combined:
            log(f"Instance '{NAME}' already exists. Stopping hunter.")
            break

        else:
            log(f"[#{attempt_count}] Error ({where}): {err[:300] or out[:300]}")
            time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Hunter stopped by user.")
    except Exception as e:
        log(f"Fatal error: {e}")
        sys.exit(1)
