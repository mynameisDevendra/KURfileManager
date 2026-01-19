import streamlit as st
import io
import base64
# --- NEW IMPORT ADDED HERE ---
from streamlit_pdf_viewer import pdf_viewer 
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# --- AUTHENTICATION ---
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

# --- HELPER: GET CONTENT FOR PREVIEW ---
def get_preview_content(file_id, mime_type):
    """
    Downloads file content specifically for previewing.
    Returns: (data_bytes, type_category)
    """
    service = get_drive_service()
    if not service: return None, "error"

    try:
        # CATEGORY 1: Google Docs (Export to Text)
        if 'application/vnd.google-apps' in mime_type:
            request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return fh.getvalue().decode('utf-8')[:2000], "text" 

        # CATEGORY 2: Images or PDFs (Download binary)
        elif 'image/' in mime_type or 'application/pdf' in mime_type:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            if 'image/' in mime_type:
                return fh.getvalue(), "image"
            else:
                return fh.getvalue(), "pdf"

        else:
            return "Preview not supported for this file type.", "text"

    except Exception as e:
        return f"Error loading preview: {str(e)}", "text"

# --- HELPER: GET FOLDERS ---
def get_shared_folders():
    service = get_drive_service()
    if not service: return {}
    results = service.files().list(
        q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        pageSize=50, 
        fields="files(id, name)"
    ).execute()
    return {f['name']: f['id'] for f in results.get('files', [])}

# --- SEARCH FUNCTION ---
def search_drive(query_text, specific_folder_id=None):
    service = get_drive_service()
    if not service: return []
    
    search_query = f"fullText contains '{query_text}' and trashed = false"
    if specific_folder_id:
        search_query += f" and '{specific_folder_id}' in parents"
    
    try:
        response = service.files().list(
            q=search_query,
            pageSize=15, 
            fields="files(id, name, mimeType, webContentLink, webViewLink, exportLinks)"
        ).execute()
        return response.get('files', [])
            
    except Exception as e:
        st.error(f"API Error: {e}")
        return []

# --- UI LAYOUT ---
st.set_page_config(page_title="Doc Search", layout="wide")
st.title("📂 Intelligent File Search")

# SIDEBAR
with st.sidebar:
    st.header("Settings")
    available_folders = get_shared_folders()
    if available_folders:
        folder_options = ["All Shared Folders"] + list(available_folders.keys())
        selected_option = st.selectbox("Search Scope", folder_options)
        target_folder_id = available_folders.get(selected_option)
    else:
        st.warning("No shared folders found.")
        target_folder_id = None

# SEARCH BAR
col1, col2 = st.columns([4, 1])
with col1:
    search_term = st.text_input("Search", placeholder="Enter keyword...", label_visibility="collapsed")
with col2:
    search_btn = st.button("Search", type="primary", use_container_width=True)

st.divider()

# RESULTS
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if search_btn and search_term:
    with st.spinner("Searching..."):
        st.session_state.search_results = search_drive(search_term, target_folder_id)

if st.session_state.search_results:
    for file in st.session_state.search_results:
        f_id = file['id']
        f_name = file['name']
        f_mime = file['mimeType']
        
        # Determine Download Link
        dl_link = file.get('webContentLink')
        if not dl_link and 'exportLinks' in file and 'application/pdf' in file['exportLinks']:
            dl_link = file['exportLinks']['application/pdf']
        
        with st.expander(f"📄 {f_name}"):
            tab1, tab2 = st.tabs(["Details", "👀 Preview"])
            
            # TAB 1: DETAILS
            with tab1:
                st.write(f"**Type:** {f_mime}")
                if dl_link:
                    st.markdown(f"[📥 **Direct Download Link**]({dl_link})")
                else:
                    st.info("Direct download not available. Use preview.")

            # TAB 2: PREVIEW
            with tab2:
                if st.button(f"Load Preview", key=f"prev_{f_id}"):
                    with st.spinner("Downloading file for preview..."):
                        content, content_type = get_preview_content(f_id, f_mime)
                        
                        if content_type == "image":
                            st.image(content, caption=f_name, use_container_width=True)
                            
                        elif content_type == "pdf":
                            # Use the professional viewer function
                            pdf_viewer(input=content, width=700, height=800)
                            
                        elif content_type == "text":
                            st.text_area("Content Snippet", content, height=300)
                            
                        else:
                            st.error(content)