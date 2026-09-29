import os
import io
import re
from fastapi import FastAPI, UploadFile, Form
from supabase import create_client, Client
from dotenv import load_dotenv
from PIL import Image
import imagehash
import pytesseract
import google.generativeai as genai
import json

load_dotenv()

app = FastAPI(title="Payment Verification API")

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

if not url or not key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in the .env file.")

supabase: Client = create_client(url, key)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
# Using gemini-1.5-flash as it is the fastest and cheapest for simple vision tasks
vision_model = genai.GenerativeModel('gemini-1.5-flash')

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

def analyze_slip_with_ai(image_bytes: bytes, expected_amount: float) -> dict:
    """Uses LLM Vision to extract data and detect fraud when standard OCR fails."""
    img = Image.open(io.BytesIO(image_bytes))
    
    prompt = f"""
    Analyze this bank transfer slip. The expected amount is {expected_amount}.
    Return ONLY a raw JSON object with no markdown formatting or backticks.
    The JSON must have the following keys:
    - "amount": (float) The exact amount transferred. If unreadable, return null.
    - "reference": (string) The transaction reference number. If unreadable, return null.
    - "is_manipulated": (boolean) True if the image looks edited, digitally altered, or suspicious.
    - "confidence": (string) "high" or "low" based on image clarity.
    - "reason": (string) A brief explanation of your findings.
    """
    
    try:
        response = vision_model.generate_content([prompt, img])
        # Clean up any potential markdown formatting the LLM might add
        raw_json = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw_json)
    except Exception as e:
        print(f"AI API Error: {e}")
        return {"amount": None, "reference": None, "is_manipulated": False, "confidence": "low", "reason": "AI analysis failed."}
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

    #--------------------------------------------------------
    # TIER 3: AI Fallback (Cost: Low API usage)
    # ---------------------------------------------------------
    ai_result = analyze_slip_with_ai(image_bytes, expected_amount)
    
    # Check for Fraud/Manipulation first
    if ai_result.get("is_manipulated"):
        return {
            "status": "REJECTED",
            "reason": "AI detected potential image manipulation or suspicious formatting.",
            "next_action": "Your payment slip appears invalid or altered. Please provide a genuine, unedited bank slip."
        }
        
    # Check AI extracted amount
    ai_amount = ai_result.get("amount")
    if ai_amount and float(ai_amount) != float(expected_amount):
        return {
            "status": "NEEDS_VERIFICATION",
            "reason": f"AI extracted amount {ai_amount} does not match expected {expected_amount}.",
            "next_action": "The payment amount does not match your order. Please check the payment and send the correct slip."
        }
        
    # If AI has low confidence (blurry, dark, cropped)
    if ai_result.get("confidence") == "low":
        return {
            "status": "NEEDS_VERIFICATION",
            "reason": "Image is too unclear for AI to confidently verify.",
            "next_action": "We couldn't clearly read the payment slip. Please send a clearer image of the complete slip."
        }
        
    # If AI verified the amount, but we still don't have matching bank SMS
    if ai_amount and float(ai_amount) == float(expected_amount):
        
        # Save this partial match to the database for manual review
        supabase.table("payments").insert({
            "order_id": order_id,
            "image_hash": img_hash,
            "extracted_amount": ai_amount,
            "extracted_reference": ai_result.get("reference"),
            "verification_status": "NEEDS_VERIFICATION",
            "reason": "AI verified amount, but no matching bank SMS found."
        }).execute()
        
        return {
            "status": "NEEDS_VERIFICATION",
            "reason": "Slip appears valid, but awaiting bank SMS confirmation.",
            "next_action": "The payment appears valid, but the transaction cannot currently be matched with a bank notification. Please wait."
        }

    # Final Catch-All
    return {
        "status": "NEEDS_VERIFICATION",
        "reason": "System could not establish payment validity.",
        "next_action": "Please hold while we manually review your payment."
    }