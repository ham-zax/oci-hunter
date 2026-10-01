# 🎯 OCI Hunter - Oracle Cloud Always Free Instance Hunter

An automated, lightweight, and rate-limit safe daemon written in Python to continuously hunt and provision **OCI Always Free Compute Instances** (ARM Ampere `VM.Standard.A1.Flex` or AMD Micro `VM.Standard.E2.1.Micro`).

---

## ✨ Key Features

- **Automated Retry Loop**: Safely retries instance creation every 45-60 seconds.
- **Rate-Limit Safe**: Automatic 3-minute backoff cooldown when hitting OCI `TooManyRequests (429)` limits.
- **Safety Auto-Stop**: Checks existing instances on startup and automatically terminates execution immediately upon successful launch (prevents duplicate creations/overlimit charges).
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
git clone https://github.com/x12zl/oci-hunter.git
cd oci-hunter
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your OCI & Telegram credentials:
```bash
cp .env.example .env
nano .env
```

### 3. Setup Virtual Environment & Install OCI CLI
```bash
python3 -m venv /opt/oci-venv
/opt/oci-venv/bin/pip install oci-cli requests
```

### 4. Install & Start Systemd Service
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

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
