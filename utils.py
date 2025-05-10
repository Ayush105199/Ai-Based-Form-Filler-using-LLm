# 
import fitz  # PyMuPDF
import google.generativeai as genai
import os
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
import json
import re
import tempfile
from unstructured.partition.pdf import partition_pdf
from dotenv import load_dotenv
import logging
from pdf2image import convert_from_path
import pytesseract
import streamlit as st
from PIL import Image
import pdfplumber
from PyPDF2 import PdfReader


def extract_form_fields(pdf_path):
    reader = PdfReader(pdf_path)
    fields = reader.get_form_text_fields()
    return fields


def extract_text_and_images(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        content = []
        for page in pdf.pages:
            text = page.extract_text()
            images = page.images
            content.append({"text": text, "images": images})
        return content

API_KEY = 'AIzaSyAHRamYbFmNDZXqZ8QdFjSYW5mWHW-5FNQ'
# Update this if you're on Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_text_with_ocr(pdf_path):
    try:
        images = convert_from_path(pdf_path)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"OCR extraction failed: {e}")
        return ""


def extract_text_from_pdf(file_path):
    elements = partition_pdf(
        filename=file_path,
        strategy="hi_res",           # enables OCR
        ocr_languages="eng",         # change as needed
    )
    return [el.text for el in elements if el.text.strip()]


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.environ["API_KEY"])

def call_llm(prompt):
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(prompt)
    return response.text


def check_pdf_basic_properties(pdf_path):
    """Uses PyMuPDF to check basic PDF properties before heavy processing."""
    try:
        doc = fitz.open(pdf_path)
        props = {
            "page_count": len(doc),
            "is_encrypted": doc.is_encrypted,
            "needs_password": doc.needs_pass,
            "has_any_text_layer": any(page.get_text("text").strip() for page in doc if len(doc) > 0),
            "metadata": doc.metadata,
        }
        logger.info(f"Basic PDF properties for '{pdf_path}': {props}")
        doc.close()
        return props
    except Exception as e:
        logger.error(f"PyMuPDF basic check failed for {pdf_path}: {e}",exc_info=True)
        return {"error": str(e), "is_likely_corrupted": True}


def get_acroform_fields(pdf_path):
    """Extracts AcroForm fields from a PDF."""
    try:
        doc = fitz.open(pdf_path)
        fields = {}
        if not doc.is_pdf: # Check if it's even a PDF
            logger.warning(f"'{pdf_path}' may not be a valid PDF file.")
            doc.close()
            return None

        for page_num in range(len(doc)):
            page = doc[page_num]
            for field in page.widgets():
                fields[field.field_name] = {
                    "value": field.field_value,
                    "rect": field.rect,
                    "type": field.field_type,
                    "options": field.choice_values if field.field_type in [fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX] else None
                }
        doc.close()
        logger.info(f"Found {len(fields)} AcroForm fields in '{pdf_path}'.")
        return fields if fields else None
    except Exception as e:
        logger.error(f"Error extracting AcroForm fields from '{pdf_path}': {e}", exc_info=True)
        return None
    
# ... (fill_acroform_pdf remains the same) ...
def fill_acroform_pdf(input_pdf_path, output_pdf_path, data_dict):
    """Fills AcroForm fields in a PDF and saves it."""
    try:
        doc = fitz.open(input_pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            for field in page.widgets():
                if field.field_name in data_dict:
                    if field.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                        val_lower = str(data_dict[field.field_name]).lower()
                        if val_lower in ["yes", "true", "checked", "on", "x"]:
                            field.field_value = True
                        else:
                            field.field_value = False
                    elif field.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                        if field.choice_values and data_dict[field.field_name] in field.choice_values:
                             field.field_value = data_dict[field.field_name]
                        elif str(data_dict[field.field_name]).lower() in ["yes", "true", "selected", field.choice_values[0] if field.choice_values else "NEVER_MATCH"]:
                            field.field_value = True
                    else:
                        field.field_value = str(data_dict[field.field_name])
                    field.update()
        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        logger.error(f"Error filling PDF '{input_pdf_path}': {e}", exc_info=True)
        return False


def extract_text_elements_unstructured(pdf_path):
    """Extracts text elements using unstructured.io, with enhanced logging and explicit OCR."""
    logger.info(f"Starting text extraction for (unstructured): '{pdf_path}'")

    # Perform basic PDF check first
    basic_props = check_pdf_basic_properties(pdf_path)
    if basic_props.get("is_likely_corrupted") or basic_props.get("is_encrypted"):
        logger.error(f"PDF '{pdf_path}' seems corrupted or is encrypted. Aborting unstructured extraction.")
        return []

    extracted_elements_unstructured = []
    try:
        # Strategy 'hi_res' attempts to use models like Detectron2 for layout and PaddleOCR for text.
        # Explicitly setting ocr_languages helps ensure OCR is attempted for image-based PDFs.
        # Make sure paddlepaddle (and paddleocr) are installed: pip install paddlepaddle paddleocr
        logger.info(f"Attempting unstructured.io partition_pdf with strategy='hi_res', ocr_languages='eng' for '{pdf_path}'.")
        elements = partition_pdf(
            filename=pdf_path,
            strategy="hi_res",
            infer_table_structure=True,
            ocr_languages="eng",  # Ensure OCR is attempted for English. Add other langs if needed: "eng+fra"
            # For debugging, you can try other strategies:
            # strategy="ocr_only", # Forces OCR on all pages. Good for purely scanned PDFs.
            # strategy="fast", # Faster, less accurate, might not use complex models.
        )
        extracted_elements_unstructured = elements
        logger.info(f"unstructured.io (hi_res) processing for '{pdf_path}' found {len(elements)} raw elements.")
        if not elements and not basic_props.get("has_any_text_layer"):
            logger.warning(f"Unstructured (hi_res) found no elements AND PyMuPDF found no text layer for '{pdf_path}'. "
                           "This strongly suggests an image-only PDF where OCR might have failed or dependencies are missing.")
            logger.warning("Please ensure PaddleOCR and its dependencies (like paddlepaddle) are correctly installed.")


    except Exception as e:
        logger.error(f"Critical error during unstructured.io (hi_res) for '{pdf_path}': {e}", exc_info=True)
        logger.info(f"Attempting fallback: unstructured.io with strategy='ocr_only' for '{pdf_path}'.")
        try:
            elements = partition_pdf(
                filename=pdf_path,
                strategy="ocr_only", # Good for scanned documents
                ocr_languages="eng",
            )
            extracted_elements_unstructured = elements
            logger.info(f"unstructured.io (ocr_only strategy) for '{pdf_path}' found {len(elements)} raw elements.")
            if not elements:
                 logger.warning(f"Unstructured (ocr_only) also found no elements for '{pdf_path}'. OCR likely failed.")

        except Exception as e2:
            logger.error(f"Critical error during unstructured.io (ocr_only fallback) for '{pdf_path}': {e2}", exc_info=True)
            # No elements found by unstructured, proceed to PyMuPDF basic text extraction
            extracted_elements_unstructured = []


    # Process elements found by unstructured.io
    if extracted_elements_unstructured:
        text_elements_for_llm = []
        

        for el_idx, el in enumerate(extracted_elements_unstructured):
            if hasattr(el, 'text') and el.text.strip():
                 text_content = el.text.strip().replace("\n", " ")  # Normalize newlines
                 is_potential_label = False
                 if 1 < len(text_content) < 100:
                      if text_content.endswith(':'):
                          is_potential_label = True
                      elif el.category in ["Title", "ListItem", "Header", "Footer", "Address"] and len(text_content) < 60:
                          is_potential_label = True
                      elif el.category in ["NarrativeText", "UncategorizedText"]:
                #     logger.debug(f"Filtered out element for LLM: '{text_content[:50]}' (category: {el.category}) from '{pdf_path}'")
        
                           if not text_elements_for_llm and extracted_elements_unstructured:
                                 logger.warning(f"Unstructured.io found {len(extracted_elements_unstructured)} elements for '{pdf_path}', "
                                 "but all were filtered out by label heuristics. Consider broadening criteria or inspect raw elements.")
        
        # Deduplication
        unique_texts = {}
        for item in text_elements_for_llm:
            if item['text'] not in unique_texts:
                unique_texts[item['text']] = item
        
        final_elements = list(unique_texts.values())
        logger.info(f"Returning {len(final_elements)} unique text elements from unstructured.io processing for '{pdf_path}'.")
        return final_elements

    # If unstructured.io yielded nothing, try PyMuPDF's simpler text extraction (NO OCR CAPABILITY HERE)
    logger.info(f"Unstructured.io yielded no processable elements for '{pdf_path}'. "
                "Falling back to PyMuPDF's basic text layer extraction (this does NOT perform OCR).")
    try:
        doc = fitz.open(pdf_path)
        pymupdf_text_elements = []
        if not doc.is_pdf:
            logger.warning(f"'{pdf_path}' may not be a valid PDF for PyMuPDF fallback.")
            doc.close()
            return []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # page.get_text("text") is simpler than blocks for just getting lines
            text_page = page.get_text("text")
            if text_page and text_page.strip():
                lines = text_page.split('\n')
                for line in lines:
                    clean_line = line.strip()
                    # Basic filter for potential labels from simple text extraction
                    if 1 < len(clean_line) < 100:
                         pymupdf_text_elements.append({"text": clean_line, "category": "fitz_line_extract"})
            # else:
            #    logger.info(f"PyMuPDF: Page {page_num+1} in '{pdf_path}' has no extractable text layer.")
        doc.close()

        if not pymupdf_text_elements:
            logger.warning(f"PyMuPDF fallback also found no text elements in '{pdf_path}'. "
                           "If this was an image-only PDF, this is expected as PyMuPDF's basic text extraction does not OCR.")
        
        unique_texts_pymupdf = {}
        for item in pymupdf_text_elements:
            if item['text'] not in unique_texts_pymupdf:
                unique_texts_pymupdf[item['text']] = item
        
        final_pymupdf_elements = list(unique_texts_pymupdf.values())
        logger.info(f"PyMuPDF fallback extracted {len(final_pymupdf_elements)} unique text lines from '{pdf_path}'.")
        return final_pymupdf_elements

    except Exception as e2:
        logger.error(f"PyMuPDF fallback extraction failed for '{pdf_path}': {e2}", exc_info=True)
        return []
    
logger = logging.getLogger(__name__)

def get_llm_mappings(pdf_field_texts, user_profile_keys, form_type_hint=""):
    """Uses Gemini LLM to map PDF fields to user profile keys."""

    if not os.environ.get("API_KEY"):
        logger.error("Google API key not found.")
        return {"error": "Google API key not found."}

    if not pdf_field_texts:
        logger.warning("No PDF field texts provided to LLM for mapping.")
        return {"info": "No PDF field texts available to map."}

    if not user_profile_keys:
        logger.warning("No user profile keys provided for mapping.")
        return {"info": "No profile keys available to map to."}

    # Truncate if needed
    MAX_FIELD_TEXTS_FOR_PROMPT = 150
    if len(pdf_field_texts) > MAX_FIELD_TEXTS_FOR_PROMPT:
        logger.warning(f"Too many PDF field texts ({len(pdf_field_texts)}), truncating.")
        pdf_field_texts_for_prompt = pdf_field_texts[:MAX_FIELD_TEXTS_FOR_PROMPT]
    else:
        pdf_field_texts_for_prompt = pdf_field_texts

    prompt_system = "You are an intelligent assistant helping to map PDF form fields to structured user profile keys."

    prompt_user = f"""
{prompt_system}

PDF Form Text Elements (first {len(pdf_field_texts_for_prompt)} shown if truncated):
{json.dumps(pdf_field_texts_for_prompt, indent=2)}

User Profile Data Keys:
{json.dumps(user_profile_keys, indent=2)}

{form_type_hint}

Instructions:
- Map each PDF field label (as key) to the most relevant profile key (as value).
- Use "NOMATCH" if there’s no suitable match.
- Combine multiple keys with commas if needed.
- Respond only with a valid JSON object.
Example:
{{
  "Full Name": "firstName, lastName",
  "Date of Birth": "dob",
  "Signature": "NOMATCH"
}}

Now provide the mapping as a valid JSON object:
"""

genai.configure(api_key=API_KEY)

# Streamlit UI
st.title("LLM JSON Mapper")

prompt_user = st.text_area("Enter your prompt for the LLM:", height=200)

if st.button("Generate Response"):
    if not prompt_user.strip():
        st.warning("Please enter a prompt.")
    else:
        try:
            model = genai.GenerativeModel("model/gemini-2.0-flash")
            response = model.generate_content(prompt_user)
            response_text = response.text.strip()

            try:
                parsed_content = json.loads(response_text)
                st.success(f"LLM successfully mapped {len(parsed_content)} fields.")
                st.json(parsed_content)
            except json.JSONDecodeError as je:
                logger.error(f"LLM response was not valid JSON: {je}. Response text: {response_text}", exc_info=True)
                st.error(f"JSON parsing error: {je}")
                st.text_area("Raw LLM Response", response_text, height=300)

        except Exception as e:
            logger.exception("LLM API call failed.")
            st.error(f"LLM API call failed: {e}")

def prepare_data_for_filling(mappings, user_profile_data):
    """Prepares the data dictionary for PDF filling based on LLM mappings."""
    data_to_fill = {}
    if not isinstance(mappings, dict):  # Guard against non-dict mappings
        logger.error(f"Cannot prepare data for filling, mappings is not a dictionary: {mappings}")
        return {}

    for pdf_field, profile_key_or_keys in mappings.items():
        if profile_key_or_keys != "NOMATCH" and profile_key_or_keys is not None:
            if isinstance(profile_key_or_keys, str) and ',' in profile_key_or_keys:
                keys = [k.strip() for k in profile_key_or_keys.split(',')]
                value_parts = []
                for k_single in keys:
                    if k_single in user_profile_data:
                        value_parts.append(str(user_profile_data.get(k_single, '')))
                    else:
                        logger.warning(
                            f"Profile key '{k_single}' (part of combined key '{profile_key_or_keys}') "
                            f"not found in user profile for PDF field '{pdf_field}'."
                        )
                value = " ".join(value_parts).strip()
            else:
                if profile_key_or_keys in user_profile_data:
                    value = user_profile_data.get(profile_key_or_keys, '')
                else:
                    value = ''  # Default to empty if key not found
                    logger.warning(
                        f"Profile key '{profile_key_or_keys}' not found in user profile for PDF field '{pdf_field}'."
                    )

            data_to_fill[pdf_field] = value
    return data_to_fill




