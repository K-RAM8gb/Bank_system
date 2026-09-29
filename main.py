import os
import io
import re
import uuid
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, UploadFile, Form, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client
from dotenv import load_dotenv
from PIL import Image
import imagehash
import pytesseract
from google import genai
from google.genai import types
import hashlib


load_dotenv()

app = FastAPI(title="Payment Verification API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
os.makedirs("static/uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="static/uploads"), name="uploads")

@app.get("/payments")
def get_all_payments():
    """Fetches all payment submissions for the business dashboard."""
    # The syntax '*, orders(...)' performs a SQL JOIN in Supabase
    response = supabase.table("payments").select(
        "*, orders(customer_phone, expected_amount)"
    ).order("created_at", desc=True).execute()
    
    return response.data
url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

if not url or not key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in the .env file.")

supabase: Client = create_client(url, key)
gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
ai_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None
VISION_MODEL_ID = 'gemini-3.5-flash'

def get_image_hash(image_bytes: bytes) -> str:
    """Generates a strict SHA-256 hash to detect exact file re-uploads."""
    return hashlib.sha256(image_bytes).hexdigest()

def extract_payment_details(image_bytes: bytes) -> dict:
    """Runs local OCR and uses robust regex to find amounts, references, accounts, and dates."""
    img = Image.open(io.BytesIO(image_bytes))
    raw_text = pytesseract.image_to_string(img)
    
    # 1. AMOUNT: Looks for "Amount", "LKR", or "Rs" followed by the value
    amount_matches = re.findall(r'(?:Amount|LKR|Rs\.?)[\s:]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', raw_text, re.IGNORECASE)
    amount = float(amount_matches[0].replace(',', '')) if amount_matches else None
    
    # 2. REFERENCE: Handles "Reference Number:" explicitly 
    ref_matches = re.findall(r'(?:Transaction ID|Ref(?:erence)?(?:\s*Number|\s*No\.?)?|Txn ID|Transaction reference)[\s:-]*([A-Za-z0-9/-]+)', raw_text, re.IGNORECASE)
    valid_refs = [r.strip('-/') for r in ref_matches if any(char.isdigit() for char in r) and len(r) > 4]
    reference = valid_refs[0] if valid_refs else None
    
    # 3. ACCOUNT: 
    acc_matches_raw = re.findall(r'(?:Account(?: No| Number)?|A/C|To Account|To)[\s:]*([0-9*X]+(?:\s+[0-9*X]+)*)', raw_text, re.IGNORECASE)
    acc_matches = [acc.replace(' ', '') for acc in acc_matches_raw]
    
    # Use negative lookarounds (?<!...) and (?!...) to ensure the number is NOT touching a slash or dash
    standalone_accs = re.findall(r'(?<![/\-\.])\b(\d{9,16})\b(?![/\-\.])', raw_text)
    
    raw_accounts = acc_matches + standalone_accs
    
    # Filter out noise: Must be >3 chars AND must NOT be a part of the extracted reference
    accounts = list(set([
        acc for acc in raw_accounts 
        if len(acc) > 3 and (reference is None or acc not in reference)
    ]))
    
    # 4. DATE: Supports both DD-MM-YYYY and YYYY-MM-DD formats
    date_match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4}|\d{4}[-/]\d{2}[-/]\d{2})', raw_text)
    date_str = date_match.group(1) if date_match else None
    
    return {
        "raw_text": raw_text,
        "amount": amount,
        "reference": reference,
        "accounts": accounts,
        "date": date_str
    }
      
def analyze_slip_with_ai(image_bytes: bytes, expected_amount: float) -> dict:
    """Uses LLM Vision to extract data and detect fraud when standard OCR fails."""
    if not ai_client:
        return {"amount": None, "reference": None, "is_manipulated": False, "confidence": "low", "reason": "AI Client not configured."}

    img = Image.open(io.BytesIO(image_bytes))
    
    prompt = f"""
    Analyze this bank transfer slip. The expected amount is {expected_amount}.
    Return ONLY a JSON object. 
    Use this exact structure:
    {{
        "amount": 25000.00,
        "reference": "839201",
        "is_manipulated": false,
        "confidence": "high",
        "reason": "Clear image, extracted details."
    }}
    If a value is unreadable, use null. 
    CRITICAL: For "confidence", use "high" or "low" based ONLY on the visual clarity of the image. Do NOT set confidence to "low" just because the amount or account is wrong.
    """
    
    print("\n" + "="*40)
    print("🚀 SENDING DATA TO GEMINI AI (NEW SDK)")
    print("="*40)
    
    try:
        # New SDK syntax for generating content
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[prompt, img],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        raw_text = response.text
        
        print("\n" + "="*40)
        print("✅ RAW RESPONSE FROM GEMINI AI")
        print("="*40)
        print(raw_text)
        print("="*40 + "\n")
        
        # Robust fallback to extract JSON
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        
        if json_match:
            return json.loads(json_match.group(0))
        else:
            return json.loads(raw_text)
            
    except Exception as e:
        print(f"\n❌ AI API ERROR: {e}")
        return {
            "amount": None, 
            "reference": None, 
            "is_manipulated": False, 
            "confidence": "low", 
            "reason": f"AI analysis failed: {e}"
        }

@app.get("/health")
def health_check():
    return {"status": "System Online"}

@app.post("/verify-payment")
async def verify_payment(
    order_id: str = Form(...),
    customer_phone: str = Form(...),
    payment_slip: UploadFile = File(...)
):
    image_bytes = await payment_slip.read()
    
    # 1. Save File Locally
    filename = f"{uuid.uuid4()}.png"
    filepath = os.path.join("static/uploads", filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    
    slip_image_url = f"http://127.0.0.1:8000/uploads/{filename}"
    img_hash = get_image_hash(image_bytes)
    
    # Default variables for the database record
    ext_amount, ext_ref, ext_account, ext_date = None, None, None, None
    status, reason, next_action = "NEEDS_VERIFICATION", "System processing failed.", "Please wait for manual review."
    
    # Helper for exiting the pipeline and logging to DB
    def finalize(final_status, final_reason, final_action):
        supabase.table("payments").insert({
            "order_id": order_id,
            "slip_image_url": slip_image_url,
            "image_hash": img_hash,
            "extracted_amount": ext_amount,
            "extracted_reference": ext_ref,
            "extracted_account": ext_account,
            "extracted_date": ext_date,
            "verification_status": final_status,
            "reason": final_reason
        }).execute()
        return {"status": final_status, "reason": final_reason, "next_action": final_action}

# ---------------------------------------------------------
    # TIER 1: Exact Image Duplicate Detection
    # ---------------------------------------------------------
    duplicate_check = supabase.table("payments").select("*").eq("image_hash", img_hash).execute()
    if len(duplicate_check.data) > 0:
        prev_payment = duplicate_check.data[0]
        prev_status = prev_payment['verification_status']
        
        if prev_payment['order_id'] != order_id:
            return finalize("REJECTED", "Payment slip already used for a different order.", "This payment appears to have already been used for another order. Please send the correct slip.")
        
        # Smart responses based on previous submission status
        if prev_status == "APPROVED":
            return finalize("REJECTED", "Duplicate of an already approved slip.", "This payment was already verified and approved. No further action needed.")
        elif prev_status == "REJECTED":
            return finalize("REJECTED", "Duplicate of a rejected slip.", "You previously submitted this exact image and it was rejected. Please submit a DIFFERENT, valid payment slip.")
        else:
            return finalize("REJECTED", "Duplicate submission for this order.", "We already received this exact slip and it is pending review. Please wait.")

# ---------------------------------------------------------
    # TIER 2: Basic OCR & DB Matching
    # ---------------------------------------------------------
    
    # NOTE: To test a successful approval with your BOC slip, temporarily change this to "0002726227"
    EXPECTED_BUSINESS_ACCOUNT = "XXXX1234" 
    
    extracted_data = extract_payment_details(image_bytes)
    
    raw_text = extracted_data.get("raw_text", "").lower()
    ext_amount = extracted_data.get("amount")
    ext_ref = extracted_data.get("reference")
    ext_accounts = extracted_data.get("accounts") # This is now a list
    ext_date = extracted_data.get("date")

    banking_keywords = ["bank", "transfer", "account", "a/c", "ref", "reference", "transaction", "success", "payment", "rs", "lkr"]
    has_keywords = any(word in raw_text for word in banking_keywords)
    
    if not ext_amount and not ext_ref and not has_keywords:
        return finalize("REJECTED", "Image does not appear to be a valid payment slip.", "The uploaded file does not look like a bank transfer slip.")

    # 1. Check for Wrong Account (Checks if the business account is ANYWHERE in the extracted accounts)
    ext_account = EXPECTED_BUSINESS_ACCOUNT if EXPECTED_BUSINESS_ACCOUNT in ext_accounts else (ext_accounts[-1] if ext_accounts else None)
    
    if ext_accounts and EXPECTED_BUSINESS_ACCOUNT not in ext_accounts:
        return finalize("REJECTED", f"Incorrect account. Found: {ext_accounts}. Expected: {EXPECTED_BUSINESS_ACCOUNT}", "This payment was made to an account that does not belong to the business.")

    # 2. Check for Old Payment (Handles multiple date formats)
    if ext_date:
        payment_date = None
        for date_format in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                payment_date = datetime.strptime(ext_date, date_format)
                break
            except ValueError:
                continue
                
        if payment_date and (datetime.now() - payment_date).days > 7:
            return finalize("REJECTED", f"Payment date ({ext_date}) is too old.", "This payment slip appears to be from a past transaction. Please submit a current slip.")
            
    # NEW: Logical Duplicate Detection (Catches cropped/rotated reused slips via Reference ID)
    if ext_ref:
        ref_check = supabase.table("payments").select("order_id").eq("extracted_reference", ext_ref).eq("verification_status", "APPROVED").execute()
        if len(ref_check.data) > 0 and ref_check.data[0]['order_id'] != order_id:
            return finalize("REJECTED", f"Reference {ext_ref} already used.", "This transaction reference was already used for a different order. Please submit a genuine slip.")

    order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_res.data:
        return finalize("NEEDS_VERIFICATION", "Order not found in system.", "Order error.")
    
    expected_amount = order_res.data[0]["expected_amount"]

    if ext_amount and float(ext_amount) != float(expected_amount):
        return finalize("NEEDS_VERIFICATION", f"Amount mismatch. Expected {expected_amount}, Found {ext_amount}.", "The payment amount does not match your order. Please check the payment.")

    if ext_ref:
        sms_check = supabase.table("sms_notifications").select("*").eq("extracted_reference", ext_ref).execute()
        if len(sms_check.data) > 0:
            sms_data = sms_check.data[0]
            if float(sms_data["extracted_amount"]) == float(expected_amount):
                return finalize("APPROVED", "Perfect match with order and bank SMS.", "Payment accepted! Your order is confirmed.")

    # ---------------------------------------------------------
    # TIER 3: AI Fallback
    # ---------------------------------------------------------
    ai_result = analyze_slip_with_ai(image_bytes, expected_amount)
    
    if ai_result.get("is_manipulated"):
        return finalize("REJECTED", "AI detected potential image manipulation.", "Your payment slip appears invalid or altered. Please provide a genuine, unedited bank slip.")
        
    ai_amount = ai_result.get("amount")
    if ai_amount:
        ext_amount = ai_amount  # Update database record with AI findings
        
    if ai_amount and float(ai_amount) != float(expected_amount):
        return finalize("NEEDS_VERIFICATION", f"AI extracted amount {ai_amount} does not match expected {expected_amount}.", "The payment amount does not match your order.")
        
    if ai_result.get("confidence") == "low":
        return finalize("NEEDS_VERIFICATION", "Image is too unclear for AI to confidently verify.", "We couldn't clearly read the payment slip. Please send a clearer image.")
        
    if ai_amount and float(ai_amount) == float(expected_amount):
        ext_ref = ai_result.get("reference")
        return finalize("NEEDS_VERIFICATION", "AI verified amount, but no matching bank SMS found.", "The payment appears valid, but cannot currently be matched with a bank notification. Please wait.")

    return finalize("NEEDS_VERIFICATION", "System could not establish payment validity.", "Please hold while we manually review your payment.")