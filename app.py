import streamlit as st
import json
import os
from utils import (
    get_acroform_fields,
    fill_acroform_pdf,
    extract_text_elements_unstructured,
    get_llm_mappings,
    prepare_data_for_filling
)
import streamlit as st
from utils import extract_form_fields

uploaded_file = st.file_uploader("Upload a fillable PDF", type="pdf")

if uploaded_file:
    with open("temp.pdf", "wb") as f:
        f.write(uploaded_file.read())

    st.success("Fillable PDF (AcroForm) detected")

    fields = extract_form_fields("temp.pdf")

    if fields:
        st.subheader("Extracted Form Fields")
        st.json(fields)
    else:
        st.warning("No form fields found.")
   

# --- App Configuration ---


# --- Session State Initialization ---
if 'user_profile' not in st.session_state:
    st.session_state.user_profile = {}
if 'pdf_path' not in st.session_state:
    st.session_state.pdf_path = None
if 'acroform_fields' not in st.session_state:
    st.session_state.acroform_fields = None
if 'extracted_texts' not in st.session_state:
    st.session_state.extracted_texts = None
if 'llm_mappings' not in st.session_state:
    st.session_state.llm_mappings = None
if 'filled_pdf_path' not in st.session_state:
    st.session_state.filled_pdf_path = None
if 'processing_mode' not in st.session_state: # "acroform" or "unstructured"
    st.session_state.processing_mode = None


# --- Helper to load sample profile ---
def load_sample_profile():
    try:
        with open("sample_profile.json", 'r') as f:
            return json.dumps(json.load(f), indent=2)
    except FileNotFoundError:
        return "{}"

# --- UI ---
st.title("📄 LLM-Powered Form Filler")
st.markdown("""
Upload a PDF form and provide your user profile data (as JSON).
The LLM will attempt to map your profile data to the form fields.
**Note:** For non-fillable PDFs, this tool will extract text elements and suggest mappings.
Directly filling non-fillable PDFs by overlaying text is highly complex and not fully implemented here.
""")

# --- Sidebar for Inputs ---
with st.sidebar:
    st.header("⚙️ Inputs")
    
    # 1. User Profile
    st.subheader("1. User Profile Data (JSON)")
    if st.button("Load Sample Profile"):
        st.session_state.user_profile_json_str = load_sample_profile()
    
    user_profile_json_str = st.text_area(
        "Paste your JSON profile here:",
        value=st.session_state.get('user_profile_json_str', load_sample_profile()),
        height=250
    )
    try:
        st.session_state.user_profile = json.loads(user_profile_json_str)
        st.success("Profile JSON loaded successfully!")
    except json.JSONDecodeError:
        st.error("Invalid JSON format in profile data.")
        st.session_state.user_profile = {}

    # 2. PDF Upload
    st.subheader("2. Upload PDF Form")
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

    if uploaded_file:
        # Save uploaded file temporarily to pass its path to processing functions
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        st.session_state.pdf_path = os.path.join(temp_dir, uploaded_file.name)
        with open(st.session_state.pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Uploaded '{uploaded_file.name}'")

    # 3. Form Type Hint (Bonus)
    st.subheader("3. Form Type (Optional Hint)")
    form_type_options = ["Generic", "KYC Form", "Tax Form (e.g., W-9, 1040)", "Visa Application"]
    form_type_hint = st.selectbox("Select form type if known:", form_type_options)
    
    custom_hint = st.text_input("Or provide a custom hint (e.g., 'Invoice details')")
    final_form_hint = ""
    if custom_hint:
        final_form_hint = f"The form is related to: {custom_hint}."
    elif form_type_hint != "Generic":
        final_form_hint = f"This is a {form_type_hint}."


    # 4. Process Button
    st.subheader("4. Process Form")
    if st.button("🚀 Analyze and Map Fields", disabled=(not uploaded_file or not st.session_state.user_profile)):
        st.session_state.llm_mappings = None # Reset previous mappings
        st.session_state.filled_pdf_path = None # Reset previous filled PDF

        with st.spinner("Processing PDF and mapping fields... This may take a moment."):
            # --- PDF Processing Logic ---
            # Try AcroForm extraction first
            st.session_state.acroform_fields = get_acroform_fields(st.session_state.pdf_path)

            if st.session_state.acroform_fields:
                st.session_state.processing_mode = "acroform"
                st.success("Fillable PDF (AcroForm) detected!")

                if st.session_state.acroform_fields:
                    st.subheader("📝 Extracted AcroForm Fields from PDF")
                    st.json(st.session_state.acroform_fields)

                pdf_field_names = list(st.session_state.acroform_fields.keys())
                st.session_state.llm_mappings = get_llm_mappings(
                    pdf_field_names,
                    list(st.session_state.user_profile.keys()),
                    form_type_hint=final_form_hint
                )
            else:
                st.session_state.processing_mode = "unstructured"
                st.info("Not a fillable AcroForm or no fields found. Attempting text extraction for mapping...")
                st.session_state.extracted_texts = extract_text_elements_unstructured(st.session_state.pdf_path)
                if st.session_state.extracted_texts:
                    # Get just the text for the LLM
                    text_labels_for_llm = [item['text'] for item in st.session_state.extracted_texts]
                    st.session_state.llm_mappings = get_llm_mappings(
                        text_labels_for_llm,
                        list(st.session_state.user_profile.keys()),
                        form_type_hint=final_form_hint
                    )
                else:
                    st.error("Could not extract any text elements from the PDF.")

# --- Main Area for Displaying Results ---
if st.session_state.get('llm_mappings'):
    st.header("📊 LLM Field Mappings")

    if "error" in st.session_state.llm_mappings:
        st.error(f"LLM Mapping Error: {st.session_state.llm_mappings['error']}")
    else:
        st.success("Mappings generated successfully!")
        
        col1, col2, col3 = st.columns(3)
        col1.subheader("PDF Field/Text")
        col2.subheader("➡️ Mapped Profile Key")
        col3.subheader("👤 Profile Value")

        data_to_fill_preview = prepare_data_for_filling(st.session_state.llm_mappings, st.session_state.user_profile)

        for pdf_field, profile_key in st.session_state.llm_mappings.items():
            if profile_key != "NOMATCH" and profile_key is not None : # Show only mapped fields
                col1.text(pdf_field)
                col2.text(profile_key)
                
                # Get the actual value that would be filled
                value_to_show = ""
                if isinstance(profile_key, str) and ',' in profile_key:
                    keys = [k.strip() for k in profile_key.split(',')]
                    value_to_show = " ".join([str(st.session_state.user_profile.get(k, '')) for k in keys]).strip()
                else:
                    value_to_show = st.session_state.user_profile.get(profile_key, "KEY_NOT_FOUND")
                
                col3.text(value_to_show)
            elif profile_key == "NOMATCH": # Optionally show NOMATCH fields
                with st.expander(f"Unmatched: {pdf_field}"):
                    st.caption("LLM indicated NOMATCH for this field.")


        # --- Fill PDF Button (only for AcroForms for now) ---
        if st.session_state.processing_mode == "acroform" and st.session_state.acroform_fields:
            st.header("✍️ Fill PDF")
            if st.button("Generate Filled PDF"):
                with st.spinner("Filling PDF..."):
                    output_pdf_name = f"filled_{os.path.basename(st.session_state.pdf_path)}"
                    output_pdf_path_temp = os.path.join("temp_uploads", output_pdf_name)
                    
                    data_for_filling = {}
                    # AcroForm fields are the keys from get_acroform_fields
                    # LLM mappings use these keys if it was an AcroForm
                    for acro_field_name in st.session_state.acroform_fields.keys():
                        # The LLM might have mapped this acro_field_name directly
                        # or it might have mapped a more descriptive label that *is* this acro_field_name.
                        # For simplicity here, we assume LLM output keys match acro_field_name if it's an Acroform.
                        # A more robust solution would be to map LLM output keys back to original acro_field_name if they differ.
                        mapped_profile_key = st.session_state.llm_mappings.get(acro_field_name)
                        
                        if mapped_profile_key and mapped_profile_key != "NOMATCH":
                            if isinstance(mapped_profile_key, str) and ',' in mapped_profile_key:
                                keys = [k.strip() for k in mapped_profile_key.split(',')]
                                value = " ".join([str(st.session_state.user_profile.get(k, '')) for k in keys]).strip()
                            else:
                                value = st.session_state.user_profile.get(mapped_profile_key, '')
                            data_for_filling[acro_field_name] = value
                    
                    success = fill_acroform_pdf(st.session_state.pdf_path, output_pdf_path_temp, data_for_filling)
                    if success:
                        st.session_state.filled_pdf_path = output_pdf_path_temp
                        st.success(f"PDF filled successfully! Path: {st.session_state.filled_pdf_path}")
                    else:
                        st.error("Failed to fill PDF.")

        elif st.session_state.processing_mode == "unstructured":
            st.info("""
            **Filling Non-Fillable PDFs:**
            For non-fillable (scanned/flat) PDFs, automatic filling by overlaying text is complex and error-prone 
            due to the need for precise coordinate detection and font matching.
            
            **Suggested Next Steps:**
            1. Review the mappings above.
            2. Manually fill the form using the suggested values.
            3. (Advanced) One could extend this to attempt text overlay using libraries like PyMuPDF or ReportLab,
               but it would require significant effort in visual element detection and coordinate mapping.
            """)
            # For demonstration, one could generate a text file with the mappings
            if st.button("Download Mappings as Text"):
                text_content = "LLM Form Filler Mappings:\n\n"
                for pdf_field, profile_key in st.session_state.llm_mappings.items():
                    if profile_key != "NOMATCH" and profile_key is not None:
                        value_to_show = ""
                        if isinstance(profile_key, str) and ',' in profile_key:
                            keys = [k.strip() for k in profile_key.split(',')]
                            value_to_show = " ".join([str(st.session_state.user_profile.get(k, '')) for k in keys]).strip()
                        else:
                            value_to_show = st.session_state.user_profile.get(profile_key, "KEY_NOT_FOUND")
                        text_content += f'"{pdf_field}": "{value_to_show}" (from profile key: {profile_key})\n'
                
                st.download_button(
                    label="Download Mappings (.txt)",
                    data=text_content,
                    file_name=f"mappings_{os.path.basename(st.session_state.pdf_path)}.txt",
                    mime="text/plain"
                )


    if st.session_state.get('filled_pdf_path'):
        with open(st.session_state.filled_pdf_path, "rb") as f:
            st.download_button(
                label="Download Filled PDF",
                data=f,
                file_name=os.path.basename(st.session_state.filled_pdf_path),
                mime="application/pdf"
            )

elif st.session_state.get('pdf_path') and not st.session_state.get('llm_mappings'):
    if st.session_state.processing_mode == "acroform" and not st.session_state.acroform_fields:
         st.warning("Could not extract AcroForm fields, though it might be a fillable PDF. Try processing for text extraction.")
    elif st.session_state.processing_mode == "unstructured" and not st.session_state.extracted_texts:
        st.error("Failed to extract text elements from the PDF for mapping. The PDF might be empty, image-only without OCR, or corrupted.")


# --- Cleanup old temp files (optional, for a long-running app) ---
# You might add a more robust cleanup mechanism if this were a deployed service.

# import streamlit as st
# import json
# import os
# from dotenv import load_dotenv
# import google.generativeai as genai

# load_dotenv()
# genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
# from utils import (
#     get_acroform_fields,
#     fill_acroform_pdf,
#     extract_text_elements_unstructured,
#     get_llm_mappings,
#     prepare_data_for_filling,
#     check_pdf_basic_properties # Import the new helper
# )
# import os
# os.environ["STREAMLIT_WATCHER_IGNORE_MODULES"] = "1"

# import logging # Ensure logging is available in app.py too

# logger = logging.getLogger(__name__) # Get logger for app.py

# # --- App Configuration ---
# st.set_page_config(page_title="LLM Form Filler", layout="wide")

# # ... (Session State Initialization remains the same) ...
# if 'user_profile' not in st.session_state:
#     st.session_state.user_profile = {}
# if 'pdf_path' not in st.session_state:
#     st.session_state.pdf_path = None
# if 'pdf_basic_props' not in st.session_state: # To store basic props
#     st.session_state.pdf_basic_props = None
# if 'acroform_fields' not in st.session_state:
#     st.session_state.acroform_fields = None
# if 'extracted_texts' not in st.session_state:
#     st.session_state.extracted_texts = None
# if 'llm_mappings' not in st.session_state:
#     st.session_state.llm_mappings = None
# if 'filled_pdf_path' not in st.session_state:
#     st.session_state.filled_pdf_path = None
# if 'processing_mode' not in st.session_state:
#     st.session_state.processing_mode = None


# # --- Helper to load sample profile ---
# def load_sample_profile():
#     try:
#         with open("sample_profile.json", 'r') as f:
#             return json.dumps(json.load(f), indent=2)
#     except FileNotFoundError:
#         return "{}"

# # --- UI ---
# st.title("📄 LLM-Powered Form Filler")
# st.markdown("""
# Upload a PDF form and provide your user profile data (as JSON).
# The LLM will attempt to map your profile data to the form fields.
# *Note:* For non-fillable PDFs, this tool will extract text elements and suggest mappings.
# Directly filling non-fillable PDFs by overlaying text is highly complex and not fully implemented here.
# """)

# # --- Sidebar for Inputs ---
# with st.sidebar:
#     st.header("⚙ Inputs")
    
#     # 1. User Profile
#     st.subheader("1. User Profile Data (JSON)")
#     if st.button("Load Sample Profile"):
#         st.session_state.user_profile_json_str = load_sample_profile()
    
#     user_profile_json_str = st.text_area(
#         "Paste your JSON profile here:",
#         value=st.session_state.get('user_profile_json_str', load_sample_profile()),
#         height=250
#     )
#     try:
#         st.session_state.user_profile = json.loads(user_profile_json_str)
#         if st.session_state.user_profile: # Check if it's not empty after loading
#              st.success("Profile JSON loaded successfully!")
#     except json.JSONDecodeError:
#         st.error("Invalid JSON format in profile data.")
#         st.session_state.user_profile = {}

#     # 2. PDF Upload
#     st.subheader("2. Upload PDF Form")
#     uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

#     if uploaded_file:
#         temp_dir = "temp_uploads"
#         os.makedirs(temp_dir, exist_ok=True)
#         # Reset states for new file
#         st.session_state.pdf_path = os.path.join(temp_dir, uploaded_file.name)
#         st.session_state.acroform_fields = None
#         st.session_state.extracted_texts = None
#         st.session_state.llm_mappings = None
#         st.session_state.filled_pdf_path = None
#         st.session_state.processing_mode = None
#         st.session_state.pdf_basic_props = None

#         with open(st.session_state.pdf_path, "wb") as f:
#             f.write(uploaded_file.getbuffer())
#         st.success(f"Uploaded '{uploaded_file.name}'")
#         # Perform basic check immediately after upload
#         st.session_state.pdf_basic_props = check_pdf_basic_properties(st.session_state.pdf_path)
#         if st.session_state.pdf_basic_props:
#             st.info(f"""
#             *PDF Quick Check:*
#             - Pages: {st.session_state.pdf_basic_props.get('page_count', 'N/A')}
#             - Encrypted: {st.session_state.pdf_basic_props.get('is_encrypted', 'N/A')}
#             - Has Text Layer (simple check): {st.session_state.pdf_basic_props.get('has_any_text_layer', 'N/A')}
#             """)
#             if st.session_state.pdf_basic_props.get('is_likely_corrupted'):
#                 st.error("The PDF seems corrupted based on initial check.")
#             elif st.session_state.pdf_basic_props.get('is_encrypted'):
#                 st.warning("The PDF is encrypted. Processing may fail or be limited.")


#     # 3. Form Type Hint (Bonus)
#     st.subheader("3. Form Type (Optional Hint)")
#     form_type_options = ["Generic", "KYC Form", "Tax Form (e.g., W-9, 1040)", "Visa Application", "Invoice"]
#     form_type_hint_selected = st.selectbox("Select form type if known:", form_type_options)
    
#     custom_hint = st.text_input("Or provide a custom hint (e.g., 'Client onboarding form')")
#     final_form_hint = ""
#     if custom_hint:
#         final_form_hint = f"The form is related to: {custom_hint}."
#     elif form_type_hint_selected != "Generic":
#         final_form_hint = f"This is a {form_type_hint_selected}."


#     # 4. Process Button
#     st.subheader("4. Analyze and Map")
#     if st.button("🚀 Analyze and Map Fields", disabled=(not st.session_state.get('pdf_path') or not st.session_state.user_profile or st.session_state.pdf_basic_props.get('is_likely_corrupted', False))):
#         st.session_state.llm_mappings = None
#         st.session_state.filled_pdf_path = None

#         with st.spinner("Processing PDF and mapping fields... This may take a moment. Check console for detailed logs."):
#             logger.info(f"Starting analysis for PDF: {st.session_state.pdf_path}")
            
#             st.session_state.acroform_fields = get_acroform_fields(st.session_state.pdf_path)

#             if st.session_state.acroform_fields:
#                 st.session_state.processing_mode = "acroform"
#                 logger.info("AcroForm detected. Proceeding with AcroForm field names.")
#                 st.success("Fillable PDF (AcroForm) detected!")
#                 pdf_field_names = list(st.session_state.acroform_fields.keys())
#                 st.session_state.llm_mappings = get_llm_mappings(
#                     pdf_field_names,
#                     list(st.session_state.user_profile.keys()),
#                     form_type_hint=final_form_hint
#                 )
#             else:
#                 st.session_state.processing_mode = "unstructured"
#                 logger.info("Not an AcroForm or no AcroForm fields found. Attempting text extraction with unstructured.io.")
#                 st.info("Not a fillable AcroForm or no fields found. Attempting text extraction for mapping...")
                
#                 st.session_state.extracted_texts = extract_text_elements_unstructured(st.session_state.pdf_path)
                
#                 if st.session_state.extracted_texts:
#                     logger.info(f"Successfully extracted {len(st.session_state.extracted_texts)} text elements via unstructured/fallback.")
#                     st.success(f"Extracted {len(st.session_state.extracted_texts)} potential text elements for mapping.")
#                     text_labels_for_llm = [item['text'] for item in st.session_state.extracted_texts]
#                     st.session_state.llm_mappings = get_llm_mappings(
#                         text_labels_for_llm,
#                         list(st.session_state.user_profile.keys()),
#                         form_type_hint=final_form_hint
#                     )
#                 else:
#                     logger.error(f"Failed to extract any text elements for PDF: {st.session_state.pdf_path} after all attempts.")
#                     st.error("""
#                     *Failed to extract any text elements from the PDF for mapping.*
#                     Please check the console logs where Streamlit is running for detailed error messages and diagnostics.
#                     Common reasons:
#                     1.  PDF is empty or severely corrupted.
#                     2.  PDF is image-only, and OCR processing (e.g., PaddleOCR via unstructured.io) failed.
#                         - Ensure paddlepaddle and paddleocr Python packages are installed: pip install paddlepaddle paddleocr
#                         - Check for OCR engine errors in the console log.
#                     3.  PDF is encrypted and cannot be processed.
#                     4.  No text elements matched the heuristics for being a "label" (less likely if OCR worked but still possible).
#                     """)
#     elif not st.session_state.get('pdf_path'):
#         st.sidebar.warning("Please upload a PDF file.")
#     elif not st.session_state.user_profile:
#         st.sidebar.warning("Please provide user profile JSON data.")
#     elif st.session_state.get('pdf_basic_props', {}).get('is_likely_corrupted'):
#         st.sidebar.error("The uploaded PDF appears corrupted. Cannot process.")


# # --- Main Area for Displaying Results ---
# if st.session_state.get('llm_mappings'):
#     st.header("📊 LLM Field Mappings")

#     if "error" in st.session_state.llm_mappings:
#         st.error(f"LLM Mapping Error: {st.session_state.llm_mappings['error']}")
#     elif "info" in st.session_state.llm_mappings: # Handle case where no fields were sent to LLM
#         st.info(f"LLM Info: {st.session_state.llm_mappings['info']}")
#     elif not st.session_state.llm_mappings : # Empty dictionary from LLM
#         st.warning("LLM returned no mappings. The extracted PDF text might not contain recognizable form fields or profile keys did not match.")
#     else:
#         st.success("Mappings generated successfully!")
        
#         # Prepare data for preview (and potential filling)
#         # This uses the LLM mappings, whether they came from Acroform keys or unstructured text
#         data_to_fill_preview = prepare_data_for_filling(st.session_state.llm_mappings, st.session_state.user_profile)
        
#         # Display mappings
#         # Use a list to collect display items to sort or better control layout
#         display_items = []
#         for pdf_field_text_from_llm_key, mapped_profile_key in st.session_state.llm_mappings.items():
#             if mapped_profile_key != "NOMATCH" and mapped_profile_key is not None:
#                 # Get the actual value that would be filled
#                 value_to_show = ""
#                 if isinstance(mapped_profile_key, str) and ',' in mapped_profile_key:
#                     keys = [k.strip() for k in mapped_profile_key.split(',')]
#                     value_to_show = " ".join([str(st.session_state.user_profile.get(k, f'[KEY {k} NOT FOUND]')) for k in keys]).strip()
#                 else:
#                     value_to_show = st.session_state.user_profile.get(mapped_profile_key, f"[KEY {mapped_profile_key} NOT FOUND]")
                
#                 display_items.append({
#                     "pdf_field": pdf_field_text_from_llm_key,
#                     "profile_key": mapped_profile_key,
#                     "profile_value": value_to_show
#                 })

#         if display_items:
#             col1, col2, col3 = st.columns(3)
#             col1.subheader("PDF Field/Text")
#             col2.subheader("➡ Mapped Profile Key")
#             col3.subheader("👤 Profile Value")
#             for item in display_items:
#                 col1.text(item["pdf_field"])
#                 col2.text(item["profile_key"])
#                 col3.text(item["profile_value"])
#         else:
#             st.info("LLM did not find any direct matches between PDF text and profile keys (excluding 'NOMATCH').")

#         # Show NOMATCH fields in an expander
#         nomatch_items = {k:v for k,v in st.session_state.llm_mappings.items() if v == "NOMATCH"}
#         if nomatch_items:
#             with st.expander(f"Unmatched PDF Text Elements ({len(nomatch_items)} items)"):
#                 for pdf_field, _ in nomatch_items.items():
#                     st.caption(pdf_field)


#         # --- Fill PDF Button (only for AcroForms for now) ---
#         if st.session_state.processing_mode == "acroform" and st.session_state.acroform_fields:
#             st.header("✍ Fill PDF (AcroForm)")
#             if st.button("Generate Filled AcroForm PDF"):
#                 with st.spinner("Filling PDF..."):
#                     output_pdf_name = f"filled_{os.path.basename(st.session_state.pdf_path)}"
#                     # Ensure temp_uploads exists for output
#                     os.makedirs("temp_uploads", exist_ok=True)
#                     output_pdf_path_temp = os.path.join("temp_uploads", output_pdf_name)
                    
#                     # Data for filling needs to map Acroform field names to values
#                     # The LLM was given Acroform field names, so its keys should match
#                     data_for_pymupdf_filling = {}
#                     for acro_field_name in st.session_state.acroform_fields.keys():
#                         # Get the profile key(s) mapped by the LLM for this acro_field_name
#                         mapped_profile_key = st.session_state.llm_mappings.get(acro_field_name)
                        
#                         if mapped_profile_key and mapped_profile_key != "NOMATCH":
#                             value_to_insert = ""
#                             if isinstance(mapped_profile_key, str) and ',' in mapped_profile_key:
#                                 keys = [k.strip() for k in mapped_profile_key.split(',')]
#                                 value_to_insert = " ".join([str(st.session_state.user_profile.get(k, '')) for k in keys]).strip()
#                             else:
#                                 value_to_insert = st.session_state.user_profile.get(mapped_profile_key, '')
#                             data_for_pymupdf_filling[acro_field_name] = value_to_insert
                    
#                     success = fill_acroform_pdf(st.session_state.pdf_path, output_pdf_path_temp, data_for_pymupdf_filling)
#                     if success:
#                         st.session_state.filled_pdf_path = output_pdf_path_temp
#                         st.success(f"PDF filled successfully! Path: {st.session_state.filled_pdf_path}")
#                     else:
#                         st.error("Failed to fill PDF. Check console logs for details.")

#         elif st.session_state.processing_mode == "unstructured":
#             st.info("""
#             *Non-Fillable PDF Mappings:*
#             The mappings above are based on text extracted from the PDF.
#             Automatic visual filling is not performed for these PDF types.
#             """)
#             if display_items and st.button("Download Mappings as Text"): # Only if there are items to download
#                 text_content = "LLM Form Filler Mappings:\n\n"
#                 for item in display_items:
#                     text_content += f'"{item["pdf_field"]}": "{item["profile_value"]}" (from profile key: {item["profile_key"]})\n'
                
#                 st.download_button(
#                     label="Download Mappings (.txt)",
#                     data=text_content,
#                     file_name=f"mappings_{os.path.basename(st.session_state.pdf_path)}.txt",
#                     mime="text/plain"
#                 )


#     if st.session_state.get('filled_pdf_path'):
#         with open(st.session_state.filled_pdf_path, "rb") as f:
#             st.download_button(
#                 label="Download Filled PDF",
#                 data=f,
#                 file_name=os.path.basename(st.session_state.filled_pdf_path),
#                 mime="application/pdf"
#             )

# elif st.session_state.get('pdf_path') and not st.session_state.get('processing_mode'): # Before processing button is clicked but file is uploaded
#     st.info("PDF uploaded. Configure profile and click 'Analyze and Map Fields'.")
#     from utils import check_pdf_basic_properties

# uploaded_file = st.file_uploader("Upload your PDF", type="pdf")
# if uploaded_file:
#     with st.spinner("Checking PDF..."):
#         info = check_pdf_basic_properties(uploaded_file)
#         st.json(info)



# --- Cleanup old temp files (very basic) ---
# Consider a more robust cleanup for a deployed app
# For example, on session end or after a certain time.
