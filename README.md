# PowerBI-Kiosk-Workaround-auto-login-update-etc-
A robust Python script to keep Power BI dashboards active on unattended kiosk screens. It automates Microsoft AAD login flows, handles iframes, closes blank pop-ups, and includes a self-healing mechanism to recover from crashes and clean zombie processes automatically.


This project is a Python-based automation script designed to keep Power BI dashboards active on unattended kiosk screens without making the dashboards public. It was originally developed to solve a specific in-house problem at the time, bypassing standard session timeouts and automatically handling the Microsoft Azure Active Directory (AAD) login flow.

⚠️ Important Limitations & Known Issues
Before using this script, please be aware of the following hard constraints:

**No MFA Support: This script will not work if Multi-Factor Authentication (MFA) or conditional access prompts (like authenticator app approvals) are enabled. It strictly requires a simple, direct username and password login flow.**

Fragile Microsoft UI Elements: The automation relies on specific HTML elements on the Microsoft AAD login page. The primary confirmation button (Next / Sign in / Yes) is currently hardcoded as MS_PRIMARY_BTN_ID = "idSIButton9".

_Note: Microsoft can change this ID at any time. If the ID is changed, the script will not be able to click "Next" or "Sign in". It will get stuck in the AAD flow, the 120-second timeout will trigger, and the script will repeatedly close and reopen the flow or restart the driver without successfully logging in. If the script stops working suddenly, inspect the Microsoft login page and update this ID variable in the script._

**Features**

Smart AAD Flow Handling: Automates email entry, password entry, and SSO consent screens while utilizing an "anti-flicker" policy to prevent multiple popup windows from spawning simultaneously. 

Iframe Watchdog: Scans up to 3 levels deep into iframes to find and click the Power BI "Sign in" button using injected JavaScript.  

Self-Healing & Cleanup: Detects dead WebDriver connections (e.g., WinError 10061) and automatically kills zombie msedge.exe and msedgedriver.exe processes before fully restarting the script.  

Tab Management: Automatically detects and closes empty popups (about:blank) or unwanted Microsoft Yammer tabs to prevent browser crashes from tab explosion.

**Prerequisites** ✍️

- Microsoft Edge: Must be installed on the host machine. 
- Python: Python 3 must be installed and added to the system PATH. 

**Setup & Installation** 💽

1. Run the provided batch script as Administrator to install the required Python packages (selenium>=4.0.0 and webdriver-manager>=4.0.0): **setup.bat**   | MAKE SURE YOU DOWNLOADED REQUIREMENTS.TXT
2. Configure the Target URL: Edit the config.json file to point to your local HTML wrapper or dashboard link.
3. Set the Password Environment Variable: To avoid storing passwords in plain text, open the Command Prompt and set your kiosk password using **setx PBI_KIOSK_PASSWORD "your_actual_password_here"**

**Usage**
Once configured, simply execute the main script: python auto_signIn_kiosk_v2.8.py (or wtv you want to name it)

**License**
This project is open-source and licensed under the GNU GPLv3 License.

**Commercial Use**

If you intend to integrate this script into a closed-source project or require a license without the strict open-source distribution requirements of GPLv3, please contact me directly to arrange a commercial license, but I highly doubt anyone wants this cr@p.
