import os
import io
import re
from fastapi import FastAPI, UploadFile, Form
from supabase import create_client, Client
from dotenv import load_dotenv
from PIL import Image
import imagehash
import pytesseract

load_dotenv()

app = FastAPI(title="Payment Verification API")

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

if not url or not key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in the .env file.")

supabase: Client = create_client(url, key)

def get_image_hash(image_bytes: bytes) -> str:
    """Generates a perceptual hash to detect duplicate or slightly cropped images."""
    img = Image.open(io.BytesIO(image_bytes))
    return str(imagehash.phash(img))

def extract_payment_details(image_bytes: bytes) -> dict:
    """Runs local OCR and uses regex to find amounts and reference numbers."""
    img = Image.open(io.BytesIO(image_bytes))
    raw_text = pytesseract.image_to_string(img)
    
    amount_matches = re.findall(r'(?:Rs\.?|LKR)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', raw_text)
    ref_matches = re.findall(r'\b(\d{6})\b', raw_text)
    
    amount = float(amount_matches[0].replace(',', '')) if amount_matches else None
    reference = ref_matches[0] if ref_matches else None
    
    return {
        "raw_text": raw_text,
        "amount": amount,
        "reference": reference
    }

@app.get("/health")
def health_check():
    return {"status": "System Online"}

@app.post("/verify-payment")
async def verify_payment(
    order_id: str = Form(...),
    customer_phone: str = Form(...),
    payment_slip: UploadFile = Form(...)
):
    image_bytes = await payment_slip.read()
    
    # TIER 1: Duplicate Detection
    img_hash = get_image_hash(image_bytes)
    duplicate_check = supabase.table("payments").select("*").eq("image_hash", img_hash).execute()
    
    if len(duplicate_check.data) > 0:
        prev_payment = duplicate_check.data[0]
        if prev_payment['order_id'] != order_id:
            return {
                "status": "REJECTED",
                "reason": "This payment slip was already used for a different order.",
                "next_action": "This payment appears to have already been used for another order. Please send the correct payment slip."
            }
        else:
            return {
                "status": "REJECTED",
                "reason": "Duplicate submission of the same payment slip for this order.",
                "next_action": "We already received this slip. Please wait for verification."
            }

    # TIER 2: Basic OCR & DB Matching
    extracted_data = extract_payment_details(image_bytes)
    ext_amount = extracted_data["amount"]
    ext_ref = extracted_data["reference"]

    order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_res.data:
        return {"status": "NEEDS_VERIFICATION", "reason": "Order not found.", "next_action": "Order error."}
    
    expected_amount = order_res.data[0]["expected_amount"]

    if ext_amount and float(ext_amount) != float(expected_amount):
        return {
            "status": "NEEDS_VERIFICATION", 
            "reason": f"Amount mismatch. Expected {expected_amount}, Found {ext_amount}.",
            "next_action": "The payment amount does not match your order. Please check the payment and send the correct slip."
        }

    if ext_ref:
        sms_check = supabase.table("sms_notifications").select("*").eq("extracted_reference", ext_ref).execute()
        if len(sms_check.data) > 0:
            sms_data = sms_check.data[0]
            if float(sms_data["extracted_amount"]) == float(expected_amount):
                
                supabase.table("payments").insert({
                    "order_id": order_id,
                    "image_hash": img_hash,
                    "extracted_amount": ext_amount,
                    "extracted_reference": ext_ref,
                    "verification_status": "APPROVED",
                    "reason": "Perfect match with order and bank SMS."
                }).execute()

                return {
                    "status": "APPROVED",
                    "reason": "Payment verified against bank SMS and expected order amount.",
                    "next_action": "Payment accepted! Your order is confirmed."
                }

    # TIER 3: Fallback logic goes here
    return {
        "status": "NEEDS_VERIFICATION",
        "reason": "Local OCR could not confidently verify the payment or find a matching SMS.",
        "next_action": "We are reviewing your payment manually. Please wait."
    }