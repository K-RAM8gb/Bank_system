import os
import shutil
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))

def reset_and_seed():
    print("Clearing old data from database...")
    # Delete in reverse order of foreign keys
    supabase.table("payments").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    supabase.table("orders").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    supabase.table("sms_notifications").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    print("Clearing old uploaded images...")
    upload_dir = "static/uploads"
    if os.path.exists(upload_dir):
        # Completely remove the directory and everything inside it
        shutil.rmtree(upload_dir)
        
    # Recreate a fresh, empty directory
    os.makedirs(upload_dir, exist_ok=True)
        
    print("Seeding new test data...")
    
    # 1. Insert Orders
    orders = [
        {"customer_phone": "+94771234567", "expected_amount": 25000.00, "status": "PENDING"},
        {"customer_phone": "+94779876543", "expected_amount": 15000.00, "status": "PENDING"}
    ]
    order_res = supabase.table("orders").insert(orders).execute()
    
    # Extract the UUIDs for your tests
    order_25k = next(o["id"] for o in order_res.data if o["expected_amount"] == 25000)
    order_15k = next(o["id"] for o in order_res.data if o["expected_amount"] == 15000)

    # 2. Insert Matching SMS for the 25k order
    sms = [{
        "sender": "BankName",
        "message_body": "Rs. 25,000 credited to A/C XXXX1234. Ref 839201.",
        "extracted_amount": 25000.00,
        "extracted_reference": "839201",
        "is_matched": False
    }]
    supabase.table("sms_notifications").insert(sms).execute()

    print("\n=== TEST CREDENTIALS ===")
    print(f"Test Order 1 (Expected 25,000):")
    print(f"Order ID: {order_25k}")
    print(f"Customer Phone: +94771234567")
    print(f"-> Use image: test_slips/01_normal_valid.png\n")
    
    print(f"Test Order 2 (Expected 15,000):")
    print(f"Order ID: {order_15k}")
    print(f"Customer Phone: +94779876543")
    print(f"-> Use image: test_slips/02_wrong_amount.png")
    print("========================")

if __name__ == "__main__":
    reset_and_seed()