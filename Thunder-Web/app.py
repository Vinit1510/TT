"""
Thunder Trail - Account & Session Keep-Alive Hub
Web server for Render deployment with:
- Cookies JSON upload & Direct OTP login
- Live Plays Remaining, Username, and Token Expiry Telemetry
- Start / Stop Auto-Refresh Keep-Alive Mode (Every 3.5 Hours)
- Multi-Account Dashboard with One-Click Actions
"""
import os
import sys
import glob
import json
import time
import base64
import random
import logging
import datetime
import threading
import requests
from typing import Optional, Dict, Any, List
from flask import Flask, render_template, request, jsonify, redirect, url_for

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE_DIR = os.path.join(HERE, "cookies")
os.makedirs(COOKIE_DIR, exist_ok=True)

BASE_URL = "https://thunder-zone.coke2home.com"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/game?skipWin=1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
}

# In-memory log buffer
activity_logs: List[Dict[str, Any]] = []


def add_log(message: str, level: str = "info"):
    entry = {
        "timestamp": datetime.datetime.now().strftime("%I:%M:%S %p"),
        "message": message,
        "level": level
    }
    activity_logs.append(entry)
    if len(activity_logs) > 100:
        activity_logs.pop(0)


# ==============================================================================
# Auto Keep-Alive Background Worker
# ==============================================================================
class AutoRefresherDaemon:
    def __init__(self, interval_hours: float = 3.5):
        self.interval_seconds = interval_hours * 3600
        self.is_running = True  # Default to ON
        self.thread: Optional[threading.Thread] = None
        self.last_run: Optional[str] = None
        self.next_run_epoch: float = time.time() + self.interval_seconds
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if not self.is_running or self.thread is None or not self.thread.is_alive():
                self.is_running = True
                self.next_run_epoch = time.time() + self.interval_seconds
                self.thread = threading.Thread(target=self._run_loop, daemon=True)
                self.thread.start()
                add_log("🟢 Auto Keep-Alive Mode STARTED (Refreshes every 3.5 hours)", "success")

    def stop(self):
        with self.lock:
            self.is_running = False
            add_log("🔴 Auto Keep-Alive Mode STOPPED", "warning")

    def _run_loop(self):
        add_log("⚡ Auto Refresher daemon initialized and active in background.", "info")
        while self.is_running:
            time.sleep(10)
            if not self.is_running:
                break
            if time.time() >= self.next_run_epoch:
                self.execute_refresh_all()
                self.next_run_epoch = time.time() + self.interval_seconds

    def execute_refresh_all(self):
        self.last_run = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        add_log("🔄 [AUTO-REFRESH] Starting scheduled refresh cycle for all accounts...", "info")
        accounts = scan_all_accounts()
        success_cnt = 0
        for acc in accounts:
            phone = acc["phone"]
            ok, msg = refresh_account_token(phone)
            if ok:
                success_cnt += 1
                add_log(f"✅ [AUTO-REFRESH] +91 {phone}: {msg}", "success")
            else:
                add_log(f"⚠️ [AUTO-REFRESH] +91 {phone}: {msg}", "error")
        add_log(f"🎉 [AUTO-REFRESH] Cycle complete! {success_cnt}/{len(accounts)} accounts active.", "success")


auto_daemon = AutoRefresherDaemon(interval_hours=3.5)


# ==============================================================================
# Helper Functions & Coke2Home API
# ==============================================================================
def decode_jwt_exp(token: str) -> Dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            padding = 4 - (len(parts[1]) % 4)
            payload_b64 = parts[1] + ("=" * padding)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
            exp_ts = payload.get("exp")
            if exp_ts:
                exp_dt = datetime.datetime.fromtimestamp(exp_ts, datetime.timezone.utc).astimezone()
                now_dt = datetime.datetime.now(datetime.timezone.utc).astimezone()
                remaining_sec = int((exp_dt - now_dt).total_seconds())
                is_expired = remaining_sec <= 0
                
                hours = max(0, remaining_sec // 3600)
                mins = max(0, (remaining_sec % 3600) // 60)
                
                return {
                    "expiry_str": exp_dt.strftime("%I:%M:%S %p"),
                    "is_expired": is_expired,
                    "remaining_sec": remaining_sec,
                    "time_left": f"{hours}h {mins}m left" if not is_expired else "Expired"
                }
    except Exception:
        pass
    return {"expiry_str": "Unknown", "is_expired": True, "remaining_sec": 0, "time_left": "Expired"}


def get_cookie_file(phone: str) -> str:
    candidates = [
        os.path.join(COOKIE_DIR, f".cookies_{phone}.json"),
        os.path.join(COOKIE_DIR, f"cookies_{phone}.json"),
        os.path.join(HERE, f".cookies_{phone}.json"),
        os.path.join(HERE, f"cookies_{phone}.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_session_from_file(cookie_file: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    if os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                c_data = json.load(f)
            for c in c_data:
                sess.cookies.set(c["name"], c["value"])
        except Exception:
            pass
    return sess


def save_session_to_file(sess: requests.Session, cookie_file: str):
    os.makedirs(os.path.dirname(os.path.abspath(cookie_file)), exist_ok=True)
    c_dict = {c.name: c.value for c in sess.cookies}
    c_list = [{"name": k, "value": v} for k, v in c_dict.items()]
    with open(cookie_file, "w", encoding="utf-8") as f:
        json.dump(c_list, f, indent=2)


def fetch_account_telemetry(phone: str) -> Dict[str, Any]:
    c_file = get_cookie_file(phone)
    if not os.path.exists(c_file):
        return {"phone": phone, "status": "No File", "plays_remaining": 0, "best_score": 0, "rank": None}

    sess = load_session_from_file(c_file)
    
    # Check expiry from access token
    access_token = sess.cookies.get("access_token", "")
    exp_meta = decode_jwt_exp(access_token)

    username = "User"
    plays_remaining = 0
    best_score = 0
    rank = None
    is_blocked = False
    is_authenticated = False

    try:
        r_me = sess.get(f"{BASE_URL}/api/thunder-trail/me", timeout=8)
        if r_me.status_code == 200:
            d = r_me.json().get("data", {})
            username = d.get("username") or username
            plays_remaining = d.get("plays_remaining", 0)
            best_score = d.get("best_score", 0)
            rank = d.get("rank")
            is_blocked = d.get("is_blocked", False)
            is_authenticated = True
    except Exception:
        pass

    return {
        "phone": phone,
        "username": username,
        "file_name": os.path.basename(c_file),
        "is_authenticated": is_authenticated,
        "is_expired": exp_meta["is_expired"],
        "expiry_str": exp_meta["expiry_str"],
        "time_left": exp_meta["time_left"],
        "remaining_sec": exp_meta["remaining_sec"],
        "plays_remaining": plays_remaining,
        "best_score": best_score,
        "rank": f"#{rank}" if rank else "Unranked",
        "is_blocked": is_blocked
    }


def scan_all_accounts() -> List[Dict[str, Any]]:
    seen = {}
    search_dirs = [COOKIE_DIR, HERE]
    for d in search_dirs:
        for f in glob.glob(os.path.join(d, "*cookies_*.json")):
            digits = "".join(c for c in os.path.basename(f) if c.isdigit())
            if len(digits) >= 10:
                phone = digits[-10:]
                if phone not in seen:
                    seen[phone] = fetch_account_telemetry(phone)
    return [seen[p] for p in sorted(seen.keys())]


def refresh_account_token(phone: str) -> (bool, str):
    c_file = get_cookie_file(phone)
    if not os.path.exists(c_file):
        return False, "Cookie file missing"

    sess = load_session_from_file(c_file)
    try:
        r = sess.post(f"{BASE_URL}/api/auth/refresh", json={}, timeout=10)
        if r.status_code in (200, 201) and r.json().get("success"):
            save_session_to_file(sess, c_file)
            new_acc = sess.cookies.get("access_token", "")
            exp_info = decode_jwt_exp(new_acc)
            return True, f"Token extended! {exp_info.get('time_left')}"
        else:
            return False, f"Refresh failed: {r.status_code} ({r.text[:80]})"
    except Exception as e:
        return False, f"Network error: {str(e)}"


# ==============================================================================
# Web Routes & API Endpoints
# ==============================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/accounts", methods=["GET"])
def api_get_accounts():
    accounts = scan_all_accounts()
    next_sec = max(0, int(auto_daemon.next_run_epoch - time.time())) if auto_daemon.is_running else 0
    hrs = next_sec // 3600
    mins = (next_sec % 3600) // 60
    secs = next_sec % 60
    
    return jsonify({
        "success": True,
        "accounts": accounts,
        "auto_mode": {
            "is_running": auto_daemon.is_running,
            "interval_hours": 3.5,
            "last_run": auto_daemon.last_run or "Pending First Cycle",
            "next_run_sec": next_sec,
            "next_run_str": f"{hrs:02d}:{mins:02d}:{secs:02d}" if auto_daemon.is_running else "Paused"
        },
        "logs": activity_logs[-20:]
    })


@app.route("/api/auto/start", methods=["POST"])
def api_auto_start():
    auto_daemon.start()
    return jsonify({"success": True, "is_running": True, "message": "Auto Keep-Alive Started!"})


@app.route("/api/auto/stop", methods=["POST"])
def api_auto_stop():
    auto_daemon.stop()
    return jsonify({"success": True, "is_running": False, "message": "Auto Keep-Alive Stopped!"})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    data = request.get_json() or {}
    phone = data.get("phone")
    if phone:
        ok, msg = refresh_account_token(phone)
        lvl = "success" if ok else "error"
        add_log(f"🔄 Manual Refresh +91 {phone}: {msg}", lvl)
        return jsonify({"success": ok, "message": msg})
    else:
        # Refresh all
        accounts = scan_all_accounts()
        results = []
        for acc in accounts:
            ok, msg = refresh_account_token(acc["phone"])
            results.append({"phone": acc["phone"], "success": ok, "message": msg})
        add_log(f"🔄 Manual Bulk Refresh completed for {len(accounts)} accounts.", "info")
        return jsonify({"success": True, "results": results})


@app.route("/api/auth/send-otp", methods=["POST"])
def api_send_otp():
    data = request.get_json() or {}
    phone = "".join(c for c in data.get("phone", "") if c.isdigit())[-10:]
    if len(phone) != 10:
        return jsonify({"success": False, "error": "Please enter a valid 10-digit mobile number."}), 400

    try:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        r = sess.post(f"{BASE_URL}/api/auth/send-otp", json={"phone_number": phone}, timeout=10)
        if r.status_code == 200:
            add_log(f"📲 OTP requested for +91 {phone}", "info")
            return jsonify({"success": True, "message": "OTP sent successfully to your mobile!"})
        else:
            return jsonify({"success": False, "error": f"Failed to send OTP: {r.status_code} {r.text}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Network error: {str(e)}"}), 500


@app.route("/api/auth/verify-otp", methods=["POST"])
def api_verify_otp():
    data = request.get_json() or {}
    phone = "".join(c for c in data.get("phone", "") if c.isdigit())[-10:]
    otp = str(data.get("otp", "")).strip()

    if len(phone) != 10 or len(otp) < 4:
        return jsonify({"success": False, "error": "Invalid phone number or OTP."}), 400

    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        # 1. Verify OTP
        r_ver = sess.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone_number": phone, "otp": otp}, timeout=10)
        if r_ver.status_code != 200:
            return jsonify({"success": False, "error": f"OTP verification failed: {r_ver.text}"}), 400

        v_data = r_ver.json()
        ott = v_data.get("one_time_token")
        if not ott:
            return jsonify({"success": False, "error": "Server did not return one-time-token."}), 400

        # 2. Validate token
        r_val = sess.post(f"{BASE_URL}/api/auth/validate-token", json={"one_time_token": ott}, timeout=10)
        # 3. Token exchange
        r_ex = sess.post(f"{BASE_URL}/api/auth/token-exchange", json={"one_time_token": ott}, timeout=10)
        if r_ex.status_code != 200:
            return jsonify({"success": False, "error": f"Token exchange failed: {r_ex.text}"}), 400

        # Complete tutorials
        for p in ("/api/thunder-trail/tutorial-complete", "/api/thunder-trail/coach-mark-seen"):
            try:
                sess.post(f"{BASE_URL}{p}", json={}, timeout=5)
            except Exception:
                pass

        # Save cookies
        cookie_file = os.path.join(COOKIE_DIR, f".cookies_{phone}.json")
        save_session_to_file(sess, cookie_file)

        add_log(f"🎉 New account +91 {phone} logged in & saved successfully!", "success")
        return jsonify({"success": True, "message": f"Logged in successfully as +91 {phone}!"})

    except Exception as e:
        return jsonify({"success": False, "error": f"Error during verification: {str(e)}"}), 500


@app.route("/api/cookies/upload", methods=["POST"])
def api_upload_cookies():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    try:
        content = file.read().decode("utf-8")
        cookie_json = json.loads(content)
        
        # Extract phone from token if possible
        phone = ""
        for c in cookie_json:
            if c.get("name") == "access_token":
                parts = c.get("value", "").split(".")
                if len(parts) >= 2:
                    padding = 4 - (len(parts[1]) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(parts[1] + ("=" * padding)).decode("utf-8"))
                    phone = payload.get("phone") or payload.get("phone_number") or ""
                break

        if not phone:
            digits = "".join(c for c in file.filename if c.isdigit())
            if len(digits) >= 10:
                phone = digits[-10:]

        if not phone:
            return jsonify({"success": False, "error": "Could not detect mobile number from cookie or filename."}), 400

        target_file = os.path.join(COOKIE_DIR, f".cookies_{phone}.json")
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(cookie_json, f, indent=2)

        add_log(f"📁 Cookies JSON uploaded for +91 {phone}", "success")
        return jsonify({"success": True, "phone": phone, "message": f"Cookies saved for +91 {phone}!"})

    except Exception as e:
        return jsonify({"success": False, "error": f"Invalid JSON cookie format: {str(e)}"}), 400


@app.route("/api/cookies/delete", methods=["POST"])
def api_delete_account():
    data = request.get_json() or {}
    phone = data.get("phone", "")
    if not phone:
        return jsonify({"success": False, "error": "Phone required."}), 400

    deleted = False
    for f in (
        os.path.join(COOKIE_DIR, f".cookies_{phone}.json"),
        os.path.join(COOKIE_DIR, f"cookies_{phone}.json"),
        os.path.join(HERE, f".cookies_{phone}.json"),
        os.path.join(HERE, f"cookies_{phone}.json")
    ):
        if os.path.exists(f):
            try:
                os.remove(f)
                deleted = True
            except Exception:
                pass

    if deleted:
        add_log(f"🗑️ Account +91 {phone} removed.", "warning")
        return jsonify({"success": True, "message": f"Account +91 {phone} removed."})
    return jsonify({"success": False, "error": "Account file not found."}), 404


# Start background auto-refresher immediately on server boot
auto_daemon.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
