# Automated Bank Payment Verification System

An intelligent, cost-optimized system designed to verify WhatsApp customer bank transfer payment slips. This system employs a 3-tier escalation architecture (Hashing → OCR → Vision AI) to accurately verify payments, prevent fraud, and reduce unnecessary API costs.

---

## 🚀 Setup Instructions

### Prerequisites
- Python 3.9+
- Node.js 18+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system.
- Supabase account (PostgreSQL database).
- Google Gemini API Key.

### 1. Database Setup (Supabase)
1. Create a new Supabase project.
2. Run the SQL provided in `schema.sql` in the Supabase SQL Editor to create the `orders`, `sms_notifications`, and `payments` tables.
3. Obtain your **Project URL** and **API Key** from the Supabase dashboard.

### 2. Backend Setup (FastAPI)
1. Navigate to the project root directory.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install fastapi uvicorn supabase python-dotenv pillow imagehash pytesseract google-genai python-multipart requests
   ```
3. Create a `.env` file in the root directory:
   ```env
   SUPABASE_URL="your_supabase_url"
   SUPABASE_KEY="your_supabase_anon_key"
   GEMINI_API_KEY="your_gemini_api_key"
   ```
4. Seed the database with test data:
   ```bash
   python reset_and_seed.py
   ```
5. Start the backend server:
   ```bash
   uvicorn main:app --reload
   ```
   *The API will be available at `http://127.0.0.1:8000`*

### 3. Frontend Setup (React Dashboard)
1. Navigate to the `dashboard` directory:
   ```bash
   cd dashboard
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```
   *The dashboard will be available at `http://localhost:5173`*

---

## 🏗️ Architecture Overview

The system is separated into three decoupled components:
1. **The Verification Engine (FastAPI):** A high-performance Python backend that receives slip images via POST request, runs the tiered verification pipeline, and logs the outcome to the database.
2. **The Database (Supabase PostgreSQL):** Stores Orders, Bank SMS Notifications, and Payment Verification Attempts.
3. **The Review Dashboard (React + Tailwind CSS):** A clean, polling-based UI for business employees to review edge cases, mismatches, and AI-flagged fraudulent slips.

---

## 💡 Major Design Decisions & Cost Considerations

The core design philosophy of this system is **Cost-Optimized Escalation**. Sending every uploaded image directly to a large Vision Model (LLM) is expensive and slow. Instead, the verification pipeline only scales up processing power when necessary:

1. **Tier 1: Exact Duplicate Detection (Cost: $0, Time: <10ms)**
   - Calculates the SHA-256 hash of the uploaded file.
   - If the exact file was already submitted, it is immediately rejected.
2. **Tier 2: Local OCR & Regex (Cost: $0, Time: ~300ms)**
   - Uses `pytesseract` to extract all raw text locally.
   - Uses Regular Expressions to identify amounts, reference numbers, dates, and account numbers.
   - Evaluates a strict 3-way match: Does `Expected Order Amount == Extracted OCR Amount == Bank SMS Amount` AND `Extracted OCR Ref == Bank SMS Ref`? If yes, it's approved.
3. **Tier 3: Vision AI Fallback (Cost: Low API Usage, Time: ~3s)**
   - Uses `gemini-3.5-flash` via the Google GenAI SDK.
   - *Only invoked* if the OCR fails to read the slip due to low quality, or if the extracted details conflict with the database.
   - The LLM is explicitly prompted to output strict JSON and flag digital manipulation or blurriness.

By filtering ~80-90% of legitimate and standard payments through Tiers 1 & 2, the system minimizes API costs while maximizing speed.

---

## 🛡️ Verification & Fraud-Handling Approach

Fraud prevention relies on a combination of strict logic rules and AI perception:

- **Reused Payments (Cropped/Rotated):** If a customer screenshots an old slip to bypass the exact file hash (Tier 1), Tier 2 extracts the `reference number` and checks the database. If that reference was already used for an *Approved* payment on a *different* order, it is rejected as a "Logical Duplicate".
- **Wrong Account/Old Dates:** Tier 2 OCR verifies that the slip is addressed to the business's actual account (`XXXX1234`) and that the slip date is within a 7-day acceptable window.
- **Photoshopped/Manipulated Slips:** If the slip reaches Tier 3, the AI is prompted to actively look for visual tampering (mismatched fonts, patched numbers, unnatural artifacting) and flags `is_manipulated = true`.
- **Similar Payments from Multiple Customers:** The system never assumes an amount match proves ownership. It requires the unique Bank SMS reference number to match the slip's reference number to confirm which customer made which payment.

---

## ⚠️ Known Limitations

1. **OCR Reliability on Handwriting:** `pytesseract` struggles with handwritten deposit slips. These will frequently fall through to Tier 3 (AI verification).
2. **Bank SMS Delays:** If a customer uploads a slip *before* the bank SMS arrives in the system, it will be flagged as `NEEDS_VERIFICATION`. A cron job or webhook would be needed in production to auto-reprocess pending payments once SMS messages arrive.
3. **Stateless Image Storage:** Currently, images are stored locally in the `static/uploads/` directory. If the FastAPI server restarts in a containerized environment (like Docker or Heroku) without a mounted volume, the uploaded images will be lost.

---
