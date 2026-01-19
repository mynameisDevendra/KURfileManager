import streamlit as st
import io
import base64
import pandas as pd
import docx  # NEW: Library for Word Files
from streamlit_pdf_viewer import pdf_viewer 
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# --- AUTHENTICATION ---
def get_drive_service():
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

# --- HELPER: GET FILE CONTENT ---
def get_file_content(file_id, mime_type):
    """Downloads file content to memory for Preview or Download."""
    service = get_drive_service()
    if not service: return None, "error"

    try:
        # 1. Google Docs/Sheets (Must Export)
        if 'application/vnd.google-apps' in mime_type:
            if 'spreadsheet' in mime_type:
                request = service.files().export_media(fileId=file_id, mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                dtype = "excel"
            elif 'document' in mime_type:
                request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
                dtype = "pdf"
            else:
                request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
                dtype = "pdf"

        # 2. Regular Files (Download as-is)
        else:
            request = service.files().get_media(fileId=file_id)
            if 'image' in mime_type: dtype = "image"
            elif 'pdf' in mime_type: dtype = "pdf"
            elif 'spreadsheet' in mime_type or 'excel' in mime_type: dtype = "excel"
            elif 'word' in mime_type or 'document' in mime_type: dtype = "word" # Detect Word
            elif 'text/plain' in mime_type: dtype = "text" # Detect Text
            else: dtype = "other"

        # Execute Download
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        return fh.getvalue(), dtype

    except Exception as e:
        return f"Error: {str(e)}", "error"

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
            fields="files(id, name, mimeType)"
        ).execute()
        return response.get('files', [])
    except Exception as e:
        st.error(f"API Error: {e}")
        return []

# --- UI LAYOUT ---
st.set_page_config(page_title="Doc Search", layout="wide")
st.title("📂 KUR File Manager")

# SIDEBAR
with st.sidebar:
    st.header("Select Folder")
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
        
        with st.expander(f"📄 {f_name}"):
            tab1, tab2 = st.tabs(["Details & Download", "👀 Preview"])
            
            # --- TAB 1: DOWNLOAD MANAGER ---
            with tab1:
                st.write(f"**Type:** {f_mime}")
                
                if st.button("📥 Prepare for Download", key=f"dl_btn_{f_id}"):
                    with st.spinner("Downloading..."):
                        content, dtype = get_file_content(f_id, f_mime)
                        
                        if dtype != "error":
                            # Determine file extension
                            ext = ".bin"
                            if dtype == "pdf": ext = ".pdf"
                            elif dtype == "excel": ext = ".xlsx"
                            elif dtype == "word": ext = ".docx"
                            elif dtype == "text": ext = ".txt"
                            elif dtype == "image": ext = ".jpg"
                            
                            final_name = f"{f_name}{ext}" if not f_name.endswith(ext) else f_name
                            
                            st.download_button(
                                label="✅ Save File",
                                data=content,
                                file_name=final_name,
                                mime=f_mime,
                                key=f"save_{f_id}"
                            )
                        else:
                            st.error("Download failed.")

            # --- TAB 2: PREVIEW MANAGER ---
            with tab2:
                if st.button(f"Load Preview", key=f"prev_{f_id}"):
                    with st.spinner("Loading preview..."):
                        content, dtype = get_file_content(f_id, f_mime)
                        
                        if dtype == "image":
                            st.image(content, caption=f_name, use_container_width=True)
                        elif dtype == "pdf":
                            pdf_viewer(input=content, width=700, height=800)
                        elif dtype == "excel":
                            try:
                                df = pd.read_excel(io.BytesIO(content))
                                st.dataframe(df)
                            except:
                                st.warning("Cannot read Excel file.")
                        elif dtype == "word":
                            try:
                                # Parse Word Document
                                doc = docx.Document(io.BytesIO(content))
                                full_text = []
                                for para in doc.paragraphs:
                                    full_text.append(para.text)
                                st.markdown('\n\n'.join(full_text))
                            except:
                                st.warning("Cannot read Word document.")
                        elif dtype == "text":
                            try:
                                # Decode Text File
                                text_content = content.decode("utf-8")
                                st.text_area("File Content", text_content, height=400)
                            except:
                                st.warning("Cannot read text file encoding.")
                        else:
                            st.info("Preview not available for this file type.")