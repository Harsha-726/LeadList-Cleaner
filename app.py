import streamlit as st
import pandas as pd
import dns.resolver
from email_validator import validate_email, EmailNotValidError
import hashlib
import requests
import difflib
import smtplib
import random
import string

# --- 1. CONFIGURATION, BLOCKLISTS & HYGIENE PATTERNS ---
MAJOR_PROVIDERS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com"}
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "tempmail.com", "throwaway.com"}
ROLE_PREFIXES = {"info", "sales", "support", "admin", "jobs", "marketing", "billing"}
GARBAGE_PATTERNS = {"???", "test", "n/a", "unknown", "asdf", "none", "null", "missing", "user"}

SUBSCRIBER_ROW_LIMIT = 50000
SINGLE_PASS_ROW_LIMIT = 10000

# --- 2. PREMIUM FEATURE ENGINES ---
def suggest_corrected_domain(domain):
    domain_lower = domain.lower()
    for provider in MAJOR_PROVIDERS:
        if domain_lower == provider:
            return domain_lower
        similarity = difflib.SequenceMatcher(None, domain_lower, provider).ratio()
        if 0.85 < similarity < 1.0:
            return provider
    return domain_lower

def is_catch_all_domain(domain):
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_record = str(records[0].exchange)
        server = smtplib.SMTP(timeout=3)
        server.connect(mx_record)
        server.helo(server.local_hostname)
        server.mail('hello@yourdomain.com')
        random_string = ''.join(random.choices(string.ascii_lowercase, k=20))
        fake_email = f"{random_string}@{domain}"
        code, message = server.rcpt(str(fake_email))
        server.quit()
        if code == 250:
            return True
    except Exception:
        pass
    return False

def check_web_footprint(email_str, domain):
    email_clean = email_str.strip().lower()
    email_hash = hashlib.md5(email_clean.encode('utf-8')).hexdigest()
    try:
        gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404"
        res = requests.get(gravatar_url, timeout=3)
        if res.status_code == 200:
            return "Valid", "Verified: Live profile found on Gravatar network"
    except Exception:
        pass 
    is_google_domain = domain.lower() == "gmail.com"
    if not is_google_domain:
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            for rec in mx_records:
                if "google" in rec.exchange.to_text().lower():
                    is_google_domain = True
                    break
        except Exception:
            pass
    if is_google_domain:
        try:
            google_url = "https://accounts.google.com/InputValidator?resource=SignUp"
            payload = {"input01": {"Input": "GmailAddress", "GmailAddress": email_clean.split('@')[0], "FirstName": "", "LastName": ""}}
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.post(google_url, json=payload, headers=headers, timeout=3)
            if res.status_code == 200:
                if res.json().get("input01", {}).get("Valid") != "Valid":
                    return "Valid", "Verified: Active Google/Workspace account"
                else:
                    return "Invalid", "Inbox does not exist on Google servers"
        except Exception:
            pass
    return "Valid", "Passed local structural & DNS checks"

# --- 3. MAIN VALIDATION LOOP ---
def verify_and_normalize_email(email_address, premium_features):
    if pd.isna(email_address):
        return "Invalid", "Missing Email", ""
    email_str = str(email_address).strip()
    try:
        email_info = validate_email(email_str, check_deliverability=False)
        domain = email_info.domain.lower()
        local_part = email_info.local_part
        normalized_email = email_info.normalized
    except EmailNotValidError as e:
        return "Invalid", f"Syntax Error: {str(e)}", email_str

    corrected_domain = suggest_corrected_domain(domain)
    action_taken_note = ""
    if corrected_domain != domain:
        if premium_features.get("auto_correct"):
            action_taken_note = f" (Auto-corrected from @{domain})"
            domain = corrected_domain
            normalized_email = f"{local_part}@{domain}"
        else:
            return "Invalid", "Known squatter typo (Upgrade to auto-correct)", normalized_email

    if domain in DISPOSABLE_DOMAINS:
        return "Risky", "Disposable email provider", normalized_email
    if local_part.lower() in ROLE_PREFIXES:
        return "Risky", "Generic corporate role account", normalized_email

    try:
        dns.resolver.resolve(domain, 'MX')
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return "Invalid", f"No active mail server{action_taken_note}", normalized_email
    except Exception:
        return "Unverified", f"DNS query issue{action_taken_note}", normalized_email

    if premium_features.get("catch_all_check"):
        if is_catch_all_domain(domain):
            return "Risky", f"Catch-All Domain{action_taken_note}", normalized_email

    if premium_features.get("deep_verify"):
        status, reason = check_web_footprint(normalized_email, domain)
        return status, reason + action_taken_note, normalized_email

    return "Valid", f"Passed all basic checks{action_taken_note}", normalized_email

# --- 4. STREAMLIT FRONTEND UI ---
st.set_page_config(page_title="Local Lead Optimizer", page_icon="📊", layout="wide")
st.title("Lead List Optimizer")
st.markdown("Clean, correct, and verify your B2B lead lists locally.")
st.markdown("Visit https://anakonda7.gumroad.com/l/kyjkoj to purchase.")
st.divider()

if 'is_premium' not in st.session_state:
    st.session_state.is_premium = False
if 'license_tier' not in st.session_state:
    st.session_state.license_tier = "Free"
if 'stored_key' not in st.session_state:
    st.session_state.stored_key = ""
if 'verified_id' not in st.session_state:
    st.session_state.verified_id = ""

st.sidebar.header("App Licensing")

if not st.session_state.is_premium:
    st.sidebar.markdown("Upgrade to unlock Auto-Correction, Catch-All Detection, and Web Verification.")
    license_key = st.sidebar.text_input("Enter Gumroad License Key:", type="password")
    
    if st.sidebar.button("Unlock Pro"):
        if license_key:
            with st.spinner("Verifying license..."):
                SINGLE_PASS_ID = "e9-PrA6mmjgQ2x8uIKf8Tg=="
                MONTHLY_SUBSCRIBER_ID = "_w9Q8UOe8il7Mmnz1Kpwig=="
                
                detected_tier = None
                target_id = ""
                debug_info = []
                
                # === FIXED: Monthly Subscription ===
                try:
                    res = requests.post("https://api.gumroad.com/v2/licenses/verify", 
                                        data={
                                            "product_id": MONTHLY_SUBSCRIBER_ID, 
                                            "license_key": license_key, 
                                            "increment_uses_count": "false"
                                        })
                    data = res.json()
                    debug_info.append(f"Monthly Sub Response: {data}")
                    
                    if res.status_code == 200 and data.get("success"):
                        p = data.get("purchase", {})
                        cancelled_at = p.get("subscription_cancelled_at")
                        failed_at = p.get("subscription_failed_at")
                        ended_at = p.get("subscription_ended_at")
                        
                        if not cancelled_at and not failed_at and not ended_at:
                            detected_tier = "Subscriber"
                            target_id = MONTHLY_SUBSCRIBER_ID
                except Exception as e:
                    debug_info.append(f"Monthly Sub Error: {str(e)}")

                # === HARDENED: Single Pass (Now truly one-time) ===
                if not detected_tier:
                    try:
                        # Increment use count during verification
                        res = requests.post("https://api.gumroad.com/v2/licenses/verify", 
                                            data={
                                                "product_id": SINGLE_PASS_ID, 
                                                "license_key": license_key, 
                                                "increment_uses_count": "true"   # ← Now increments on unlock
                                            })
                        data = res.json()
                        debug_info.append(f"Single Pass Response: {data}")
                        
                        if res.status_code == 200 and data.get("success"):
                            detected_tier = "Single Pass"
                            target_id = SINGLE_PASS_ID
                        else:
                            debug_info.append("Single Pass already used or invalid")
                    except Exception as e:
                        debug_info.append(f"Single Pass Error: {str(e)}")

                if detected_tier:
                    st.session_state.is_premium = True
                    st.session_state.license_tier = detected_tier
                    st.session_state.stored_key = license_key
                    st.session_state.verified_id = target_id
                    st.rerun()
                else:
                    st.sidebar.error("Key verification failed.")
                    with st.sidebar.expander("🛠️ Show API Debug Logs"):
                        st.write(debug_info)
        else:
            st.sidebar.warning("Please enter a key.")
else:
    tier_label = "👑 Pro Subscriber ($40/mo)" if st.session_state.license_tier == "Subscriber" else "🎟️ Single Sheet Pass ($15)"
    st.sidebar.success(f"Account: {tier_label}")

# --- SIDEBAR SETTINGS ---
st.sidebar.header("Core Settings")
dedup_toggle = st.sidebar.checkbox("Remove Duplicate Emails", value=True)
fix_names_toggle = st.sidebar.checkbox("Auto-Fix Name Capitalization", value=True)
drop_garbage_toggle = st.sidebar.checkbox("Filter Garbage Records (???, test, n/a)", value=True)

st.sidebar.header("Pro Features")
if st.session_state.is_premium:
    auto_correct = st.sidebar.checkbox("Auto-Correct Domain Typos", value=True)
    catch_all_check = st.sidebar.checkbox("Flag Catch-All Domains", value=True)
    deep_verify = st.sidebar.checkbox("Port-443 Web Verification", value=True)
else:
    auto_correct, catch_all_check, deep_verify = False, False, False

premium_settings = {"auto_correct": auto_correct, "catch_all_check": catch_all_check, "deep_verify": deep_verify}

# --- MAIN APP FLOW ---
uploaded_file = st.file_uploader("Drop your messy lead list CSV here", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    initial_row_count = len(df)
    
    st.subheader("Original File Preview")
    st.dataframe(df.head(5), use_container_width=True)
    
    df.columns = df.columns.str.strip().str.lower()
    email_col = 'email' if 'email' in df.columns else None
    
    if not email_col:
        st.error("Could not find an 'email' column.")
    else:
        is_allowed = True
        if st.session_state.license_tier == "Free":
            st.warning("Free preview mode. Enter a valid key in the sidebar to clean.")
            is_allowed = False
        elif st.session_state.license_tier == "Single Pass" and initial_row_count > SINGLE_PASS_ROW_LIMIT:
            st.error(f"Single Sheet limits files to {SINGLE_PASS_ROW_LIMIT} rows. Yours has {initial_row_count}.")
            is_allowed = False
        elif st.session_state.license_tier == "Subscriber" and initial_row_count > SUBSCRIBER_ROW_LIMIT:
            st.error(f"Subscription tier caps uploads at {SUBSCRIBER_ROW_LIMIT} rows.")
            is_allowed = False

        if is_allowed:
            if st.button("Process List", type="primary"):
                with st.spinner("Processing..."):
                    # No more increment here for Single Pass (already done at unlock)
                    
                    initial_count = len(df)
                    
                    for col in df.select_dtypes(include=['object']).columns:
                        df[col] = df[col].astype(str).str.strip()

                    garbage_removed = 0
                    if drop_garbage_toggle:
                        df = df.dropna(subset=[email_col])
                        df = df[df[email_col] != ""]
                        for col in df.columns:
                            normalized_col = col.replace('_', ' ').strip()
                            if normalized_col in ['first name', 'last name', 'name']:
                                df = df[~df[col].str.lower().isin(GARBAGE_PATTERNS)]
                        garbage_removed = initial_count - len(df)

                    if fix_names_toggle:
                        for col in df.columns:
                            normalized_col = col.replace('_', ' ').strip()
                            if normalized_col in ['first name', 'last name', 'name']:
                                df[col] = df[col].str.title()
                    
                    results = df[email_col].apply(lambda x: verify_and_normalize_email(x, premium_features=premium_settings))
                    df['validation_status'] = [r[0] for r in results]
                    df['validation_reason'] = [r[1] for r in results]
                    df[email_col] = [r[2] for r in results]
                    
                    post_hygiene_count = len(df)
                    if dedup_toggle:
                        df = df.drop_duplicates(subset=[email_col], keep='first')
                    duplicates_removed = post_hygiene_count - len(df)
                    
                st.success("🎉 Processing Complete!")
                
                if st.session_state.license_tier == "Single Pass":
                    st.session_state.is_premium = False
                    st.session_state.license_tier = "Free"
                    st.session_state.stored_key = ""
                    st.session_state.verified_id = ""
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Rows Output", len(df))
                col2.metric("Garbage Dropped", garbage_removed)
                col3.metric("Duplicates Removed", duplicates_removed)
                col4.metric("Valid Leads", len(df[df['validation_status'] == 'Valid']))
                    
                st.subheader("Cleaned Data")
                st.dataframe(df, use_container_width=True)
                
                csv_bytes = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download Cleaned CSV", data=csv_bytes, file_name="cleaned_leads.csv", mime="text/csv", use_container_width=True)
                
                st.rerun()
