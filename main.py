import os
import io
import re
from fastapi import FastAPI, UploadFile, Form, File
from supabase import create_client, Client
from dotenv import load_dotenv
from PIL import Image
import imagehash
import pytesseract
from google import genai
import json
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta 

load_dotenv()

app = FastAPI(title="Payment Verification API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
VISION_MODEL_ID = 'gemini-3.5-flash'

def get_image_hash(image_bytes: bytes) -> str:
    """Generates a perceptual hash to detect duplicate or slightly cropped images."""
    img = Image.open(io.BytesIO(image_bytes))
    return str(imagehash.phash(img))

def extract_payment_details(image_bytes: bytes) -> dict:
    """Runs local OCR and uses regex to find amounts, references, accounts, and dates."""
    img = Image.open(io.BytesIO(image_bytes))
    raw_text = pytesseract.image_to_string(img)
    
    amount_matches = re.findall(r'(?:Rs\.?|LKR)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', raw_text)
    ref_matches = re.findall(r'\b(\d{6})\b', raw_text)
    
    # Extract Account (Looks for "To Account: XXXX1234" or "A/C: 12345678")
    acc_match = re.search(r'(?:Account|A/C|Acc)[\s:]*([A-Za-z0-9*X]+)', raw_text, re.IGNORECASE)
    
    # Extract Date (Looks for YYYY-MM-DD)
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', raw_text)
    
    amount = float(amount_matches[0].replace(',', '')) if amount_matches else None
    reference = ref_matches[0] if ref_matches else None
    account = acc_match.group(1) if acc_match else None
    date_str = date_match.group(1) if date_match else None
    
    return {
        "raw_text": raw_text,
        "amount": amount,
        "reference": reference,
        "account": account,
        "date": date_str
    }

def analyze_slip_with_ai(image_bytes: bytes, expected_amount: float) -> dict:
    """Uses LLM Vision to extract data and detect fraud when standard OCR fails."""
    img = Image.open(io.BytesIO(image_bytes))
    
    prompt = f"""
    Analyze this bank transfer slip. The expected amount is {expected_amount}.
    It may be a digitally generated e-receipt, which is perfectly valid. Do not mark confidence as "low" just because it is digital.
    Format your response EXACTLY matching this JSON schema:
    {{
        "amount": (float) The exact amount transferred. Use null if completely unreadable.,
        "reference": (string) The reference number. Use null if completely unreadable.,
        "is_manipulated": (boolean) True ONLY if you see clear signs of digital tampering like mismatched fonts or patches over numbers.,
        "confidence": (string) "high" if you can read the text, "low" if it is too blurry or cut off.,
        "reason": (string) A brief explanation of your findings.
    }}
    """
    
    try:
        # Force strict JSON output from Gemini
        response = client.models.generate_content(
            model=VISION_MODEL_ID,
            contents=[prompt, img],
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
        raw_json = response.text.strip()
        print(f"\n[AI RESPONSE] {raw_json}\n") # Debugging print
        return json.loads(raw_json)
        
    except Exception as e:
        print(f"\n[AI ERROR] {e}\n")
        return {"amount": None, "reference": None, "is_manipulated": False, "confidence": "low", "reason": f"AI Error: {str(e)}"}

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
    img_hash = get_image_hash(image_bytes)

    # 1. Verify Order Exists First
    order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_res.data:
        return {"status": "NEEDS_VERIFICATION", "reason": "Order not found.", "next_action": "Order error."}
    
    expected_amount = order_res.data[0]["expected_amount"]

    def save_and_return(status, reason, next_action, ext_amt=None, ext_ref=None):
        supabase.table("payments").insert({
            "order_id": order_id,
            "image_hash": img_hash,
            "extracted_amount": ext_amt,
            "extracted_reference": ext_ref,
            "verification_status": status,
            "reason": reason
        }).execute()
        return {
            "status": status,
            "reason": reason,
            "next_action": next_action
        }
    
    # TIER 1: Duplicate Detection
    duplicate_check = supabase.table("payments").select("*").eq("image_hash", img_hash).execute()
    
    if len(duplicate_check.data) > 0:
        prev_payment = duplicate_check.data[0]
        if prev_payment['order_id'] != order_id:
            return save_and_return(
                "REJECTED", 
                "This payment slip was already used for a different order.", 
                "This payment appears to have already been used for another order. Please send the correct payment slip."
            )
        else:
            return save_and_return(
                "REJECTED", 
                "Duplicate submission of the same payment slip for this order.", 
                "We already received this slip. Please wait for verification."
            )

    # TIER 2: Basic OCR & DB Matching
    EXPECTED_BUSINESS_ACCOUNT = "XXXX1234"
    
    extracted_data = extract_payment_details(image_bytes)
    ext_amount = extracted_data["amount"]
    ext_ref = extracted_data["reference"]
    ext_account = extracted_data["account"]
    ext_date = extracted_data["date"]

    # 1. Check for Wrong Account
    if ext_account and ext_account != EXPECTED_BUSINESS_ACCOUNT:
        return save_and_return(
            "REJECTED", 
            f"Payment made to incorrect account: {ext_account}. Expected: {EXPECTED_BUSINESS_ACCOUNT}", 
            "This payment was made to an account that does not belong to the business. Please check the details.",
            ext_amount, ext_ref
        )

    # 2. Check for Old Payment (e.g., older than 7 days)
    if ext_date:
        try:
            payment_date = datetime.strptime(ext_date, "%Y-%m-%d")
            # If the payment date is more than 7 days old
            if (datetime.now() - payment_date).days > 7:
                return save_and_return(
                    "REJECTED", 
                    f"Payment date ({ext_date}) is too old to be for this current order.", 
                    "This payment slip appears to be from a past transaction. Please submit the slip for your new order.",
                    ext_amount, ext_ref
                )
        except ValueError:
            pass # Ignore date parsing errors and let AI handle it if necessary

    # 3. Compare Amounts
    if ext_amount and float(ext_amount) != float(expected_amount):
        return save_and_return(
            "NEEDS_VERIFICATION", 
            f"Amount mismatch. Expected {expected_amount}, Found {ext_amount}.",
            "The payment amount does not match your order. Please check the payment and send the correct slip.",
            ext_amount, ext_ref
        )

    # 4. Look for matching Bank SMS Evidence
    if ext_ref:
        sms_check = supabase.table("sms_notifications").select("*").eq("extracted_reference", ext_ref).execute()
        if len(sms_check.data) > 0:
            sms_data = sms_check.data[0]
            if float(sms_data["extracted_amount"]) == float(expected_amount):
                # Perfect 3-Way Match!
                return save_and_return(
                    "APPROVED", 
                    "Perfect match with order and bank SMS.", 
                    "Payment accepted! Your order is confirmed.",
                    ext_amount, ext_ref
                )

    #--------------------------------------------------------
    # TIER 3: AI Fallback (Cost: Low API usage)
    # ---------------------------------------------------------
    ai_result = analyze_slip_with_ai(image_bytes, expected_amount)
    
    ai_amount = ai_result.get("amount")
    ai_ref = ai_result.get("reference")

    # Check for Fraud/Manipulation first
    if ai_result.get("is_manipulated"):
        return save_and_return(
            "REJECTED", 
            "AI detected potential image manipulation or suspicious formatting.", 
            "Your payment slip appears invalid or altered. Please provide a genuine, unedited bank slip.",
            ai_amount, ai_ref
        )
        
    # Check AI extracted amount
    if ai_amount and float(ai_amount) != float(expected_amount):
        return save_and_return(
            "NEEDS_VERIFICATION", 
            f"AI extracted amount {ai_amount} does not match expected {expected_amount}.", 
            "The payment amount does not match your order. Please check the payment and send the correct slip.",
            ai_amount, ai_ref
        )
        
    # If AI has low confidence (blurry, dark, cropped)
    if ai_result.get("confidence") == "low":
        return save_and_return(
            "NEEDS_VERIFICATION", 
            "Image is too unclear for AI to confidently verify.", 
            "We couldn't clearly read the payment slip. Please send a clearer image of the complete slip.",
            ai_amount, ai_ref
        )
        
    # If AI verified the amount, but we still don't have matching bank SMS
    if ai_amount and float(ai_amount) == float(expected_amount):
        return save_and_return(
            "NEEDS_VERIFICATION", 
            "AI verified amount, but no matching bank SMS found.", 
            "The payment appears valid, but the transaction cannot currently be matched with a bank notification. Please wait.",
            ai_amount, ai_ref
        )

    # Final Catch-All
    return save_and_return(
        "NEEDS_VERIFICATION", 
        "System could not establish payment validity.", 
        "Please hold while we manually review your payment.",
        ai_amount, ai_ref
    )