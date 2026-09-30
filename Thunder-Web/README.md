# ⚡ Thunder Trail - Account & Session Keep-Alive Hub

A dedicated 24/7 Web Application for Coca-Cola / Thums Up Thunder Trail promotion accounts.

---

## 🌟 Key Features

1. **24/7 Automatic Session Refresher (Keep-Alive)**:
   - Starts automatically on boot.
   - Wakes up every **3.5 hours** to refresh all connected accounts on the Coca-Cola server.
   - Preserves the 7-day token window indefinitely so your accounts never expire.
   - **START / STOP** toggle button directly from the web dashboard.

2. **Cookie Management**:
   - **Upload Cookies JSON**: Drag & drop or browse `.cookies_*.json` files.
   - **New OTP Login**: Log in any phone number directly via OTP from the web modal.

3. **Live Account Telemetry**:
   - Displays **Plays Remaining Today** (e.g. `🎯 5 / 5 Left Today`).
   - Displays **Username, Today's Best Score, and Leaderboard Rank**.
   - Displays **Token Expiry Countdown** (`3h 45m left` or `Expired`).
   - Action buttons: **Refresh Now** and **Delete Account**.

4. **Live Activity Console**:
   - Real-time event logs of token refreshes, logins, and keep-alive cycles.

---

## 🚀 How to Run Locally (On PC)

1. Open PowerShell in this directory:
   ```powershell
   cd Desktop\Thunder-Web
   & "C:\Users\VICKY\AppData\Local\Programs\Python\Python311\python.exe" app.py
   ```
2. Open your browser to: **`http://localhost:5000`**

---

## 🌐 How to Deploy to Render (24/7 Free Cloud)

### Method 1: Deploy via GitHub (Recommended)
1. Create a new GitHub repository (e.g., `thunder-session-hub`).
2. Push the files in this folder to your GitHub repo.
3. Log in to [Render.com](https://render.com).
4. Click **New +** $\rightarrow$ **Web Service**.
5. Connect your GitHub repository.
6. Render will automatically detect `requirements.txt` and `Procfile`:
   - **Environment**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`
7. Click **Create Web Service**. Your app will be live 24/7!
