"""Fb Reviews Automation - permanent module.
Run via main.py mode 3

Reads:
  output/browser_accounts.txt  (uid|password|cookies)
  reviews.txt                  (one review per line - paste client list here)
  target_page.txt              (Facebook page URL)

Integrated into main tool as Reviews Mode.
"""
import os
import sys
import time
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright
from automation.browser_register import (
    _human_type,
    _human_pause,
    _human_click,
)
from ui.colors import GREEN, RED, WHITE, YELLOW, CYAN
from ui.display import print_lock

from core.path_manager import get_output_dir, get_base_storage_dir


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def gemini_variations(reviews, needed, api_key):
    """Use Gemini to expand few reviews into many unique variations."""
    try:
        import google.generativeai as genai
    except ImportError:
        print(f"{YELLOW}Installing google-generativeai...{WHITE}")
        os.system(f"{sys.executable} -m pip install google-generativeai -q")
        import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    base = "\n".join([f"{i+1}. {r}" for i, r in enumerate(reviews)])
    prompt = f"""You are a review writer. Given these sample reviews:
{base}

Generate {needed} UNIQUE review variations. Same positive meaning, different wording each time.
Natural human tone, varied length (some short, some 2 sentences).
Output ONLY the reviews, one per line, no numbering."""

    resp = model.generate_content(prompt)
    lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
    # Clean numbering if present
    cleaned = []
    for l in lines:
        import re
        l = re.sub(r"^\d+[.\)]\s*", "", l)
        if l:
            cleaned.append(l)
    return cleaned[:needed]


def _parse_cookies_any(raw, default_domain=".facebook.com"):
    """Parse cookies in ANY common format into Playwright cookie dicts.

    Handles: JSON array/dict (browser-extension exports like
    EditThisCookie / Cookie-Editor), Netscape cookies.txt
    (tab-separated), and name=value text separated by ';', '|'
    or newlines (with an optional leading 'Cookie:' label).
    Set-Cookie attribute pairs (expires/path/domain/...) are
    skipped. Returns a list of {name, value, domain, path}."""
    import json as _json
    raw = (raw or "").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    if not raw:
        return []
    out = []
    seen = set()
    _skip = {"expires", "max-age", "path", "domain", "secure",
             "httponly", "samesite", "version", "comment"}

    def _add(name, value, domain=None, path="/"):
        name = str(name or "").strip().strip('"').strip("'")
        value = str(value or "").strip().strip('"').strip("'")
        if not name or name.lower() in _skip:
            return
        dom = str(domain or default_domain).strip() or default_domain
        key = (name, dom)
        if key in seen:
            return
        seen.add(key)
        out.append({"name": name, "value": value,
                    "domain": dom, "path": path or "/"})

    # 1) JSON: array of cookie objects, single object, or name->value map
    if raw[:1] in ("[", "{"):
        try:
            data = _json.loads(raw)
            if isinstance(data, dict):
                if any(str(k).lower() in ("name", "value") for k in data):
                    data = [data]
                else:
                    for k, v in data.items():
                        _add(k, v)
                    return out
            if isinstance(data, list):
                for c in data:
                    if not isinstance(c, dict):
                        continue
                    low = {str(k).lower(): v for k, v in c.items()}
                    _add(low.get("name"), low.get("value"),
                         low.get("domain") or low.get("host"),
                         low.get("path", "/"))
                return out
        except Exception:
            pass

    # 2) Netscape cookies.txt: tab-separated, >=7 fields per line
    lines = [ln for ln in raw.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if lines and all("\t" in ln for ln in lines):
        rows = []
        ok = True
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) < 7:
                ok = False
                break
            rows.append((parts[5], parts[6], parts[0], parts[2]))
        if ok:
            for nm, val, dom, pth in rows:
                _add(nm, val, dom, pth)
            return out

    # 3) name=value text separated by ';', '|' or newlines
    text = raw.replace("\r", "\n").replace("|", ";").replace("\n", ";")
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        _add(name, value)
    return out


def fb_login(context, page, cookie_str):
    """Login to Facebook directly via saved cookies (safer than password).
    Accepts cookies in any common format (see _parse_cookies_any).
    Returns True ONLY when the account is really logged in. A dead cookie
    can land on a checkpoint or another non-login URL, so the URL alone
    is not enough - also check that no login form is showing. The
    failure reason is printed so a dead cookie is distinguishable
    from a checkpoint."""
    try:
        cookies = _parse_cookies_any(cookie_str)
        if not cookies:
            with print_lock:
                print(f"{RED}[Reviews] No usable cookies parsed{WHITE}")
            return False
        context.add_cookies(cookies)
    except Exception as e:
        with print_lock:
            print(f"{RED}[Reviews] Cookie load failed: {e}{WHITE}")
        return False
    # Verify by opening Facebook
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(random.uniform(2.0, 3.0))
    try:
        url = page.url.lower()
        # Login page or checkpoint = NOT logged in (dead/gated cookie)
        if "checkpoint" in url:
            with print_lock:
                print(f"{YELLOW}[Reviews] Cookie -> checkpoint page{WHITE}")
            return False
        if "login" in url:
            with print_lock:
                print(f"{YELLOW}[Reviews] Cookie -> login page (dead cookie){WHITE}")
            return False
        # A visible password field means the login form is showing
        # (dead cookie) even when the URL looks like home.
        try:
            if page.locator('input[type="password"]').first.is_visible(timeout=3000):
                with print_lock:
                    print(f"{YELLOW}[Reviews] Cookie -> login form showing (dead cookie){WHITE}")
                return False
        except Exception:
            pass
        return True
    except Exception:
        return False


def submit_review(page, page_url, review_text):
    """Submit a page review. VERIFIED selectors (2026-10-13 live test).
    Flow: page?sk=reviews -> Yes button -> wait composer -> textbox -> Post.
    Returns True only if submission is verified."""
    # Extract page ID and go directly to reviews tab
    import re as _re
    _m = _re.search(r'id=(\d+)', page_url)
    if _m:
        _pid = _m.group(1)
        _reviews_url = f"https://www.facebook.com/profile.php?id={_pid}&sk=reviews"
    else:
        _reviews_url = page_url.rstrip("/") + "/reviews"
    page.goto(_reviews_url, wait_until="domcontentloaded", timeout=30000)
    _human_pause(2.0, 3.0)

    # Skip if this account already reviewed (no Yes button = already done)
    try:
        page.get_by_role("button", name="Yes", exact=True).first.wait_for(
            state="visible", timeout=8000)
    except Exception:
        _body = page.content().lower()
        if "recommends" in _body:
            with print_lock:
                print(f"{YELLOW}[Reviews] Already reviewed - skipping{WHITE}")
            # 'already' is truthy, so run_reviews_mode counts it exactly
            # as the old True did; the combined flow below uses the
            # distinct value to keep the review in the queue.
            return "already"  # nothing posted
        with print_lock:
            print(f"{RED}[Reviews] Yes button not found and no existing review{WHITE}")
        return False

    # Click "Yes" (normal button, NOT radio)
    try:
        _yes = page.get_by_role("button", name="Yes", exact=True).first
        _human_click(page, _yes)
        with print_lock:
            print(f"{GREEN}[Reviews] Clicked Yes{WHITE}")
    except Exception as e:
        with print_lock:
            print(f"{RED}[Reviews] Yes button not found: {e}{WHITE}")
        return False

    # Wait for composer dialog (10-15 sec load)
    try:
        _dialog = page.get_by_role("dialog").first
        _dialog.wait_for(state="visible", timeout=20000)
        with print_lock:
            print(f"{CYAN}[Reviews] Dialog opened{WHITE}")
    except Exception as e:
        with print_lock:
            print(f"{RED}[Reviews] Dialog did not open: {e}{WHITE}")
        return False

    # Textbox: DIV contenteditable, dynamic aria-label - match by role only
    try:
        _textbox = _dialog.get_by_role("textbox").first
        _textbox.wait_for(state="visible", timeout=20000)
        _human_type(page, _textbox, review_text)
        with print_lock:
            print(f"{CYAN}[Reviews] Text typed{WHITE}")
    except Exception as e:
        with print_lock:
            print(f"{RED}[Reviews] Textbox failed: {e}{WHITE}")
        return False
    _human_pause(1.0, 2.0)

    # Privacy -> Public (LIVE-verified 2026-10-13)
    try:
        _priv = _dialog.locator("[aria-label*='Edit privacy']").first
        _priv.wait_for(state="visible", timeout=10000)
        _human_click(page, _priv)
        time.sleep(3)
        # Public is PLAIN TEXT (not a button!)
        _pub = page.get_by_text("Public", exact=True).first
        _pub.wait_for(state="visible", timeout=10000)
        _human_click(page, _pub)
        time.sleep(2)
        # Done is also PLAIN TEXT (not a button role!)
        _done = page.get_by_text("Done", exact=True).first
        _done.wait_for(state="visible", timeout=10000)
        _human_click(page, _done)
        time.sleep(3)
        with print_lock:
            print(f"{CYAN}[Reviews] Privacy set to Public{WHITE}")
    except Exception as e:
        with print_lock:
            print(f"{YELLOW}[Reviews] Privacy change skipped: {e}{WHITE}")

    # Click Post (exact name "Post")
    try:
        _post = _dialog.get_by_role("button", name="Post", exact=True).first
        _human_click(page, _post)
        with print_lock:
            print(f"{CYAN}[Reviews] Clicked Post{WHITE}")
    except Exception as e:
        with print_lock:
            print(f"{RED}[Reviews] Post button not found: {e}{WHITE}")
        return False

    # Wait for dialog to CLOSE = real submission signal (up to 20 sec)
    _submitted = False
    for _i in range(20):
        time.sleep(1)
        try:
            if _dialog.count() == 0 or not _dialog.is_visible():
                _submitted = True
                break
        except Exception:
            _submitted = True  # dialog gone = submitted
            break
    if not _submitted:
        with print_lock:
            print(f"{RED}[Reviews] Dialog did not close - Post may have failed{WHITE}")
        # Try clicking Post once more
        try:
            _post2 = page.get_by_role("button", name="Post", exact=True).first
            if _post2.count() > 0 and _post2.is_visible(timeout=3000):
                _human_click(page, _post2)
                with print_lock:
                    print(f"{YELLOW}[Reviews] Retried Post click{WHITE}")
                time.sleep(5)
                try:
                    if _dialog.count() == 0 or not _dialog.is_visible():
                        _submitted = True
                except Exception:
                    _submitted = True
        except Exception:
            pass
    if not _submitted:
        with print_lock:
            print(f"{RED}[Reviews] FAILED: review not submitted{WHITE}")
        return False

    # Dialog closed - now verify review appears on page (dialog is gone)
    time.sleep(random.uniform(2.0, 4.0))
    _verified = False
    try:
        _page_text = page.content().lower()
        if review_text[:20].lower() in _page_text:
            _verified = True
    except Exception:
        pass

    # VISUAL CONFIRM: scroll review to center of screen, keep open 8 sec
    try:
        _review_el = page.get_by_text(review_text[:30]).first
        if _review_el.count() > 0:
            _review_el.scroll_into_view_if_needed(timeout=5000)
            # Center it exactly
            page.evaluate("""el => {
                const r = el.getBoundingClientRect();
                window.scrollBy(0, r.top - window.innerHeight/2 + r.height/2);
            }""", _review_el.element_handle(timeout=5000))
            with print_lock:
                print(f"{GREEN}[Reviews] Review visible on screen - showing for 8 sec{WHITE}")
            time.sleep(8)
            _verified = True
        else:
            # Fallback: scroll page to reviews section
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
            time.sleep(8)
    except Exception as e:
        with print_lock:
            print(f"{YELLOW}[Reviews] Visual scroll failed: {str(e)[:60]}{WHITE}")
        time.sleep(5)

    if _verified:
        with print_lock:
            print(f"{GREEN}[Reviews] VERIFIED: review live on page{WHITE}")
    else:
        with print_lock:
            print(f"{GREEN}[Reviews] Submitted (dialog closed){WHITE}")
    return True

def run_reviews_mode():
    print(f"{CYAN}=== Fb Reviews Automation ==={WHITE}")

    accounts = read_lines(os.path.join(get_output_dir(), "browser_accounts.txt"))
    reviews = read_lines(os.path.join(get_base_storage_dir(), "reviews.txt"))

    if not accounts:
        print(f"{RED}No accounts in output/browser_accounts.txt{WHITE}")
        return
    if not reviews:
        print(f"{RED}No reviews in reviews.txt - paste client list there{WHITE}")
        return

    # Use every review in the file - no prompt.
    need = len(reviews)

    # Gemini expands if needed > available
    if need > len(reviews):
        print(f"{CYAN}Need {need}, have {len(reviews)} - asking Gemini for variations...{WHITE}")
        _key_file = os.path.join(get_base_storage_dir(), "gemini_api_key.txt")
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key and os.path.exists(_key_file):
            with open(_key_file) as _kf:
                api_key = _kf.read().strip()
        if not api_key:
            api_key = input(f"{CYAN}Enter Gemini API Key (one time only): {WHITE}").strip()
            if api_key:
                with open(_key_file, "w") as _kf:
                    _kf.write(api_key)
                print(f"{GREEN}API key saved - won't ask again{WHITE}")
        if api_key:
            reviews = gemini_variations(reviews, need, api_key)
            print(f"{GREEN}Gemini generated {len(reviews)} unique reviews{WHITE}")
        else:
            print(f"{YELLOW}No API key - using available reviews only{WHITE}")
            need = len(reviews)
    else:
        reviews = reviews[:need]

    # Live input: paste page link in terminal (like custom password)
    page_url = input(f"{CYAN}Paste Facebook Page Link and press Enter: {WHITE}").strip()
    if not page_url:
        print(f"{RED}No link given{WHITE}")
        return
    print(f"{CYAN}Page: {page_url}{WHITE}")
    print(f"{CYAN}Accounts: {len(accounts)}, Reviews: {len(reviews)}{WHITE}")

    # Queue: a review is consumed ONLY when actually posted.
    # Already-reviewed / failed login / failed post leaves the review
    # in the queue for the next working account.
    queue = list(reviews)
    total = len(queue)

    with sync_playwright() as p:
        _exe = os.path.expandvars(
            r"C:\Users\Rizvi Lion\AppData\Local\ms-playwright\chromium-1243\chrome-win\chrome.exe"
        )
        _launch_kwargs = dict(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        _lk = dict(_launch_kwargs)
        if os.path.exists(_exe):
            _lk["executable_path"] = _exe
        browser = p.chromium.launch(**_lk)

        done = 0
        for acc_line in accounts:
            if not queue:
                break  # every review posted
            parts = acc_line.split("|")
            uid = parts[0]
            cookie_str = parts[2] if len(parts) > 2 else ""
            if not cookie_str:
                print(f"{RED}[Reviews] No cookies for {uid}, skipping - review stays in queue{WHITE}")
                continue
            print(f"\n{CYAN}--- Account: {uid} ---{WHITE}")
            review = queue[0]

            context = browser.new_context()
            page = context.new_page()

            try:
                logged_in = fb_login(context, page, cookie_str)
                if not logged_in:
                    # Cookie dead -> UID+password fallback in the
                    # SAME open browser/page.
                    _pwd = parts[1] if len(parts) > 1 else ""
                    if _pwd:
                        print(f"{YELLOW}[Reviews] Cookie failed for {uid} - trying password login{WHITE}")
                        try:
                            from automation.dp_apply import password_login
                            _st = password_login(page, uid, _pwd)
                            if _st == "checkpoint":
                                print(f"{RED}[Reviews] {uid} checkpoint on password login - skipping{WHITE}")
                            elif _st == "captcha-unavailable":
                                print(f"{YELLOW}[Reviews] {uid} check appeared - solve in browser, skipping{WHITE}")
                            else:
                                try:
                                    _cks = context.cookies()
                                    _has_cu = any(c["name"] == "c_user" and c["value"] for c in _cks)
                                    _u = page.url.lower()
                                    logged_in = _has_cu and "login" not in _u and "checkpoint" not in _u
                                except Exception:
                                    logged_in = False
                        except Exception as e:
                            print(f"{RED}[Reviews] Password login error for {uid}: {e}{WHITE}")
                if not logged_in:
                    print(f"{RED}[Reviews] Login failed for {uid} - review stays in queue{WHITE}")
                    continue
                print(f"{GREEN}[Reviews] Logged in: {uid}{WHITE}")

                result = submit_review(page, page_url, review)
                if result is True:
                    print(f"{GREEN}[Reviews] Review submitted for {uid}{WHITE}")
                    queue.pop(0)
                    done += 1
                elif result == "already":
                    print(f"{YELLOW}[Reviews] {uid} already reviewed - review stays in queue{WHITE}")
                else:
                    print(f"{RED}[Reviews] Review FAILED for {uid} - review stays in queue{WHITE}")
            except Exception as e:
                print(f"{RED}[Reviews] Error for {uid}: {e} - review stays in queue{WHITE}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                time.sleep(random.uniform(3.0, 5.0))

        browser.close()
        print(f"\n{CYAN}{'='*50}{WHITE}")
        print(f"{GREEN}[Reviews] DONE: {done}/{total} reviews submitted{WHITE}")
        print(f"{CYAN}{'='*50}{WHITE}")


def main():
    run_reviews_mode()


if __name__ == "__main__":
    main()


def run_dp_feedback_mode():
    """Mode 3 with DP, per account: cookie-open -> DP from file ->
    feedback post -> next ID. DP apply verified live 2026-10-31
    (same apply_dp_on_page); Yes button verified visible on Global
    Food Hub 2026-11-02 (read-only check, Sophia). Rules: no proxy,
    no generation; IDs open via cookie ONLY (a dead cookie skips the
    account, no password fallback); a review is consumed ONLY when
    actually posted - failed login / closed route / already-reviewed
    leaves the review in the queue for the next working account."""
    from automation.dp_apply import (
        FB_PROFILE_URL, _goto_profile, _is_logged_in, _wait_for_pic,
        apply_dp_on_page, detect_gender, has_custom_dp,
        parse_cookie_string, pick_dp, read_profile_name, record_used,
        used_file_path,
    )
    accounts = read_lines(os.path.join(get_output_dir(), "browser_accounts.txt"))
    reviews = read_lines(os.path.join(get_base_storage_dir(), "reviews.txt"))
    if not accounts:
        print(f"{RED}No accounts in output/browser_accounts.txt{WHITE}")
        return
    if not reviews:
        print(f"{RED}No reviews in reviews.txt - paste client list there{WHITE}")
        return
    # Use every review in the file - no prompt.
    need = len(reviews)
    reviews = reviews[:need]
    try:
        gap = int(input(
            f"{CYAN}Gap between accounts in seconds [60] {WHITE}"
        ).strip() or "60")
    except Exception:
        gap = 60
    gap = max(0, min(gap, 300))
    page_url = input(f"{CYAN}Paste Facebook Page Link and press Enter: {WHITE}").strip()
    if not page_url:
        print(f"{RED}No link given{WHITE}")
        return
    print(f"{CYAN}Page: {page_url}{WHITE}")
    print(f"{CYAN}Accounts: {len(accounts)}, Reviews: {len(reviews)}{WHITE}")

    queue = list(reviews)  # next review to post is queue[0]
    done = dp_done = 0
    with sync_playwright() as p:
        _exe = os.path.expandvars(
            r"C:\Users\Rizvi Lion\AppData\Local\ms-playwright\chromium-1243\chrome-win\chrome.exe"
        )
        _launch_kwargs = dict(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        _lk = dict(_launch_kwargs)
        if os.path.exists(_exe):
            _lk["executable_path"] = _exe
        browser = p.chromium.launch(**_lk)  # DIRECT - no proxy
        for i, acc_line in enumerate(accounts):
            if not queue:
                break  # every review posted
            if i > 0:
                time.sleep(gap)
            parts = acc_line.split("|")
            uid = parts[0]
            cookie_str = parts[2] if len(parts) > 2 else ""
            if not cookie_str:
                print(f"{RED}[Reviews] No cookies for {uid}, skipping "
                      f"- review stays in queue{WHITE}")
                continue
            print(f"\n{CYAN}--- Account: {uid} ---{WHITE}")
            context = browser.new_context()
            cookies = parse_cookie_string(cookie_str, "facebook.com")
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            try:
                if not _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
                    print(f"{RED}[Reviews] Profile did not load for {uid} "
                          f"- review stays in queue{WHITE}")
                    continue
                _human_pause(1.0, 2.0)
                if not _is_logged_in(page, context):
                    # Cookie dead -> UID+password fallback in the
                    # SAME open browser/page.
                    _pwd = parts[1] if len(parts) > 1 else ""
                    _ok = False
                    if _pwd:
                        print(f"{YELLOW}[Reviews] Cookie failed for {uid} - trying password login{WHITE}")
                        try:
                            from automation.dp_apply import password_login
                            _st = password_login(page, uid, _pwd)
                            if _st == "submitted" and _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
                                _human_pause(1.0, 2.0)
                                _ok = _is_logged_in(page, context)
                        except Exception as e:
                            print(f"{RED}[Reviews] Password login error for {uid}: {e}{WHITE}")
                    if not _ok:
                        print(f"{RED}[Reviews] Login failed for {uid} "
                              f"- review stays in queue{WHITE}")
                        continue
                print(f"{GREEN}[Reviews] Logged in: {uid}{WHITE}")
                # DP first (same verified steps as dp_apply.process_account)
                name = read_profile_name(page)
                if not _wait_for_pic(page):
                    _goto_profile(page, FB_PROFILE_URL.format(uid=uid))
                    _human_pause(1.0, 2.0)
                    _wait_for_pic(page)
                if has_custom_dp(page):
                    print(f"{YELLOW}[DP] {name or uid}: already has DP - skipped{WHITE}")
                else:
                    gender, method = detect_gender(page, uid, name)
                    _goto_profile(page, FB_PROFILE_URL.format(uid=uid))
                    _human_pause(1.0, 2.0)
                    picked = pick_dp(name, gender)
                    if picked:
                        res = apply_dp_on_page(page, picked["path"])
                        if res["ok"]:
                            record_used(used_file_path(), picked["path"])
                            dp_done += 1
                            print(f"{GREEN}[DP] {name or uid}: applied "
                                  f"({os.path.basename(picked['path'])}){WHITE}")
                        else:
                            print(f"{YELLOW}[DP] {name or uid}: FAILED - {res['detail']}{WHITE}")
                    else:
                        print(f"{YELLOW}[DP] {name or uid}: no pic - add photos to "
                              f"dp_pics/{gender or 'male/female'}/{WHITE}")
                # Feedback next, on the SAME page/context
                review = queue[0]
                result = submit_review(page, page_url, review)
                if result is True:
                    queue.pop(0)
                    done += 1
                    print(f"{GREEN}[Reviews] Review submitted for {uid}{WHITE}")
                elif result == "already":
                    print(f"{YELLOW}[Reviews] {uid} already reviewed "
                          f"- review stays in queue{WHITE}")
                else:
                    print(f"{RED}[Reviews] Review FAILED for {uid} "
                          f"- review stays in queue{WHITE}")
            except Exception as e:
                print(f"{RED}[Reviews] Error for {uid}: {e} "
                      f"- review stays in queue{WHITE}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass
        browser.close()
        print(f"\n{CYAN}{'='*50}{WHITE}")
        print(f"{GREEN}[Reviews] DONE: {done}/{len(reviews)} reviews posted, "
              f"{dp_done} DPs applied{WHITE}")
        if queue:
            print(f"{YELLOW}[Reviews] {len(queue)} review(s) left unposted "
                  f"- no more working accounts{WHITE}")
        print(f"{CYAN}{'='*50}{WHITE}")
