# Automated Bank Payment Verification System

A low-cost, highly reliable system that determines whether a customer's WhatsApp bank transfer payment can be safely accepted. Built for the BuildStart Software Engineering Intern Challenge.

## Architecture Overview

This system uses a **Tiered Verification Funnel** to balance absolute payment safety with strict cost minimization. Instead of sending every payment slip to an expensive AI model, the system filters submissions through three progressive tiers:

1. **Tier 1 (Zero Cost):** Perceptual Image Hashing for instant duplicate/reuse detection.
2. **Tier 2 (Negligible Cost):** Local OCR (`pytesseract`) + Regex + Database matching (Order Amount & Bank SMS).
3. **Tier 3 (Low Cost):** Vision LLM (Gemini 3.5 Flash) strictly as a fallback for blurry, cropped, or highly suspicious slips.

## Setup Instructions

### Prerequisites

* Python 3.10+
* Node.js 18+
* Tesseract OCR installed locally (`sudo dnf install tesseract` on Fedora/Linux)
* A Supabase Project
* A Google Gemini API Key

### Backend Setup

1. Clone the repository and navigate to the project root.
2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate

```


3. Install dependencies:
```bash
pip install fastapi uvicorn supabase python-dotenv pydantic imagehash Pillow pytesseract google-generativeai

```


4. Create a `.env` file in the root directory:
```ini
SUPABASE_URL=your_url
SUPABASE_KEY=your_key
GEMINI_API_KEY=your_gemini_key

```


5. Run the database seed script to populate test orders and SMS:
```bash
python reset_and_seed.py

```


6. Start the FastAPI server:
```bash
uvicorn main:app --reload

```



### Frontend Dashboard Setup

1. Open a new terminal and navigate to the `dashboard` directory:
```bash
cd dashboard

```


2. Install dependencies:
```bash
npm install

```


3. Start the Vite development server:
```bash
npm run dev

```


4. Open the provided local URL (e.g., `http://localhost:5173`) to view the dashboard. Use `[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)` to upload test slips to the API.

## Major Design Decisions & Cost Considerations

* **Why Supabase?** Provides instant PostgreSQL with built-in relational querying to seamlessly match `orders`, `payments`, and `sms_notifications`.
* **Why Fast Local OCR?** Using `pytesseract` to parse clear images reduces API calls to zero for standard, clean submissions.
* **Why Gemini 3.5 Flash?** When Tier 2 fails, Gemini Flash offers state-of-the-art vision capabilities at a fraction of the cost of GPT-4V or Claude 3.5 Sonnet, keeping API overhead in Tier 3 strictly minimized.
* **Why React + Tailwind?** Allows for a lightweight, single-page application that strictly visually separates "Customer Expected Details" from "System Extracted Details", minimizing cognitive load for business employees reviewing edge cases.

## Verification & Fraud Handling Approach

* **Duplicates & Reuse:** The system generates a perceptual hash (`pHash`) of every uploaded image. If a hash collision occurs on a new order, it is instantly rejected as a reused slip.
* **Amount/Account Mismatch:** OCR extracts amounts and references. If the extracted amount does not match the expected order amount, it triggers a `NEEDS_VERIFICATION` flag.
* **Digital Manipulation:** The Tier 3 Vision AI is explicitly prompted to evaluate image clarity, unnatural artifacts, and digital manipulation, rejecting slips that appear tampered with.
* **SMS Triangulation:** A payment is only strictly `APPROVED` if the Order Amount, the Slip Amount, and the ingested Bank SMS Notification all match perfectly via the transaction reference.

## Known Limitations

* The current local OCR regex logic is optimized for standard Sri Lankan banking formats (e.g., "Rs. X,XXX.XX") and 6-digit reference numbers. Distinctly different bank formats may default to the Tier 3 AI fallback.
* Perceptual hashing prevents duplicate image uploads but can be bypassed if the user heavily alters the image crop, brightness, or aspect ratio (though the AI fallback catches duplicate reference numbers).
