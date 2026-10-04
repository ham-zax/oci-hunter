# 🎯 OCI Hunter - Oracle Cloud Always Free Instance Hunter

An automated Python daemon that retries provisioning an ARM Ampere `VM.Standard.A1.Flex` instance in your OCI home region. This is a fork of [x12zl/oci-hunter](https://github.com/x12zl/oci-hunter).

---

## ✨ Key Features

- **Automated Retry Loop**: Safely retries instance creation every 45-60 seconds.
- **Rate-Limit Safe**: Automatic 3-minute backoff cooldown when hitting OCI `TooManyRequests (429)` limits.
- **Auto-Stop**: Checks for a matching non-terminated instance on startup and exits after successful launch. Failed existence checks stop provisioning. Account-wide free-tier/billing limits are not enforced.
- **Placement Rotation**: Rotates configured availability domains and fault domains.
- **Telegram Notifications**: Real-time alert delivered directly to your Telegram chat/thread when the instance is successfully created.
- **Systemd Integration**: Runs as a background system service on Linux (Ubuntu/Debian) with auto-restart capability.

---

## 🛠️ Prerequisites

1. An active **Oracle Cloud Infrastructure (OCI)** Account.
2. OCI CLI installed & configured (`~/.oci/config` + `.pem` key).
3. A Public Subnet & VCN created in your OCI Home Region.
4. Python 3.8+

---

## 🚀 Quick Setup & Installation

### 1. Clone Repository
```bash
git clone https://github.com/ham-zax/oci-hunter.git
cd oci-hunter
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your OCI & Telegram credentials:
```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Use a real ARM-compatible image and a complete SSH public key. Leave Telegram settings empty if notifications are not needed. `.env` and private keys must never be committed.

### 3. Setup Virtual Environment & Install OCI CLI
```bash
python3 -m venv /opt/oci-venv
/opt/oci-venv/bin/pip install oci-cli requests
```

This layout requires permission to write under `/opt`. Alternatively, create a user-owned virtual environment and set `OCI_CLI_PATH` in `.env` to its `bin/oci` path.

### 4. Configure, Install & Start Systemd Service
The supplied unit expects the repository at `/opt/oci-hunter` and runs as `root`. Before installing it, set `User`, `WorkingDirectory`, and `ExecStart` to the actual deployment user and absolute paths. Configure OCI authentication for that service user; its home directory determines `~/.oci/config` and the saved launch-state location. For a non-root user, set a writable `LOG_FILE` in `.env` and use `StandardOutput=journal` / `StandardError=journal` in the unit.

Only start after reviewing the target account and resource allowance. The service creates an instance when capacity is available.
```bash
sudo cp oci-hunter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oci-hunter.service
```

---

## 📊 View Logs

To monitor the live status of your hunter daemon:
```bash
sudo tail -f /var/log/oci_hunter.log
```

Or use `sudo journalctl -u oci-hunter.service -f`. After success, the service exits normally (`Restart=on-failure`). Disable it when provisioning is complete:

```bash
sudo systemctl disable --now oci-hunter.service
```

Disabling the hunter leaves the created instance running.

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
