import streamlit as st
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# --- AUTHENTICATION ---
@st.cache_resource
def get_drive_service():
    """Authenticates using local file OR Streamlit Secrets."""
    creds = None
    if "gcp_service_account" in st.secrets:
        service_account_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES)
    else:
        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        except FileNotFoundError:
            st.error("❌ credentials.json not found!")
            return None
    return build('drive', 'v3', credentials=creds)

# --- HELPER: GET CONTENT ---
def get_file_content(file_id, mime_type):
    """Downloads a snippet of the file text for preview."""
    service = get_drive_service()
    try:
        if 'google-apps' in mime_type:
            # It's a Google Doc, we must Export it as plain text
            request = service.files().export_media(fileId=file_id, mimeType='text/plain')
        else:
            # It's a regular file (txt, csv), we get the content directly
            # Note: This is complex for PDFs/Images, so we skip them for simple text preview
            return "Preview not available for binary files (PDF/Images) in this version."
            
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        return fh.getvalue().decode('utf-8')[:500] + "..." # Limit to first 500 chars
    except Exception as e:
        return f"Could not load preview: {str(e)}"

# --- HELPER: GET SHARED FOLDERS ---
def get_shared_folders():
    service = get_drive_service()
    if not service: return {}
    query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, pageSize=50, fields="files(id, name)").execute()
    return {f['name']: f['id'] for f in results.get('files', [])}

# --- SEARCH FUNCTION ---
def search_drive(query_text, specific_folder_id=None):
    service = get_drive_service()
    results = []
    search_query = f"fullText contains '{query_text}' and trashed = false"
    if specific_folder_id:
        search_query += f" and '{specific_folder_id}' in parents"
    
    try:
        response = service.files().list(
            q=search_query,
            pageSize=20, # Keep it low for speed
            fields="files(id, name, mimeType, parents, webContentLink, webViewLink, exportLinks)"
        ).execute()
        
        files = response.get('files', [])
        
        for file in files:
            dl_link = file.get('webContentLink')
            view_link = file.get('webViewLink')
            if not dl_link: 
                if 'exportLinks' in file and 'application/pdf' in file['exportLinks']:
                    dl_link = file['exportLinks']['application/pdf']
                else:
                    dl_link = view_link

            results.append({
                "ID": file.get('id'),
                "File Name": file.get('name'),
                "Type": file.get('mimeType'),
                "Action": dl_link,
                "View": view_link
            })
            
    except Exception as e:
        st.error(f"API Error: {e}")
    return results

# --- UI LAYOUT ---
st.set_page_config(page_title="Doc Search", layout="wide")
st.title("📂 Intelligent File Search System")

# SIDEBAR
with st.sidebar:
    st.header("Settings")
    available_folders = get_shared_folders()
    folder_options = ["All Shared Folders"] + list(available_folders.keys())
    selected_option = st.selectbox("Search Scope", folder_options)
    target_folder_id = None
    if selected_option != "All Shared Folders":
        target_folder_id = available_folders[selected_option]

# MAIN SEARCH
st.markdown("### Search")
with st.container():
    col1, col2 = st.columns([4, 1])
    with col1:
        search_term = st.text_input("Enter keyword", placeholder="e.g. Invoice...", label_visibility="collapsed")
    with col2:
        search_btn = st.button("Search", type="primary", use_container_width=True)

st.divider()

# RESULTS
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if search_btn and search_term:
    with st.spinner(f"Scanning '{selected_option}'..."):
        st.session_state.search_results = search_drive(search_term, target_folder_id)

if st.session_state.search_results:
    data = st.session_state.search_results
    st.success(f"Found {len(data)} documents.")
    
    for item in data:
        with st.expander(f"📄 {item['File Name']}"):
            
            # Create Tabs inside the expander
            tab1, tab2 = st.tabs(["Details & Actions", "👀 Text Preview"])
            
            with tab1:
                c1, c2, c3 = st.columns([1, 1, 1])
                c1.write(f"**Type:** {item['Type'].split('/')[-1]}")
                c2.markdown(f"[📥 **Download File**]({item['Action']})")
                c3.markdown(f"[↗️ **Open in Drive**]({item['View']})")
            
            with tab2:
                # Only load preview if user clicks this tab (Lazy Loading button)
                if st.button(f"Load Preview for {item['File Name']}", key=item['ID']):
                    with st.spinner("Fetching content..."):
                        content = get_file_content(item['ID'], item['Type'])
                        st.text_area("Content Snippet", content, height=200)