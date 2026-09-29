import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))

def seed_data():
    orders = [
        {"customer_phone": "+94771234567", "expected_amount": 25000.00, "status": "PENDING"},
        {"customer_phone": "+94779876543", "expected_amount": 5000.00, "status": "PENDING"},
        {"customer_phone": "+94775555555", "expected_amount": 12500.50, "status": "PENDING"}
    ]
    supabase.table("orders").insert(orders).execute()

    sms_messages = [
        {
            "sender": "BankName",
            "message_body": "Rs. 25,000 credited to A/C XXXX1234. Ref 839201.",
            "extracted_amount": 25000.00,
            "extracted_reference": "839201",
            "is_matched": False
        }
    ]
    supabase.table("sms_notifications").insert(sms_messages).execute()
    print("Database seeded successfully.")

if __name__ == "__main__":
    seed_data()