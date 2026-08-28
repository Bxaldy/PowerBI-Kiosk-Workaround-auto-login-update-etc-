import os
import time
import subprocess
import logging
import sys
import json
from logging.handlers import RotatingFileHandler

from pathlib import Path

# ===================== DEPENDENCIES CHECK =====================
# Ensure required packages are installed before importing them
def ensure_dependencies():
    """Install missing dependencies using python -m pip install"""
    required_packages = {
        'selenium': 'selenium>=4.0.0',
        'webdriver_manager': 'webdriver-manager>=4.0.0'
    }
    
    for module_name, pip_package in required_packages.items():
        try:
            __import__(module_name)
        except ImportError:
            print(f"[BOOTSTRAP] Installing {pip_package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pip_package])
                print(f"[BOOTSTRAP] {pip_package} installed successfully")
            except Exception as e:
                print(f"[BOOTSTRAP] ERROR: Failed to install {pip_package}: {e}")
                print(f"[BOOTSTRAP] Try installing manually: python -m pip install {pip_package}")
                sys.exit(1)

ensure_dependencies()

# Now safe to import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    WebDriverException,
    ElementNotInteractableException, ElementClickInterceptedException
)

# =====================Gabriel Buicu Noiembrie 2025 + copilot :) =====================
# ===================== CONFIG =====================
SCRIPT_VERSION = "2.8.0 - 07/05/2026"

# Load HTML path from config file
CONFIG_FILE = Path(__file__).parent / "config.json"
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        URL_PATH = Path(config.get("html_file_path", r"C:\Users\your_path_to.html"))
else:
    # Fallback to default if config file doesn't exist
    URL_PATH = Path(r"C:\Users\your_path_to.html")

URL_DASHBOARD = URL_PATH.as_uri()

USER_EMAIL = "powerbi_email@example.com"
#PASSWORD = "PASSWORD" # use only for local tests or where there are no access rights to set environment variables
PASSWORD = os.environ.get("PBI_KIOSK_PASSWORD")  # cmd -> setx PBI_KIOSK_PASSWORD "password"

SCAN_INTERVAL_SECONDS = 2.5
PBI_SIGNIN_COOLDOWN   = 5.0
TILE_COOLDOWN         = 3.0
MAX_TILE_CLICKS_PER_VISIT = 3
IFRAME_MAX_DEPTH      = 3

MS_PRIMARY_BTN_ID = "idSIButton9"  # Next / Sign in / Yes / Continue

#ATTENTION THIS BUTTON ID MIGHT CHANGE IN THE FUTURE AND SHOULD BE UPDATED WHEN THAT'S GONNA HAPPEN

# Popup blank (about:blank) handling
BLANK_POPUP_WAIT_SECONDS = 10.0
BLANK_POPUP_COOLDOWN     = 20.0

# Heartbeat logging
HEARTBEAT_SECONDS = 60.0

# Safety: tab cap (anti "tab explosion")
MAX_TABS_SAFETY = 15

# === Anti-flicker / AAD popup policy ===
# 1) how long we consider AAD authentication to be "in progress"
AAD_FLOW_ACTIVE_TIMEOUT = 120.0

# 2) while AAD is active, do not press "Sign in" in PBI (otherwise we open other popups)
SKIP_PBI_SIGNIN_WHEN_AAD_ACTIVE = True

# 3) close AAD popup when flow is done (reduces leftover windows)
CLOSE_AAD_POPUP_WHEN_DONE = True

# 4) if HTML refreshes and beforeunload prompt appears, Selenium auto-accepts
ACCEPT_UNHANDLED_PROMPTS = True


# ===================== LOGGING =====================
def setup_logger():
    here = Path(__file__).resolve().parent
    log_file = here / "kiosk_powerbi.log"

    logger = logging.getLogger("PBI_KIOSK")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("=== START SCRIPT ===")
    logger.info(f"Version: {SCRIPT_VERSION}")
    logger.info(f"Log file: {log_file}")
    return logger

LOGGER = setup_logger()

def log_info(msg): LOGGER.info(msg)
def log_warn(msg): LOGGER.warning(msg)
def log_err(msg):  LOGGER.error(msg)


# ===================== PROCESS CLEANUP =====================
def kill_edge_processes():
    """
    Forces closure of all msedge.exe and wermgr.exe processes to avoid zombie processes.
    """
    try:
        # Kill main Edge processes
        subprocess.run(
            ["taskkill", "/IM", "msedge.exe", "/F"],
            capture_output=True,
            timeout=5
        )
        log_warn("Killed msedge.exe processes.")
    except Exception as e:
        log_warn(f"Could not kill msedge.exe: {e}")
    
    try:
        # Kill WebDriver processes
        subprocess.run(
            ["taskkill", "/IM", "msedgedriver.exe", "/F"],
            capture_output=True,
            timeout=5
        )
        log_warn("Killed msedgedriver.exe processes.")
    except Exception as e:
        log_warn(f"Could not kill msedgedriver.exe: {e}")
    
    # Wait for processes to fully die
    time.sleep(3)


def soft_quit_driver(driver):
    """
    Attempts to close the driver cleanly; if it fails, forces kill.
    """
    try:
        driver.quit()
        log_info("Driver closed cleanly.")
    except Exception as e:
        log_warn(f"Driver quit failed ({e}), will force kill Edge processes...")
        kill_edge_processes()
        time.sleep(1)


# ===================== ALERT / BEFOREUNLOAD HANDLING =====================
def accept_any_alert(driver) -> bool:
    """
    Accepts any alert/confirm/beforeunload (e.g., "Reload site?").
    Returns True if something was accepted.
    """
    try:
        al = driver.switch_to.alert
        txt = ""
        try:
            txt = al.text
        except Exception:
            pass
        al.accept()
        log_warn(f"[ALERT] ACCEPT: {txt}")
        return True
    except Exception:
        return False


# ===================== FIX #3: SELF-HEAL / AUTO-RESTART WEBDRIVER =====================
def is_driver_dead_exception(e: Exception) -> bool:
    s = (repr(e) + " " + str(e)).lower()
    return (
        "winerror 10061" in s
        or "connection refused" in s
        or "maxretryerror" in s
        or "failed to establish a new connection" in s
        or "invalidsessionid" in s
        or "disconnected" in s
        or "chrome not reachable" in s
        or "no such window" in s
        or "session not created" in s
    )

def restart_driver(driver, reason: str, retries: int = 3):
    log_err(f"[RECOVER] Restart WebDriver. Reason: {reason}")

    soft_quit_driver(driver)
    time.sleep(2)

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            log_warn(f"[RECOVER] Attempt {attempt}/{retries}: starting new driver...")
            new_driver = start_browser()
            new_driver.get(URL_DASHBOARD)
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(new_driver)
            wait_dom_ready(new_driver)

            try:
                log_info(f"[RECOVER] New session started. URL: {new_driver.current_url}")
            except Exception:
                log_info("[RECOVER] New session started. URL: (unknown)")
            return new_driver

        except Exception as e:
            last_exc = e
            error_str = str(e).lower()
            
            # SessionNotCreatedException means driver can't even start - bail out immediately
            if "sessionnotcreatedexception" in error_str:
                log_err(f"[RECOVER] SessionNotCreatedException - killing ALL Edge/driver processes and triggering full restart...")
                soft_quit_driver(new_driver if 'new_driver' in locals() else driver)
                kill_edge_processes()
                raise RuntimeError(f"SessionNotCreatedException - driver cannot start. Full restart needed. Error: {repr(e)}")
            
            log_err(f"[RECOVER] Attempt {attempt} failed: {repr(e)}")
            soft_quit_driver(new_driver if 'new_driver' in locals() else driver)
            time.sleep(3)

    raise RuntimeError(f"Restart WebDriver failed after {retries} attempts. Last error: {repr(last_exc)}")


def restart_entire_script():
    """
    Restarts the entire script from scratch (last resort).
    """
    log_err("[FATAL] Restarting entire script in 5 seconds...")
    time.sleep(5)
    
    kill_edge_processes()
    time.sleep(2)
    
    script_path = Path(__file__).resolve()
    log_info(f"[RESTART] Launching: {script_path}")
    
    try:
        subprocess.Popen([sys.executable, str(script_path)])
        log_info("[RESTART] New process started.")
    except Exception as e:
        log_err(f"[RESTART] Failed to start new process: {e}")
    
    sys.exit(0)



# ===================== WEBDRIVER VERIFICATION =====================
def verify_webdriver_available():
    """
    Verify that Edge webdriver is available. Download if missing.
    Automatically installs webdriver-manager if not present.
    Called at script startup to fail fast if driver cannot be obtained.
    """
    log_info("[SETUP] Checking if webdriver-manager is installed...")
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
    except ImportError:
        log_warn("[SETUP] webdriver-manager not installed. Installing now...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "webdriver-manager"])
            log_info("[SETUP] [OK] webdriver-manager installed successfully")
            from webdriver_manager.microsoft import EdgeChromiumDriverManager
        except Exception as e:
            log_err(f"[SETUP] [FAIL] Failed to install webdriver-manager: {e}")
            log_err("[SETUP] Try installing manually: python -m pip install webdriver-manager")
            raise RuntimeError(f"Failed to install webdriver-manager: {e}")
    
    log_info("[SETUP] Verifying Edge webdriver availability...")
    try:
        svc_path = EdgeChromiumDriverManager(
            url="https://msedgedriver.microsoft.com/",
            latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE"
        ).install()
        log_info(f"[SETUP] [OK] Edge webdriver ready: {svc_path}")
        return svc_path
    except Exception as e:
        log_err(f"[SETUP] [FAIL] Failed to verify/download Edge webdriver: {e}")
        log_err("[SETUP] Possible causes:")
        log_err("  - No internet connection or network timeout")
        log_err("  - Company firewall blocking msedgedriver.microsoft.com")
        log_err("  - Microsoft Edge not installed on this PC")
        log_err("[SETUP] Script cannot continue without webdriver. Exiting.")
        raise RuntimeError(f"Webdriver verification failed: {e}")


# ===================== BROWSER =====================
def start_browser():
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    
    here = Path(__file__).resolve().parent

    # persistent profile
    profile_dir = here / "EdgeProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    opts = webdriver.EdgeOptions()
    opts.add_argument("--start-maximized")
    opts.add_argument("--kiosk")  # Fullscreen kiosk mode
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-session-crashed-bubble")
    opts.add_argument("--hide-crash-restore-bubble")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--log-level=3")

    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--profile-directory=Default")

    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

    prefs = {
        "profile.block_third_party_cookies": False,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_experimental_option("useAutomationExtension", False)

    if ACCEPT_UNHANDLED_PROMPTS:
        # auto-accept confirm/beforeunload prompts
        opts.set_capability("unhandledPromptBehavior", "accept")

    log_info(f"Persistent Edge profile: {profile_dir}")

    log_info("[WEBDRIVER] Detecting Edge version and downloading matching driver...")
    try:
        svc_path = EdgeChromiumDriverManager(
            url="https://msedgedriver.microsoft.com/",
            latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE"
        ).install()
        log_info(f"[WEBDRIVER] Driver path: {svc_path}")
    except Exception as e:
        log_err(f"[WEBDRIVER] EdgeChromiumDriverManager failed: {e}")
        raise

    service = EdgeService(svc_path, log_output=subprocess.DEVNULL)
    return webdriver.Edge(service=service, options=opts)

def wait_dom_ready(driver, timeout=25):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass


# ===================== GENERIC HELPERS =====================
def wait_overlay_clear(driver, timeout=8):
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".lightbox-cover.disable-lightbox"))
        )
    except Exception:
        pass

def try_click(driver, el):
    try:
        el.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(el).pause(0.05).click().perform()
        return True
    except Exception:
        pass
    return False

def is_visible(driver, by, sel, timeout=0.9):
    try:
        return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, sel)))
    except Exception:
        return None

def wait_clickable(driver, by, sel, timeout=5):
    try:
        return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, sel)))
    except Exception:
        return None

def has_page_id(driver, page_id: str) -> bool:
    try:
        return bool(driver.execute_script(
            "return !!document.querySelector('meta[name=\"PageID\"][content=\"'+arguments[0]+'\"]');", page_id
        ))
    except Exception:
        return False

def click_primary_btn(driver, timeout=6) -> bool:
    wait_overlay_clear(driver, timeout=3)
    try:
        btn = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.ID, MS_PRIMARY_BTN_ID)))
        try:
            btn.click()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            driver.execute_script("arguments[0].click();", btn)
        except Exception:
            driver.execute_script("arguments[0].click();", btn)
        return True
    except Exception:
        return False

def click_sso_consent_continue(driver, timeout=3) -> bool:
    """
    Handle the SSO Consent page ("Continue to sign in?").
    Finds and clicks the Continue button by looking for a submit button inside the ssoConsentForm
    that contains the text "Continue" or has aria-labelledby="ssoConsentTitle".
    """
    wait_overlay_clear(driver, timeout=2)
    try:
        try:
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@aria-labelledby='ssoConsentTitle' and @type='submit']"))
            )
            log_info("[SSO Consent] Found Continue button by aria-labelledby.")
        except Exception:
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//form[@name='ssoConsentForm']//button[contains(@class, 'ext-primary') and normalize-space(text())='Continue']"))
            )
            log_info("[SSO Consent] Found Continue button by form and text.")
        
        try:
            btn.click()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            driver.execute_script("arguments[0].click();", btn)
        except Exception:
            driver.execute_script("arguments[0].click();", btn)
        
        log_info("[SSO Consent] Clicked Continue button.")
        return True
    except Exception as e:
        return False

def focus_scroll_type(driver, el, text):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        el.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].focus();", el)
        except Exception:
            pass
    try:
        el.clear()
    except Exception:
        pass
    try:
        el.send_keys(text)
        return True
    except ElementNotInteractableException:
        try:
            driver.execute_script("""
                const e = arguments[0], v = arguments[1];
                e.value = v;
                e.dispatchEvent(new Event('input', {bubbles:true}));
                e.dispatchEvent(new Event('change', {bubbles:true}));
            """, el, text)
            return True
        except Exception:
            return False
    except Exception:
        return False


# ===================== BLANK POPUP HANDLING =====================
BLANK_URLS = {"about:blank", "data:,"}

def is_blank_popup_url(u: str) -> bool:
    u = (u or "").strip().lower()
    return (u in BLANK_URLS) or u.startswith("about:blank")

def wait_for_popup_navigation(driver, timeout=12.0, poll=0.25):
    end = time.time() + timeout
    while time.time() < end:
        if ACCEPT_UNHANDLED_PROMPTS:
            accept_any_alert(driver)
        try:
            url = driver.current_url
            if url and not is_blank_popup_url(url):
                return url
        except Exception:
            pass
        time.sleep(poll)
    return None

def safe_close_window(driver, handle, protected_handles=None) -> bool:
    protected_handles = protected_handles or set()
    if handle in protected_handles:
        return False
    try:
        if handle in driver.window_handles:
            driver.switch_to.window(handle)
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(driver)
            driver.close()
            return True
    except Exception:
        pass
    return False

def recover_after_blank_popup(driver, dashboard_handle, dashboard_url):
    try:
        driver.switch_to.window(dashboard_handle)
        if ACCEPT_UNHANDLED_PROMPTS:
            accept_any_alert(driver)
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        driver.refresh()
        if ACCEPT_UNHANDLED_PROMPTS:
            accept_any_alert(driver)
        log_warn("Recover: refreshed dashboard after blank popup.")
        return True
    except Exception:
        try:
            driver.get(dashboard_url)
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(driver)
            log_warn("Recover: fetched dashboard after blank popup.")
            return True
        except Exception:
            return False


# ===================== POWER BI SIGN IN =====================
PBI_SIGNIN_LOCATORS = [
    (By.ID, "pbi-reportembed-singin-button"),
    (By.CSS_SELECTOR, "button.pbi-fluent-button.primary"),
    (By.XPATH, "//button[normalize-space()='Sign in']"),
    (By.XPATH, "//*[@role='button' and normalize-space()='Sign in']"),
    (By.XPATH, "//button[contains(., 'Sign in to view')]"),
    (By.XPATH, "//*[self::button or self::a][contains(normalize-space(.), 'Sign in')]"),
    (By.XPATH, "//*[self::button or self::a][contains(normalize-space(.), 'Conecta') "
               "or contains(normalize-space(.), 'Autentif') "
               "or contains(normalize-space(.), 'Oturum')]"),
    (By.CSS_SELECTOR, "[aria-label*='Sign in' i]"),
]

def find_pbi_signin_in_current_context(driver):
    try:
        for by, sel in PBI_SIGNIN_LOCATORS:
            try:
                elems = driver.find_elements(by, sel)
            except WebDriverException:
                elems = []
            for el in elems:
                try:
                    visible = driver.execute_script("""
                        const e = arguments[0], s = getComputedStyle(e), r = e.getBoundingClientRect();
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
                    """, el)
                    if not visible:
                        continue
                    if try_click(driver, el):
                        log_info("Pressed PBI 'Sign in' (current context).")
                        return True
                except WebDriverException:
                    continue
    except WebDriverException:
        pass
    return False

def install_pbi_watchdog_in_current_context(driver):
    js = """
    (function(){
      try{
        if (window.__pbiSignInWatchdogInstalled) return 'already';
        window.__pbiSignInWatchdogInstalled = true;

        function visible(el){
          if(!el) return false;
          const s=getComputedStyle(el), r=el.getBoundingClientRect();
          return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
        }
        function clickIfReady(){
          try{
            var btn = document.getElementById('pbi-reportembed-singin-button')
                      || document.querySelector('button.pbi-fluent-button.primary');
            if(btn && visible(btn)){
              btn.click();
              return true;
            }
          }catch(e){}
          return false;
        }

        if (clickIfReady()) return 'clicked-now';

        const mo = new MutationObserver(function(){ clickIfReady(); });
        mo.observe(document.documentElement, {subtree:true, childList:true, attributes:true});

        window.__pbiWatchdogInterval = window.setInterval(clickIfReady, 2000);
        return 'installed';
      }catch(e){
        return 'error:' + (e && e.message ? e.message : e);
      }
    })();
    """
    try:
        return driver.execute_script(js)
    except Exception as e:
        return f"inject-error:{e}"

def scan_frames_recursive_and_click_pbi(driver, depth=0, max_depth=IFRAME_MAX_DEPTH, install_watchdog=True):
    if depth > max_depth:
        return False

    if install_watchdog:
        try:
            install_pbi_watchdog_in_current_context(driver)
        except Exception:
            pass

    if find_pbi_signin_in_current_context(driver):
        return True

    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except WebDriverException:
        frames = []

    for frame in frames:
        try:
            driver.switch_to.frame(frame)
            if scan_frames_recursive_and_click_pbi(driver, depth + 1, max_depth, install_watchdog):
                driver.switch_to.default_content()
                return True
            driver.switch_to.parent_frame()
        except WebDriverException:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            continue
    return False


# ===================== MICROSOFT AAD PAGES =====================
def pick_account_tile_if_present(driver, email, cooldown, state) -> bool:
    now = time.time()
    last = state.get("last_tile_click", 0)
    if now - last < cooldown:
        return False

    try:
        tile = WebDriverWait(driver, 1.2).until(
            EC.presence_of_element_located(
                (By.XPATH, f"//*[normalize-space(text())='{email}']/ancestor::*[self::div or self::button][1]")
            )
        )
    except Exception:
        return False

    try:
        if tile.is_displayed() and try_click(driver, tile):
            state["last_tile_click"] = now
            state["tile_clicks"] = state.get("tile_clicks", 0) + 1
            log_info("Click account tile.")
            for _ in range(20):
                if (is_visible(driver, By.ID, "i0118") or is_visible(driver, By.ID, "i0116")
                    or is_visible(driver, By.ID, "KmsiDescription") or is_visible(driver, By.ID, "appConfirmTitle")):
                    break
                time.sleep(0.1)
            return True
    except WebDriverException:
        pass
    return False

def handle_microsoft_pages_once(driver, email: str, password: str, state: dict, max_wait=8) -> bool:
    end = time.time() + max_wait
    did = False
    while time.time() < end:
        if ACCEPT_UNHANDLED_PROMPTS:
            accept_any_alert(driver)
        try:
            # Handle SSO Consent page ("Continue to sign in?") - NEW
            if click_sso_consent_continue(driver, timeout=2):
                did = True
                time.sleep(0.5)
                continue

            if state.get("tile_clicks", 0) < MAX_TILE_CLICKS_PER_VISIT:
                if pick_account_tile_if_present(driver, email, TILE_COOLDOWN, state):
                    did = True
                    time.sleep(0.5)
                    continue

            if has_page_id(driver, "CmsiInterrupt") or is_visible(driver, By.ID, "appConfirmTitle"):
                if click_primary_btn(driver, timeout=6):
                    did = True
                    time.sleep(0.5)
                    continue

            if is_visible(driver, By.ID, "KmsiDescription"):
                if click_primary_btn(driver, timeout=6):
                    did = True
                    time.sleep(0.5)
                    continue

            email_box = wait_clickable(driver, By.ID, "i0116", timeout=2) or is_visible(driver, By.NAME, "loginfmt")
            if email_box:
                if focus_scroll_type(driver, email_box, email):
                    if click_primary_btn(driver, timeout=8):
                        did = True
                        time.sleep(0.5)
                        continue

            pass_box = wait_clickable(driver, By.ID, "i0118", timeout=3) or is_visible(driver, By.NAME, "passwd")
            if pass_box:
                wait_overlay_clear(driver, timeout=5)
                if focus_scroll_type(driver, pass_box, password):
                    if not click_primary_btn(driver, timeout=8):
                        try:
                            pass_box.send_keys(Keys.ENTER)
                            did = True
                            time.sleep(0.5)
                            continue
                        except Exception:
                            pass
                    else:
                        did = True
                        time.sleep(0.5)
                        continue

            if (not is_visible(driver, By.NAME, "loginfmt")) and (not is_visible(driver, By.NAME, "passwd")):
                if click_primary_btn(driver, timeout=2):
                    did = True
                    time.sleep(0.5)
                    continue

        except WebDriverException:
            break
        time.sleep(0.2)
    return did


# ===================== WINDOW / HANDLE MANAGEMENT (FIXED) =====================
def strip_url_noise(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    u = u.split("#", 1)[0]
    return u.lower().rstrip("/")

def is_dashboard_url(current_url: str, dashboard_url: str) -> bool:
    u = strip_url_noise(current_url)
    d = strip_url_noise(dashboard_url)
    return (u == d) or (u.startswith(d + "?"))

def is_aad_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in ("microsoftonline.com", "login.live.com", "login.microsoft.com", "sts.windows.net"))

def is_yammer_url(url: str) -> bool:
    """Detect Yammer URLs to auto-close them."""
    u = (url or "").lower()
    return any(x in u for x in ("yammer.com", "engage.cloud.microsoft", "teams.microsoft.com/yammer"))

def ensure_dashboard_handle(driver, dashboard_handle, dashboard_url):
    """
    IMPORTANT: do not open new tabs unless the dashboard does not exist anywhere.
    """
    try:
        if dashboard_handle and dashboard_handle in driver.window_handles:
            driver.switch_to.window(dashboard_handle)
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(driver)
            try:
                if is_dashboard_url(driver.current_url, dashboard_url):
                    return dashboard_handle
            except Exception:
                pass
    except Exception:
        pass

    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(driver)
            if is_dashboard_url(driver.current_url, dashboard_url):
                log_warn("Dashboard handle restored by scanning window_handles.")
                return h
        except Exception:
            continue

    try:
        driver.switch_to.new_window("tab")
    except Exception:
        pass
    driver.get(dashboard_url)
    if ACCEPT_UNHANDLED_PROMPTS:
        accept_any_alert(driver)
    wait_dom_ready(driver)
    new_handle = driver.current_window_handle
    log_warn("Dashboard not found; reopened in a new tab.")
    return new_handle


# ===================== MAIN =====================
def main():
    if not PASSWORD:
        log_warn("Environment variable PBI_KIOSK_PASSWORD is not set. Autologin might fail at password.")

    # Verify webdriver is available BEFORE attempting to start browser
    try:
        verify_webdriver_available()
    except Exception as e:
        log_err(f"[FATAL] Script startup failed: {e}")
        sys.exit(1)

    driver = start_browser()
    driver.get(URL_DASHBOARD)
    if ACCEPT_UNHANDLED_PROMPTS:
        accept_any_alert(driver)
    wait_dom_ready(driver)

    log_info(f"Current URL: {driver.current_url}")
    log_info(f"Dashboard URL (from URL_PATH): {URL_DASHBOARD}")

    DASHBOARD_HANDLE = driver.current_window_handle
    known_handles = set(driver.window_handles)
    window_states = {}
    last_pbi_click = 0.0
    last_blank_popup_recover = 0.0
    last_heartbeat = 0.0
    consecutive_errors = 0  # Track consecutive errors for full restart

    # Anti-flicker: a single "active" AAD popup
    aad_active_handle = None
    aad_active_since = 0.0

    while True:
        try:
            consecutive_errors = 0  # Reset on successful iteration
            
            if ACCEPT_UNHANDLED_PROMPTS:
                accept_any_alert(driver)

            # Safety: tab cap (do not close dashboard)
            try:
                if len(driver.window_handles) > MAX_TABS_SAFETY:
                    log_warn(f"Too many tabs ({len(driver.window_handles)}). Closing the newest ones for protection.")
                    keep = set([DASHBOARD_HANDLE])
                    for h in list(driver.window_handles):
                        if h not in keep and len(keep) < 3:
                            keep.add(h)
                    for h in list(driver.window_handles):
                        if h not in keep:
                            safe_close_window(driver, h, protected_handles={DASHBOARD_HANDLE})
            except Exception:
                pass

            # Heartbeat
            now = time.time()
            if now - last_heartbeat > HEARTBEAT_SECONDS:
                try:
                    driver.switch_to.window(DASHBOARD_HANDLE)
                    if ACCEPT_UNHANDLED_PROMPTS:
                        accept_any_alert(driver)
                    log_info(f"Heartbeat: handles={len(driver.window_handles)} | dashboard_url={driver.current_url} | aad_active={bool(aad_active_handle)}")
                except Exception:
                    log_info("Heartbeat: (cannot read current_url)")
                last_heartbeat = now

            # 0) Ensure dashboard handle (minimizes random switches)
            DASHBOARD_HANDLE = ensure_dashboard_handle(driver, DASHBOARD_HANDLE, URL_DASHBOARD)

            # 1) Detect new windows and handle blank popup
            try:
                current_handles = set(driver.window_handles)
            except WebDriverException:
                current_handles = set()

            new_handles = current_handles - known_handles
            if new_handles:
                for nh in list(new_handles):
                    window_states.setdefault(nh, {"last_tile_click": 0, "tile_clicks": 0})

                    # IMPORTANT: switch here only to read url and decide if it's AAD/blank,
                    # but don't loop through all windows constantly.
                    try:
                        driver.switch_to.window(nh)
                        if ACCEPT_UNHANDLED_PROMPTS:
                            accept_any_alert(driver)
                    except Exception:
                        continue

                    url = wait_for_popup_navigation(driver, timeout=BLANK_POPUP_WAIT_SECONDS)

                    if url is None:
                        log_warn(f"Popup {nh} stayed BLANK (about:blank). Closing it.")
                        safe_close_window(driver, nh, protected_handles={DASHBOARD_HANDLE})

                        now2 = time.time()
                        if now2 - last_blank_popup_recover > BLANK_POPUP_COOLDOWN:
                            last_blank_popup_recover = now2
                            recover_after_blank_popup(driver, DASHBOARD_HANDLE, URL_DASHBOARD)
                        else:
                            log_warn("Blank popup repeated too often -> skip recover (cooldown active).")
                    elif is_yammer_url(url):
                        log_warn(f"Detected Yammer tab {nh} | URL: {url}. Closing it.")
                        safe_close_window(driver, nh, protected_handles={DASHBOARD_HANDLE})
                    else:
                        log_info(f"Detected new window: {nh} | URL: {url}")

                        # Anti-flicker: set the first AAD popup as "active"
                        if is_aad_url(url) and aad_active_handle is None:
                            aad_active_handle = nh
                            aad_active_since = time.time()
                            log_warn(f"[AAD] Flow active on handle={aad_active_handle}. Stop spamming PBI Sign-in.")

                # return to dashboard after inspecting popups
                try:
                    driver.switch_to.window(DASHBOARD_HANDLE)
                except Exception:
                    pass

            # Refresh known_handles after possible closures
            try:
                known_handles = set(driver.window_handles)
            except Exception:
                pass

            # 2) Scan PBI Sign in - ALWAYS in dashboard, but not if AAD is active (anti flicker + anti popup spam)
            try:
                driver.switch_to.window(DASHBOARD_HANDLE)
                if ACCEPT_UNHANDLED_PROMPTS:
                    accept_any_alert(driver)
                driver.switch_to.default_content()
            except Exception:
                pass

            # if AAD is active, do not press "Sign in" in PBI; wait for the flow to finish
            if SKIP_PBI_SIGNIN_WHEN_AAD_ACTIVE and aad_active_handle:
                if (time.time() - aad_active_since) > AAD_FLOW_ACTIVE_TIMEOUT:
                    log_warn("[AAD] Flow timeout. Resetting AAD handle to allow retry.")
                    aad_active_handle = None
                    aad_active_since = 0.0
            else:
                now = time.time()
                if now - last_pbi_click > PBI_SIGNIN_COOLDOWN:
                    try:
                        log_info(f"Scanning PBI in dashboard | URL: {driver.current_url}")
                    except Exception:
                        log_info("Scanning PBI in dashboard | URL: (unknown)")

                    if scan_frames_recursive_and_click_pbi(driver, depth=0, max_depth=IFRAME_MAX_DEPTH, install_watchdog=True):
                        last_pbi_click = now

            # 3) Process AAD ONLY on the active window (reduces massive flicker)
            if aad_active_handle:
                # if window disappeared, reset
                try:
                    handles_now = set(driver.window_handles)
                except Exception:
                    handles_now = set()

                if aad_active_handle not in handles_now:
                    log_warn("[AAD] Active handle no longer exists. Resetting AAD.")
                    aad_active_handle = None
                    aad_active_since = 0.0
                else:
                    try:
                        driver.switch_to.window(aad_active_handle)
                        if ACCEPT_UNHANDLED_PROMPTS:
                            accept_any_alert(driver)
                    except Exception:
                        aad_active_handle = None
                        aad_active_since = 0.0
                    else:
                        st = window_states.setdefault(aad_active_handle, {"last_tile_click": 0, "tile_clicks": 0})
                        try:
                            url = driver.current_url
                        except Exception:
                            url = ""

                        if is_blank_popup_url(url):
                            # if it became blank, close and reset
                            log_warn("[AAD] Active popup became blank. Closing and resetting.")
                            safe_close_window(driver, aad_active_handle, protected_handles={DASHBOARD_HANDLE})
                            aad_active_handle = None
                            aad_active_since = 0.0
                        elif is_aad_url(url):
                            log_info(f"[AAD] Processing flow | handle={aad_active_handle} | URL: {url}")
                            handle_microsoft_pages_once(driver, USER_EMAIL, PASSWORD or "", st, max_wait=5)

                            # if it left AAD domains, the flow is complete
                            try:
                                if not is_aad_url(driver.current_url):
                                    log_info("[AAD] Flow complete. Closing popup (optional) and returning to dashboard.")
                                    st["tile_clicks"] = 0

                                    if CLOSE_AAD_POPUP_WHEN_DONE:
                                        try:
                                            driver.close()
                                            log_info("[AAD] Popup closed.")
                                        except Exception:
                                            pass

                                    aad_active_handle = None
                                    aad_active_since = 0.0
                            except Exception:
                                pass
                        else:
                            # no longer AAD => consider it done
                            log_info("[AAD] Active popup no longer AAD. Resetting AAD.")
                            aad_active_handle = None
                            aad_active_since = 0.0

            # Return to dashboard at the end of iteration (stabilizes focus)
            try:
                driver.switch_to.window(DASHBOARD_HANDLE)
                if ACCEPT_UNHANDLED_PROMPTS:
                    accept_any_alert(driver)
            except Exception:
                pass

            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            log_info("Ctrl+C -> leaving Edge window open (not closing driver).")
            break

        except Exception as e:
            consecutive_errors += 1
            LOGGER.exception("Exception in loop (stacktrace):")
            log_err(f"Consecutive errors: {consecutive_errors}")

            # Self-heal when driver dies (WinError 10061 etc.)
            if is_driver_dead_exception(e):
                try:
                    driver = restart_driver(driver, reason=repr(e), retries=3)

                    # reset state
                    DASHBOARD_HANDLE = driver.current_window_handle
                    known_handles = set(driver.window_handles)
                    window_states = {}
                    last_pbi_click = 0.0
                    last_blank_popup_recover = 0.0
                    last_heartbeat = 0.0
                    aad_active_handle = None
                    aad_active_since = 0.0
                    consecutive_errors = 0

                    time.sleep(1.0)
                    continue
                except Exception as e2:
                    LOGGER.exception(f"[RECOVER] Restart failed: {repr(e2)}")
                    consecutive_errors += 1

            # If we've had too many consecutive errors, restart the entire script
            if consecutive_errors >= 2:
                log_err(f"[FATAL] Too many consecutive errors ({consecutive_errors}). Full script restart.")
                soft_quit_driver(driver)
                kill_edge_processes()
                restart_entire_script()

            time.sleep(SCAN_INTERVAL_SECONDS)

    # intentionally no driver.quit()

if __name__ == "__main__":
    main()
