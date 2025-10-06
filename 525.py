
import streamlit as st
import pandas as pd
import os
import tempfile
import re
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import json

# Custom CSS for UI/UX
st.markdown("""
<style>
    .main { background-color: #f0f2f6; padding: 20px; }
    .stButton>button { background-color: #4CAF50; color: white; border-radius: 8px; padding: 10px 20px; font-size: 16px; transition: all 0.3s ease; }
    .stButton>button:hover { background-color: #45a049; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
    .stTextInput, .stFileUploader { border: 2px dashed #d3d3d3; border-radius: 8px; padding: 10px; }
    .stExpander { background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .stSuccess { background-color: #e6f3e6; padding: 10px; border-radius: 8px; }
    .stWarning { background-color: #fff4e6; padding: 10px; border-radius: 8px; }
    .stError { background-color: #ffe6e6; padding: 10px; border-radius: 8px; }
    .stInfo { background-color: #e6f0ff; padding: 10px; border-radius: 8px; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Arial', sans-serif; }
    .sidebar .sidebar-content { background-color: #2c3e50; color: white; }
</style>
""", unsafe_allow_html=True)

# App Title and Description
st.title("📊 User Consistency Checker (Google Drive)")
st.markdown("""
This app authenticates with Google Drive, processes Excel files from the 'summary' subfolder of a provided folder link, and compares user IDs with an uploaded CSV.
""")

# Authentication
@st.cache_resource
def authenticate_drive():
    try:
        client_secrets = {
            "installed": {
                "client_id": "597141289794-q48ejlatd71q0el3tko70chje91rkbu2.apps.googleusercontent.com",
                "project_id": "upheld-producer-454005-t3",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": "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",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(client_secrets, f)
            client_secrets_path = f.name

        gauth = GoogleAuth()
        gauth.settings['client_config_file'] = client_secrets_path
        gauth.settings['oauth_scope'] = ['https://www.googleapis.com/auth/drive']
        gauth.LoadClientConfigFile(client_secrets_path)
        if 'GOOGLE_CREDENTIALS' in st.secrets:
            creds_dict = {
                "client_id": st.secrets["GOOGLE_CREDENTIALS"]["client_id"],
                "client_secret": st.secrets["GOOGLE_CREDENTIALS"]["client_secret"],
                "refresh_token": st.secrets["GOOGLE_CREDENTIALS"]["refresh_token"],
                "access_token": None
            }
            gauth.credentials = gauth.AuthFromCredentialsDict(creds_dict)
        else:
            st.error("❌ Missing Google Drive credentials in Streamlit secrets. Configure GOOGLE_CREDENTIALS.")
            return None

        drive = GoogleDrive(gauth)
        st.success("✅ Google Drive authenticated!")
        os.unlink(client_secrets_path)
        return drive
    except Exception as e:
        st.error(f"❌ Authentication failed: {e}")
        return None

# Extract Folder ID
def extract_folder_id(drive_link):
    pattern = r"(?:folders/|id=)([a-zA-Z0-9_-]+)"
    match = re.search(pattern, drive_link)
    if not match:
        st.error("❌ Invalid Google Drive folder link.")
        return None
    return match.group(1)

# Process Summary Users
def check_summary_users(drive, folder_id, result):
    try:
        main_folder = drive.CreateFile({"id": folder_id})
        main_folder.FetchMetadata()
        folder_name = main_folder["title"]
        st.subheader(f"📁 Processing folder: {folder_name}")

        all_files = drive.ListFile({"q": f"'{folder_id}' in parents and trashed=false"}).GetList()
        folder_map = {f["title"].lower(): f["id"] for f in all_files if f["mimeType"] == "application/vnd.google-apps.folder"}

        if "summary" not in folder_map:
            st.warning("⚠️ No 'summary' subfolder found.")
            return

        summary_id = folder_map["summary"]
        summary_files = drive.ListFile({"q": f"'{summary_id}' in parents and trashed=false"}).GetList()

        with tempfile.TemporaryDirectory() as temp_dir:
            for f in summary_files:
                if f["title"].endswith((".xlsx", ".xls")):
                    file_name = f["title"]
                    f_path = os.path.join(temp_dir, file_name)
                    f.GetContentFile(f_path)

                    try:
                        sheets = pd.read_excel(f_path, sheet_name=None, engine="openpyxl")
                    except Exception as e:
                        st.error(f"❌ Could not read {file_name}: {e}")
                        continue

                    users_sheet_name = None
                    for sname in sheets.keys():
                        if sname.strip().lower() == "users":
                            users_sheet_name = sname
                            break

                    if not users_sheet_name:
                        st.warning(f"⚠️ No 'Users' sheet in {file_name}")
                        continue

                    users_df = sheets[users_sheet_name]
                    algo = users_df["ALGO"].unique() if "ALGO" in users_df.columns else []
                    server = users_df["SERVER"].unique() if "SERVER" in users_df.columns else []

                    if len(algo) > 1:
                        st.error(f"❌ {file_name}: {len(algo)} invalid algos.")
                    if len(server) > 1:
                        st.error(f"❌ {file_name}: {len(server)} invalid servers.")

                    if "UserID" not in users_df.columns:
                        st.warning(f"⚠️ 'UserID' column missing in {file_name}")
                        continue

                    all_users = set(users_df["UserID"].astype(str).str.strip().tolist())
                    st.info(f"ℹ️ Found {len(all_users)} users in '{users_sheet_name}'")

                    if algo:
                        filtered_users = result[result["algo"] == algo[0]]["userId"].tolist()[0] if not result[result["algo"] == algo[0]].empty else []
                        same_elements = set(filtered_users) == all_users
                        if same_elements:
                            st.success(f"✅ {file_name}: Users match AlgoUI")
                        else:
                            st.warning(f"⚠️ {file_name}: Users do not match AlgoUI")
                            missing_from_csv = all_users - set(filtered_users)
                            extra_in_csv = set(filtered_users) - all_users
                            if missing_from_csv:
                                st.markdown("**Missing from CSV:** " + ", ".join(sorted(missing_from_csv)))
                            if extra_in_csv:
                                st.markdown("**Extra in CSV:** " + ", ".join(sorted(extra_in_csv)))
                    else:
                        st.warning("⚠️ No ALGO in Users sheet.")

                    with st.expander(f"Detailed Checks for {file_name}", expanded=True):
                        for sheet_name, df in sheets.items():
                            if sheet_name == users_sheet_name:
                                continue

                            if "User ID" not in df.columns:
                                st.info(f"ℹ️ Skipping '{sheet_name}' (no User ID)")
                                continue

                            present_users = set(df["User ID"].dropna().astype(str).str.strip().tolist())

                            missing = all_users - present_users
                            if missing:
                                for m in sorted(missing):
                                    st.warning(f"⚠️ User {m} missing in '{sheet_name}'")

                            extra = present_users - all_users
                            if extra:
                                for e in sorted(extra):
                                    st.warning(f"⚠️ User {e} extra in '{sheet_name}'")

                            if not missing and not extra:
                                st.success(f"✅ Users match in '{sheet_name}'")
    except Exception as e:
        st.error(f"❌ Folder processing error: {e}")

# Main Logic
st.header("1. Enter Google Drive Folder Link")
drive_link = st.text_input("Folder link:", placeholder="https://drive.google.com/drive/folders/...")
folder_id = None
if drive_link:
    folder_id = extract_folder_id(drive_link)
    if folder_id:
        st.success("✅ Valid link!")

st.header("2. Upload Running Users CSV")
csv_file = st.file_uploader("Upload running-users.csv", type=["csv"])

if csv_file and folder_id:
    try:
        df = pd.read_csv(csv_file)
        st.success("✅ CSV uploaded!")
        st.subheader("CSV Preview")
        st.dataframe(df.head(), use_container_width=True)

        result = df.groupby(["algo", "server"])["userId"].apply(list).reset_index()
        st.subheader("Grouped Users by Algo/Server")
        st.dataframe(result, use_container_width=True)

        st.header("3. Process Files")
        if st.button("🔍 Process", type="primary"):
            with st.spinner("Processing..."):
                drive = authenticate_drive()
                if drive:
                    check_summary_users(drive, folder_id, result)
                    st.success("🎉 Complete!")
    except Exception as e:
        st.error(f"❌ CSV error: {e}")
else:
    st.info("ℹ️ Provide link and CSV to proceed.")

