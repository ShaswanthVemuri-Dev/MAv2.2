from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, date, time, timezone
import base64
import json
import asyncio
import io
import mimetypes

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
MONGO_URL = os.getenv('MONGO_URL')
DB_NAME = os.getenv('DB_NAME', 'prescriptions')

client: Optional[AsyncIOMotorClient] = None
db = None

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Helper functions
def prepare_for_mongo(data):
    """Convert date/time objects to strings for MongoDB storage"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, date):
                data[key] = value.isoformat()
            elif isinstance(value, time):
                data[key] = value.strftime('%H:%M:%S')
            elif isinstance(value, list):
                data[key] = [prepare_for_mongo(item) if isinstance(item, dict) else item for item in value]
    return data

def parse_from_mongo(item):
    """Convert string dates/times back to Python objects"""
    if isinstance(item, dict):
        for key, value in item.items():
            # Keep start_date as string for Pydantic model compatibility
            if key == 'start_date' and isinstance(value, str):
                # Keep as string - no conversion needed
                pass
            elif key.endswith('_date') and isinstance(value, str) and key != 'start_date':
                try:
                    item[key] = datetime.fromisoformat(value).date()
                except:
                    pass
            elif key == 'times' and isinstance(value, list):
                # Keep times as strings for Pydantic model compatibility
                pass
    return item

# Define Models
class MedicationSchedule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    medicine_name: Optional[str] = None
    display_name: Optional[str] = None
    form: Optional[str] = None  # tablet, capsule, syrup, injection, ointment, etc.
    icon_svg: Optional[str] = None  # SVG file path or identifier
    medication_color: Optional[str] = None  # actual medication/pill color (hex)
    background_color: Optional[str] = None  # packaging/sheet color (hex)
    dosage: Optional[str] = None
    frequency: Optional[int] = None  # times per day
    times: Optional[List[str]] = None  # list of time strings like ["08:00", "14:00", "20:00"]
    course_duration_days: Optional[int] = None
    start_date: Optional[str] = None  # ISO date string
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MedicationScheduleCreate(BaseModel):
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    medicine_name: Optional[str] = None
    display_name: Optional[str] = None
    form: Optional[str] = None
    icon_svg: Optional[str] = None
    medication_color: Optional[str] = None
    background_color: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[int] = None
    times: Optional[List[str]] = None
    course_duration_days: Optional[int] = None
    start_date: Optional[str] = None

class PrescriptionProcessRequest(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None
    voice_transcription: Optional[str] = None
    user_id: Optional[str] = None
    device_id: Optional[str] = None

class ProcessedPrescription(BaseModel):
    medications: List[MedicationSchedule]
    raw_text: str
    processing_notes: str

# Drug form to SVG icon mapping
DRUG_FORM_ICONS = {
    "tablet": "/icons/medications/tablet.svg",
    "capsule": "/icons/medications/capsule.svg",
    "syrup": "/icons/medications/syrup.svg",
    "liquid": "/icons/medications/liquid.svg",
    "injection": "/icons/medications/injection.svg",
    "ointment": "/icons/medications/ointment.svg",
    "cream": "/icons/medications/cream.svg",
    "drops": "/icons/medications/drops.svg",
    "inhaler": "/icons/medications/inhaler.svg",
    "patch": "/icons/medications/patch.svg",
    "powder": "/icons/medications/powder.svg",
    "gel": "/icons/medications/gel.svg",
    "spray": "/icons/medications/spray.svg",
    "lotion": "/icons/medications/lotion.svg",
    "suppository": "/icons/medications/suppository.svg",
    "solution": "/icons/medications/solution.svg"
}

# Common medication and packaging colors
COLOR_MAP: Dict[str, str] = {
    "white": "#FFFFFF",
    "blue": "#3B82F6",
    "red": "#EF4444",
    "green": "#10B981",
    "yellow": "#F59E0B",
    "pink": "#EC4899",
    "orange": "#F97316",
    "purple": "#8B5CF6",
    "brown": "#A57C5A",
    "clear": "#F8FAFC",
    "transparent": "#F8FAFC",
    "silver": "#D1D5DB",
    "gold": "#FCD34D",
    "cream": "#FEF3C7",
    "beige": "#F5F5DC",
    "maroon": "#991B1B",
    "grey": "#9CA3AF",
    "gray": "#9CA3AF",
    "light blue": "#93C5FD",
    "dark blue": "#1E40AF",
    "light green": "#86EFAC",
    "dark green": "#065F46"
}

def normalize_color_name(name: Optional[str]) -> str:
    if not name:
        return "white"
    return name.strip().lower()


def color_to_hex(name: Optional[str]) -> str:
    """Map a color name to hex code with safe defaults."""
    hex_val = COLOR_MAP.get(normalize_color_name(name))
    return hex_val or COLOR_MAP["white"]


def generate_times_for_frequency(freq: Optional[int]) -> List[str]:
    if not freq or freq <= 0:
        return []
    # even distribution over 24h starting at 08:00
    start_hour = 8
    gap = 24 / float(freq)
    times = []
    for i in range(freq):
        hour = int((start_hour + i * gap) % 24)
        minute = int(((start_hour + i * gap) % 1) * 60)
        times.append(f"{hour:02d}:{minute:02d}")
    return times


def basic_text_parse(text: str) -> Dict[str, Any]:
    """Very simple heuristic parser for common patterns when LLM is unavailable."""
    import re
    if not text:
        return {"medications": [], "raw_text": "", "processing_notes": "No text provided."}

    raw = text
    name_match = re.search(r"([A-Za-z][A-Za-z0-9\- ]+)", text)
    dosage_match = re.search(r"(\d+\s?(mg|ml|mcg))", text, re.IGNORECASE)
    # Frequency patterns: OD/BD/TDS/QDS or "3 times daily"
    freq = None
    if re.search(r"\b(OD|once daily)\b", text, re.IGNORECASE):
        freq = 1
    elif re.search(r"\b(BD|BID|twice daily)\b", text, re.IGNORECASE):
        freq = 2
    elif re.search(r"\b(TDS|TID|three times)\b", text, re.IGNORECASE):
        freq = 3
    elif re.search(r"\b(QDS|QID|four times)\b", text, re.IGNORECASE):
        freq = 4
    else:
        times_match = re.search(r"(\d+)\s*x\s*(?:daily|per day)", text, re.IGNORECASE)
        if times_match:
            freq = int(times_match.group(1))

    duration = None
    dur_match = re.search(r"(\d+)\s*(d|day|days|wk|week|weeks)", text, re.IGNORECASE)
    if dur_match:
        n = int(dur_match.group(1))
        unit = dur_match.group(2).lower()
        duration = n * (7 if unit.startswith('wk') else 1)

    form = None
    for f in ["tablet", "tab", "capsule", "cap", "syrup", "injection", "ointment", "cream", "drops", "inhaler", "patch", "powder", "gel", "spray", "solution", "liquid"]:
        if re.search(fr"\b{f}\b", text, re.IGNORECASE):
            form = {
                "tab": "tablet",
                "cap": "capsule",
            }.get(f, f)
            break

    medicine_name = name_match.group(1).strip() if name_match else None
    dosage = dosage_match.group(1).replace(" ", "") if dosage_match else None
    frequency = freq if freq is not None else None
    times = generate_times_for_frequency(frequency)

    today = datetime.now(timezone.utc).date().isoformat()

    med = {
        "medicine_name": medicine_name,
        "display_name": None,
        "form": form or None,
        "dosage": dosage,
        "frequency": frequency,
        "times": times or None,
        "course_duration_days": duration,
        "start_date": today,
        "medication_color": "white",
        "background_color": "blue",
    }

    notes = "Parsed with heuristic fallback; values may be incomplete."
    return {"medications": [med] if any(v for k, v in med.items() if k not in ("times",)) else [], "raw_text": raw, "processing_notes": notes}


async def process_prescription_with_openai(text: str = None, image_base64: str = None, voice_transcription: str = None) -> dict:
    """Use OpenAI (gpt-4o) to extract structured medication data from text or image."""
    try:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key or OpenAI is None:
            return basic_text_parse(voice_transcription or text)

        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_OCR_MODEL", "gpt-4o")

        input_content = ""
        if voice_transcription:
            input_content = f"Voice transcription: {voice_transcription}"
        elif text:
            input_content = f"Prescription text: {text}"

        system_message = """You are a specialized Medical Prescription Processing AI with expertise in:
- Medical terminology and drug nomenclature
- Prescription formats and doctor handwriting patterns
- Dosage calculations and frequency interpretations
- Drug forms, routes of administration, and scheduling
- Medication appearance and packaging colors

COLOR EXTRACTION RULES (CRITICAL):
1. medication_color: actual color of pill/tablet/liquid (e.g., white tablet, red syrup)
2. background_color: packaging/strip color (e.g., blue blister pack, silver strip)
   - Dolo 650: medication_color=white, background_color=blue
   - Amoxicillin: medication_color=pink, background_color=silver
3. Infer colors from common knowledge when not explicit; default medication_color=white, background_color=blue

Return ONLY a JSON object with fields:
{
  "medications": [
    {
      "medicine_name": string|null,
      "display_name": string|null,
      "form": string|null,
      "dosage": string|null,
      "frequency": number|null,
      "times": [string]|null,
      "course_duration_days": number|null,
      "start_date": string|null,
      "medication_color": string|null,
      "background_color": string|null
    }
  ],
  "raw_text": string,
  "processing_notes": string
}
All fields may be null if uncertain. For times, use HH:MM 24h.
"""

        user_text = (
            f"Analyze this prescription image. Additional context: {input_content or 'None'}\n"
            if image_base64 else
            f"Process this prescription information with medical expertise:\n\n{input_content}"
        )

        if image_base64:
            content = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ]
        else:
            content = user_text

        completion = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        )
        message = completion.choices[0].message
        response_text = message.content or "{}"
        try:
            return json.loads(response_text)
        except Exception:
            return basic_text_parse(voice_transcription or text)
    except Exception as e:
        logging.error(f"OpenAI OCR extraction error: {e}")
        return basic_text_parse(voice_transcription or text)


async def process_prescription_with_ai(text: str = None, image_base64: str = None, voice_transcription: str = None) -> dict:
    """Process prescription using AI with enhanced medical context. Falls back to heuristic parser if AI unavailable."""
    try:
        # Prefer OpenAI API if configured
        openai_key = os.environ.get('OPENAI_API_KEY')
        if openai_key and OpenAI is not None:
            result = await process_prescription_with_openai(text, image_base64, voice_transcription)
            return result

        # Legacy provider removed; falling back if OpenAI not available
        return basic_text_parse(voice_transcription or text)
        
        # Enhanced system message with medical-specific context
        system_message = """You are a specialized Medical Prescription Processing AI with expertise in:
- Medical terminology and drug nomenclature
- Prescription formats and doctor handwriting patterns
- Dosage calculations and frequency interpretations
- Drug forms, routes of administration, and scheduling
- Medication appearance and packaging colors

CORE MEDICAL KNOWLEDGE:
- Common drug names (generic and brand): Paracetamol/Acetaminophen/Tylenol, Amoxicillin, Ibuprofen, etc.
- Dosage forms: tablets, capsules, syrup, injection, ointment, cream, drops, inhaler, patch, powder, gel, spray
- Frequency patterns: OD (once daily), BD/BID (twice daily), TDS/TID (three times daily), QDS/QID (four times daily)
- Medical abbreviations: mg, ml, mcg, IU, PRN (as needed), AC (before meals), PC (after meals)

COLOR EXTRACTION RULES (CRITICAL):
1. **medication_color**: The actual color of the pill/tablet/liquid (e.g., white tablet, red syrup, yellow capsule)
2. **background_color**: The packaging/sheet/strip color (e.g., blue blister pack, silver strip, white box)
   - For Dolo 650: medication_color = "white" (tablet is white), background_color = "blue" (strip is blue)
   - For Amoxicillin: medication_color = "pink" (capsule is pink/red), background_color = "silver" (strip is silver)
   - For syrups: medication_color = syrup color, background_color = bottle/label dominant color
3. Use common knowledge about popular medications to infer colors if not explicitly stated
4. Default to medication_color = "white" and background_color = "blue" if uncertain

EXTRACTION RULES FOR PRESCRIPTIONS:
1. **Medicine Name**: Extract both generic and brand names, normalize spelling variations
2. **Strength/Dosage**: Include unit (mg, ml, mcg) and quantity per dose
3. **Form**: Identify tablet, capsule, syrup, etc. from context or explicit mention
4. **Frequency**: Convert medical abbreviations to daily count (BD=2, TDS=3, QDS=4)
5. **Duration**: Extract days, weeks, or "until finished"
6. **Schedule**: Generate optimal timing based on frequency (evenly distributed)

HANDLE POOR QUALITY/DISTORTED TEXT:
- Use medical context to interpret unclear handwriting
- Recognize common prescription patterns even with spelling errors
- Infer missing information based on standard medical practices
- Flag uncertain extractions in processing_notes

For images: First extract ALL readable text (including partial/unclear words), then apply medical knowledge to interpret and complete the prescription information.

Return ONLY a JSON object in this exact format:
{
  "medications": [
    {
      "medicine_name": "Primary drug name (generic preferred)",
      "display_name": "Form + Color description (e.g., 'White Tablet on Blue Strip', 'Red Syrup')",
      "form": "tablet|capsule|syrup|injection|ointment|cream|drops|inhaler|patch|powder|gel|spray",
      "dosage": "Complete dosage with units (e.g., '500mg per tablet', '5ml')", 
      "frequency": integer (times per day),
      "times": ["HH:MM format times evenly distributed"],
      "course_duration_days": integer,
      "start_date": "Today's date in YYYY-MM-DD format",
      "medication_color": "actual medication color name (e.g., white, pink, red, yellow)",
      "background_color": "packaging/strip color name (e.g., blue, silver, white, green)"
    }
  ],
  "raw_text": "All extracted text from image/input",
  "processing_notes": "Medical interpretation notes, confidence level, any uncertainties"
}

COMMON MEDICAL PATTERNS WITH COLORS:
- "Tab Dolo 650 1 OD x 5d" = Paracetamol 650mg tablet, once daily, 5 days | medication_color: white, background_color: blue
- "Cap Amoxil 500 BD x 7d" = Amoxicillin 500mg capsule, twice daily, 7 days | medication_color: pink, background_color: silver
- "Syr Cetirizine 5ml TDS x 3d" = Cetirizine syrup 5ml, three times daily, 3 days | medication_color: clear, background_color: white
- "Tab Aspirin 75mg OD" = Aspirin tablet, once daily | medication_color: white, background_color: white

Focus on medical accuracy, patient safety, and precise color identification in your extractions."""

        # Legacy code path removed
        return basic_text_parse(voice_transcription or text)
                
    except Exception as e:
        logging.error(f"Error processing prescription with AI: {str(e)}")
        # Fallback instead of erroring out
        return basic_text_parse(voice_transcription or text)

# Routes

@api_router.post("/transcribe-audio")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(None),
    audio_base64: Optional[str] = Form(None),
    mime_type: Optional[str] = Form(None),
    duration_seconds: Optional[float] = Form(None),
):
    """Transcribe audio via OpenAI Whisper. Supports multipart file or base64 JSON/Form.

    Limits: size <= MAX_AUDIO_SIZE_MB (default 150), duration <= 300 seconds if provided.
    """
    # Allow JSON body for base64 input
    if file is None and audio_base64 is None:
        ct = request.headers.get("content-type", "")
        if ct.startswith("application/json"):
            body = await request.json()
            audio_base64 = body.get("audio_base64")
            mime_type = body.get("mime_type")
            duration_seconds = body.get("duration_seconds")

    if file is None and audio_base64 is None:
        raise HTTPException(status_code=400, detail="Provide 'file' (multipart) or 'audio_base64' with 'mime_type'.")

    # Enforce 5-min duration cap if provided by client
    if duration_seconds is not None and float(duration_seconds) > 300.0:
        raise HTTPException(status_code=413, detail="Audio too long (> 300 seconds)")

    max_audio_mb = float(os.getenv("MAX_AUDIO_SIZE_MB", "150"))
    max_bytes = int(max_audio_mb * 1024 * 1024)

    def ensure_audio_mime(mt: Optional[str]) -> str:
        if not mt or not mt.startswith("audio/"):
            raise HTTPException(status_code=415, detail="Unsupported content type. Expect audio/*")
        return mt

    # Read data with size cap
    if file is not None:
        ensure_audio_mime(file.content_type)
        size = 0
        chunks = []
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail=f"File too large (> {max_audio_mb} MB)")
            chunks.append(chunk)
        data = b"".join(chunks)
        mt = file.content_type
        ext = mimetypes.guess_extension(mt) or ".wav"
        bio = io.BytesIO(data)
        bio.name = f"audio{ext}"
    else:
        ensure_audio_mime(mime_type)
        try:
            data = base64.b64decode(audio_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 audio")
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (> {max_audio_mb} MB)")
        ext = mimetypes.guess_extension(mime_type) or ".wav"
        bio = io.BytesIO(data)
        bio.name = f"audio{ext}"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        raise HTTPException(status_code=500, detail="OpenAI not configured")

    client = OpenAI(api_key=api_key)

    try:
        resp = await asyncio.to_thread(lambda: client.audio.transcriptions.create(model="whisper-1", file=bio))
        # SDK returns an object with 'text'; safely access either
        text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else None) or ""
        return {"text": text, "confidence": None, "duration": duration_seconds}
    except Exception as e:
        logging.error(f"OpenAI transcription error: {e}")
        raise HTTPException(status_code=502, detail="Transcription failed")
@api_router.get("/")
async def root():
    return {"message": "Advanced Prescription Processing API with Medical AI"}

@api_router.post("/process-prescription", response_model=ProcessedPrescription)
async def process_prescription(request: PrescriptionProcessRequest):
    """Process prescription from text, voice, or image and return structured medication data"""
    if not request.text and not request.image_base64 and not request.voice_transcription:
        raise HTTPException(status_code=400, detail="Either text, voice_transcription, or image_base64 must be provided")
    
    # Basic payload safety checks
    max_image_mb = float(os.getenv('MAX_IMAGE_SIZE_MB', '5'))
    if request.image_base64:
        try:
            approx_size_mb = (len(request.image_base64) * 3) / (4 * 1024 * 1024)
            if approx_size_mb > max_image_mb:
                raise HTTPException(status_code=413, detail=f"Image too large (> {max_image_mb} MB)")
        except Exception:
            pass

    # Process with enhanced medical AI (with fallback)
    ai_result = await process_prescription_with_ai(request.text, request.image_base64, request.voice_transcription)
    
    # Convert to our models and enhance with SVG icons and colors
    medications = []
    max_meds = int(os.getenv('MAX_MEDICATIONS_PER_REQUEST', '20'))
    meds_in = ai_result.get("medications", [])[:max_meds]
    for med_data in meds_in:
        # Get SVG icon path based on form
        form_val = (med_data.get("form") or "tablet").lower()
        icon_svg = DRUG_FORM_ICONS.get(form_val, "/icons/medications/tablet.svg")
        
        # Get medication color (actual pill/liquid color)
        medication_color = color_to_hex(med_data.get("medication_color", "white"))
        
        # Get background color (packaging/strip color)
        background_color = color_to_hex(med_data.get("background_color", "blue"))
        
        # Support partial fields by using .get with safe defaults
        times_in = med_data.get("times") or generate_times_for_frequency(med_data.get("frequency"))
        medication = MedicationSchedule(
            user_id=request.user_id,
            device_id=request.device_id,
            medicine_name=med_data.get("medicine_name"),
            display_name=med_data.get("display_name"),
            form=form_val,
            icon_svg=icon_svg,
            medication_color=medication_color,
            background_color=background_color,
            dosage=med_data.get("dosage"),
            frequency=med_data.get("frequency"),
            times=times_in,
            course_duration_days=(med_data.get("course_duration_days") if med_data.get("course_duration_days") is not None else None),
            start_date=med_data.get("start_date")
        )
        medications.append(medication)
    
    # Store in database
    if db is not None and medications:
        for medication in medications:
            med_dict = prepare_for_mongo(medication.dict())
            await db.medications.insert_one(med_dict)
    
    return ProcessedPrescription(
        medications=medications,
        raw_text=ai_result.get("raw_text", request.text or request.voice_transcription or "Image processed"),
        processing_notes=ai_result.get("processing_notes", "Processed with advanced medical AI")
    )

@api_router.get("/medications", response_model=List[MedicationSchedule])
async def get_medications(user_id: Optional[str] = None, device_id: Optional[str] = None):
    """Get all stored medications; optionally filter by user_id/device_id"""
    query: Dict[str, Any] = {}
    if user_id:
        query["user_id"] = user_id
    if device_id:
        query["device_id"] = device_id

    if db is None:
        return []
    medications = await db.medications.find(query).to_list(1000)
    return [MedicationSchedule(**parse_from_mongo(med)) for med in medications]

@api_router.get("/medications/{medication_id}", response_model=MedicationSchedule)
async def get_medication(medication_id: str):
    """Get a specific medication by ID"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    medication = await db.medications.find_one({"id": medication_id})
    if not medication:
        raise HTTPException(status_code=404, detail="Medication not found")
    return MedicationSchedule(**parse_from_mongo(medication))

@api_router.delete("/medications/{medication_id}")
async def delete_medication(medication_id: str):
    """Delete a medication"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    result = await db.medications.delete_one({"id": medication_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Medication not found")
    return {"message": "Medication deleted successfully"}

@api_router.post("/medications", response_model=MedicationSchedule)
async def create_medication(medication: MedicationScheduleCreate):
    """Manually create a medication schedule"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    med_obj = MedicationSchedule(**medication.dict())
    med_dict = prepare_for_mongo(med_obj.dict())
    await db.medications.insert_one(med_dict)
    return med_obj

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_db_client():
    global client, db
    if MONGO_URL:
        try:
            client = AsyncIOMotorClient(MONGO_URL)
            db_name = DB_NAME or 'prescriptions'
            db = client[db_name]
            # Create helpful indexes
            await db.medications.create_index("id", unique=True)
            await db.medications.create_index([("user_id", 1)])
            await db.medications.create_index([("device_id", 1)])
            logging.info("MongoDB connected and indexes ensured")
        except Exception as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            client = None
            db = None
    else:
        logging.warning("MONGO_URL not set; database operations will be disabled")

@api_router.get("/health")
async def health():
    status = {
        "status": "ok",
        "db": "connected" if db is not None else "disabled",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return status

@app.on_event("shutdown")
async def shutdown_db_client():
    if client:
        client.close()
