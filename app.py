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
import concurrent.futures
import threading

# --- 1. CONFIGURATION ---
MAJOR_PROVIDERS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com"}
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "tempmail.com", "throwaway.com"}
ROLE_PREFIXES = {"info", "sales", "support", "admin", "jobs", "marketing", "billing"}
GARBAGE_PATTERNS = {"???", "test", "n/a", "unknown", "asdf", "none", "null", "missing", "user"}

SUBSCRIBER_ROW_LIMIT = 50000

# --- 2. CACHING ENGINE ---
# Thread-safe cache to ensure we never query the same domain's DNS/SMTP twice
domain_cache = {}
cache_lock = threading.Lock()

def get_domain_network_info(domain, premium_features):
    """Fetches MX and Catch-All data for a domain, using a cache to prevent rate-limits."""
    with cache_lock:
        if domain in domain_cache:
            return domain_cache[domain]
            
    info = {'mx_ok': False, 'catch_all': False, 'google_hosted': False, 'error': None}
    
    # Check 1: DNS & MX Records
    try:
        records = dns.resolver.resolve(domain, 'MX')
        info['mx_ok'] = True
        
        # Check if the domain is hosted on Google Workspace
        for rec in records:
            if "google" in rec.exchange.to_text().lower():
                info['google_hosted'] = True
                break
        mx_record = str(records[0].exchange)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        info['error'] = "No active mail server"
        with cache_lock:
            domain_cache[domain] = info
        return info
    except Exception:
        info['error'] = "DNS query issue"
        with cache_lock:
            domain_cache[domain] = info
        return info

    # Check 2: Catch-All Testing (Port 25)
    if premium_features.get("catch_all_check"):
        try:
            server = smtplib.SMTP(timeout=3)
            server.connect(mx_record)
            server.helo(server.local_hostname)
            server.mail('hello@yourdomain.com')
            
            # Send a fake string to test if the server accepts everything
            random_string = ''.join(random.choices(string.ascii_lowercase, k=20))
            fake_email = f"{random_string}@{domain}"
            
            code, message = server.rcpt(str(fake_email))
            server.quit()
            
            if code == 250:
                info['catch_all'] = True
        except Exception:
            pass # Ignore timeouts to prevent app crashing; assume false if we can't verify
            
    with cache_lock:
        domain_cache[domain] = info
    return info


# --- 3. CORE VALIDATION PIPELINE ---
def suggest_corrected_domain(domain):
    domain_lower = domain.lower()
    for provider in MAJOR_PROVIDERS:
        if domain_lower == provider:
            return domain_lower
        similarity = difflib.SequenceMatcher(None, domain_lower, provider).ratio()
        if 0.85 < similarity < 1.0:
            return provider
    return domain_lower

def process_single_email(email_address, premium_features):
    """The master function that processes a single email. Safe for threading."""
    if pd.isna(email_address):
        return {"status": "Invalid", "reason": "Missing Email", "email": ""}
        
    email_str = str(email_address).strip()
    
    # Step 1: Structural & Syntax Check (Fast Local)
    try:
        email_info = validate_email(email_str, check_deliverability=False)
        domain = email_info.domain.lower()
        local_part = email_info.local_part
        normalized_email = email_info.normalized
    except EmailNotValidError as e:
        return {"status": "Invalid", "reason": f"Syntax Error: {str(e)}", "email": email_str}

    # Step 2: Auto-Correct & Blocklists (Fast Local)
    corrected_domain = suggest_corrected_domain(domain)
    action_taken_note = ""
    if corrected_domain != domain:
        if premium_features.get("auto_correct"):
            action_taken_note = f" (Auto-corrected from @{domain})"
            domain = corrected_domain
            normalized_email = f"{local_part}@{domain}"
        else:
            return {"status": "Invalid", "reason": "Known squatter typo (Upgrade to auto-correct)", "email": normalized_email}

    if domain in DISPOSABLE_DOMAINS:
        return {"status": "Risky", "reason": "Disposable email provider", "email": normalized_email}
    if local_part.lower() in ROLE_PREFIXES:
        return {"status": "Risky", "reason": "Generic corporate role account", "email": normalized_email}

    # Step 3: Domain Network Verification (Cached)
    dom_info = get_domain_network_info(domain, premium_features)
    
    if not dom_info['mx_ok']:
        return {"status": "Invalid", "reason": f"{dom_info.get('error')}{action_taken_note}", "email": normalized_email}
        
    if dom_info['catch_all']:
        return {"status": "Risky", "reason": f"Catch-All Domain{action_taken_note}", "email": normalized_email}

    # Step 4: Deep Web Footprint Verification (Port 443)
    if premium_features.get("deep_verify"):
        email_clean = normalized_email.lower()
        email_hash = hashlib.md5(email_clean.encode('utf-8')).hexdigest()
        
        try: # Gravatar check
            gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404"
            res = requests.get(gravatar_url, timeout=3)
            if res.status_code == 200:
                return {"status": "Valid", "reason": f"Verified: Live profile found on Gravatar network{action_taken_note}", "email": normalized_email}
        except Exception:
            pass 

        if dom_info['google_hosted'] or domain == "gmail.com":
            try: # Google Account API check
                google_url = "https://accounts.google.com/InputValidator?resource=SignUp"
                payload = {"input01": {"Input": "GmailAddress", "GmailAddress": local_part, "FirstName": "", "LastName": ""}}
                headers = {"User-Agent": "Mozilla/5.0"}
                res = requests.post(google_url, json=payload, headers=headers, timeout=3)
                if res.status_code == 200:
                    if res.json().get("input01", {}).get("Valid") != "Valid":
                        return {"status": "Valid", "reason": f"Verified: Active Google/Workspace account{action_taken_note}", "email": normalized_email}
                    else:
                        return {"status": "Invalid", "reason": f"Inbox does not exist on Google servers{action_taken_note}", "email": normalized_email}
            except Exception:
                pass

    return {"status": "Valid", "reason": f"Passed all basic checks{action_taken_note}", "email": normalized_email}


# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Local Lead Optimizer", page_icon="📊", layout="wide")
st.title("Lead List Optimizer")
st.markdown("Clean, correct, and verify your B2B lead lists locally.")
st.divider()

if 'is_premium' not in st.session_state:
    st.session_state.is_premium = False
if 'license_tier' not in st.session_state:
    st.session_state.license_tier = "Free"
if 'stored_key' not in st.session_state:
    st.session_state.stored_key = ""
if 'verified_id' not in st.session_state:
    st.session_state.verified_id = ""

st.sidebar.header("🔑 App Licensing")

if not st.session_state.is_premium:
    st.sidebar.markdown("Upgrade to unlock full features.")
    license_key = st.sidebar.text_input("Enter Gumroad License Key:", type="password")
    
    if st.sidebar.button("Unlock Pro"):
        if license_key:
            with st.spinner("Verifying license..."):
                SINGLE_PASS_ID = "e9-PrA6mmjgQ2x8uIKf8Tg=="
                MONTHLY_SUBSCRIBER_ID = "_w9Q8UOe8il7Mmnz1Kpwig=="
                
                detected_tier = None
                target_id = ""
                debug_info = []
                
                # Monthly Subscription
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

                # Single Pass
                if not detected_tier:
                    try:
                        res = requests.post("https://api.gumroad.com/v2/licenses/verify", 
                                            data={
                                                "product_id": SINGLE_PASS_ID, 
                                                "license_key": license_key, 
                                                "increment_uses_count": "true"
                                            })
                        data = res.json()
                        debug_info.append(f"Single Pass Response: {data}")
                        
                        if res.status_code == 200 and data.get("success"):
                            detected_tier = "Single Pass"
                            target_id = SINGLE_PASS_ID
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
                    with st.sidebar.expander("Debug Logs"):
                        st.write(debug_info)
        else:
            st.sidebar.warning("Please enter a key.")
else:
    tier_label = "👑 Pro Subscriber" if st.session_state.license_tier == "Subscriber" else "Single Pass"
    st.sidebar.success(f"Account: {tier_label}")

# --- MAIN APP ENGINES ---
uploaded_file = st.file_uploader("Drop your messy lead list CSV here", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    initial_row_count = len(df)
    
    st.subheader("Original Preview")
    st.dataframe(df.head(5), use_container_width=True)
    
    df.columns = df.columns.str.strip().str.lower()
    email_col = 'email' if 'email' in df.columns else None
    
    if not email_col:
        st.error("Could not find an 'email' column.")
    else:
        is_allowed = True
        if st.session_state.license_tier == "Free":
            st.warning("Enter a valid key in the sidebar to unlock cleaning.")
            is_allowed = False
        elif st.session_state.license_tier == "Single Pass" and initial_row_count > 10000:
            st.error("Single Pass limited to 10,000 rows.")
            is_allowed = False
        elif st.session_state.license_tier == "Subscriber" and initial_row_count > 50000:
            st.error("Subscriber limited to 50,000 rows.")
            is_allowed = False

        if is_allowed:
            if st.button("Process List", type="primary"):
                # Clear domain cache at the start of a new run
                domain_cache.clear()
                
                # Setup UI placeholders for streaming progress
                progress_text = st.empty()
                progress_bar = st.progress(0)
                
                initial_count = len(df)
                
                # --- PHASE 1: Fast String Hygiene ---
                for col in df.select_dtypes(include=['object']).columns:
                    df[col] = df[col].astype(str).str.strip()

                garbage_removed = 0
                df = df.dropna(subset=[email_col])
                df = df[df[email_col] != ""]
                for col in df.columns:
                    normalized_col = col.replace('_', ' ').strip()
                    if normalized_col in ['first name', 'last name', 'name']:
                        df = df[~df[col].str.lower().isin(GARBAGE_PATTERNS)]
                garbage_removed = initial_count - len(df)
                
                # Ensure validation columns exist
                df['validation_status'] = ""
                df['validation_reason'] = ""

                # --- PHASE 2: Threaded Network Checks ---
                premium_settings = {"auto_correct": True, "catch_all_check": True, "deep_verify": True}
                total_emails = len(df)
                completed = 0
                
                # Execute 20 network requests concurrently
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    # Map the dataframe index to the running thread
                    future_to_idx = {
                        executor.submit(process_single_email, row[email_col], premium_settings): idx 
                        for idx, row in df.iterrows()
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        try:
                            res = future.result()
                        except Exception as exc:
                            res = {"status": "Unverified", "reason": f"System error: {str(exc)}", "email": df.at[idx, email_col]}
                            
                        # Safely inject the results back into the dataframe
                        df.at[idx, 'validation_status'] = res['status']
                        df.at[idx, 'validation_reason'] = res['reason']
                        df.at[idx, email_col] = res['email']
                        
                        completed += 1
                        
                        # Update progress bar smoothly
                        if completed % 10 == 0 or completed == total_emails:
                            progress_bar.progress(completed / total_emails)
                            progress_text.text(f"Processed {completed} of {total_emails} leads...")

                # --- PHASE 3: Final Cleanup ---
                post_hygiene_count = len(df)
                df = df.drop_duplicates(subset=[email_col], keep='first')
                duplicates_removed = post_hygiene_count - len(df)
                
                # UI Clean up
                progress_text.empty()
                progress_bar.empty()
                st.success("🎉 Processing Complete!")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Rows Output", len(df))
                col2.metric("Garbage Dropped", garbage_removed)
                col3.metric("Duplicates Removed", duplicates_removed)
                col4.metric("Valid Leads", len(df[df['validation_status'] == 'Valid']))
                    
                st.subheader("Cleaned Data")
                st.dataframe(df, use_container_width=True)
                
                csv_bytes = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download Cleaned CSV", data=csv_bytes, file_name="cleaned_leads.csv", mime="text/csv", use_container_width=True)
