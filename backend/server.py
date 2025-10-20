from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, date, time, timezone
import base64
import json
import asyncio
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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
    medicine_name: str
    display_name: str
    form: str  # tablet, capsule, syrup, injection, ointment, etc.
    icon_svg: str  # SVG file path or identifier
    medication_color: str  # actual medication/pill color (hex)
    background_color: str  # packaging/sheet color (hex)
    dosage: str
    frequency: int  # times per day
    times: List[str]  # list of time strings like ["08:00", "14:00", "20:00"]
    course_duration_days: int
    start_date: str  # ISO date string
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MedicationScheduleCreate(BaseModel):
    medicine_name: str
    display_name: str
    form: str
    icon_svg: str
    medication_color: str
    background_color: str
    dosage: str
    frequency: int
    times: List[str]
    course_duration_days: int
    start_date: str

class PrescriptionProcessRequest(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None
    voice_transcription: Optional[str] = None

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
COLOR_MAP = {
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

async def process_prescription_with_ai(text: str = None, image_base64: str = None, voice_transcription: str = None) -> dict:
    """Process prescription using AI with enhanced medical context"""
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="LLM API key not configured")

        # Create unique session ID for this processing
        session_id = f"prescription_{uuid.uuid4()}"
        
        # Enhanced system message with medical-specific context
        system_message = """You are a specialized Medical Prescription Processing AI with expertise in:
- Medical terminology and drug nomenclature
- Prescription formats and doctor handwriting patterns
- Dosage calculations and frequency interpretations
- Drug forms, routes of administration, and scheduling

CORE MEDICAL KNOWLEDGE:
- Common drug names (generic and brand): Paracetamol/Acetaminophen/Tylenol, Amoxicillin, Ibuprofen, etc.
- Dosage forms: tablets, capsules, syrup, injection, ointment, cream, drops, inhaler, patch, powder, gel, spray
- Frequency patterns: OD (once daily), BD/BID (twice daily), TDS/TID (three times daily), QDS/QID (four times daily)
- Medical abbreviations: mg, ml, mcg, IU, PRN (as needed), AC (before meals), PC (after meals)

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
      "display_name": "Form + Color description (e.g., 'White Tablet', 'Red Syrup')",
      "form": "tablet|capsule|syrup|injection|ointment|cream|drops|inhaler|patch|powder|gel|spray",
      "dosage": "Complete dosage with units (e.g., '500mg per tablet', '5ml')", 
      "frequency": integer (times per day),
      "times": ["HH:MM format times evenly distributed"],
      "course_duration_days": integer,
      "start_date": "Today's date in YYYY-MM-DD format",
      "color": "inferred or default color name"
    }
  ],
  "raw_text": "All extracted text from image/input",
  "processing_notes": "Medical interpretation notes, confidence level, any uncertainties"
}

COMMON MEDICAL PATTERNS TO RECOGNIZE:
- "Tab Dolo 650 1 OD x 5d" = Paracetamol 650mg tablet, once daily, 5 days
- "Cap Amoxil 500 BD x 7d" = Amoxicillin 500mg capsule, twice daily, 7 days  
- "Syr Cetirizine 5ml TDS x 3d" = Cetirizine syrup 5ml, three times daily, 3 days

Focus on medical accuracy and patient safety in your extractions."""

        # Initialize chat with GPT-4o (vision model for maximum medical processing efficiency)
        chat = LlmChat(
            api_key=api_key,
            session_id=session_id,
            system_message=system_message
        ).with_model("openai", "gpt-4o")

        # Prepare input text
        input_content = ""
        if voice_transcription:
            input_content = f"Voice transcription: {voice_transcription}"
        elif text:
            input_content = f"Prescription text: {text}"

        # Create user message
        if image_base64:
            # Enhanced prompt for image processing with medical context
            image_content = ImageContent(image_base64=image_base64)
            user_message = UserMessage(
                text=f"""Analyze this prescription image with maximum medical accuracy. 

INSTRUCTIONS:
1. Extract ALL readable text, including partially visible words
2. Use medical knowledge to interpret unclear handwriting/print
3. Recognize common prescription abbreviations and formats
4. Apply context to complete partial information
5. Provide confidence assessment for each extraction

Additional context: {input_content if input_content else 'No additional context'}

Focus on: Medicine names, dosages, frequencies, duration, and any special instructions.""",
                file_contents=[image_content]
            )
        else:
            # Process text or voice transcription
            user_message = UserMessage(
                text=f"""Process this prescription information with medical expertise:

{input_content}

Apply medical knowledge to:
1. Normalize drug names to standard forms
2. Convert abbreviations to full specifications  
3. Calculate optimal dosing schedules
4. Infer missing but standard information
5. Ensure medical safety and accuracy"""
            )

        # Send message and get response
        response = await chat.send_message(user_message)
        
        # Parse JSON response
        try:
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            # If response is not valid JSON, try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
            else:
                raise HTTPException(status_code=500, detail=f"Could not parse AI response as JSON: {response}")
                
    except Exception as e:
        logging.error(f"Error processing prescription with AI: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process prescription: {str(e)}")

# Routes
@api_router.get("/")
async def root():
    return {"message": "Advanced Prescription Processing API with Medical AI"}

@api_router.post("/process-prescription", response_model=ProcessedPrescription)
async def process_prescription(request: PrescriptionProcessRequest):
    """Process prescription from text, voice, or image and return structured medication data"""
    if not request.text and not request.image_base64 and not request.voice_transcription:
        raise HTTPException(status_code=400, detail="Either text, voice_transcription, or image_base64 must be provided")
    
    # Process with enhanced medical AI
    ai_result = await process_prescription_with_ai(request.text, request.image_base64, request.voice_transcription)
    
    # Convert to our models and enhance with icons/colors
    medications = []
    for med_data in ai_result.get("medications", []):
        # Get icon based on form
        form = med_data.get("form", "tablet").lower()
        icon = DRUG_FORM_ICONS.get(form, "💊")
        
        # Get color
        color_name = med_data.get("color", "white").lower()
        color = DRUG_COLORS.get(color_name, "#FFFFFF")
        
        medication = MedicationSchedule(
            medicine_name=med_data["medicine_name"],
            display_name=med_data["display_name"],
            form=form,
            icon=icon,
            color=color,
            dosage=med_data["dosage"],
            frequency=med_data["frequency"],
            times=med_data["times"],
            course_duration_days=med_data.get("course_duration_days") or 7,  # Default to 7 days if None
            start_date=med_data["start_date"]
        )
        medications.append(medication)
    
    # Store in database
    for medication in medications:
        med_dict = prepare_for_mongo(medication.dict())
        await db.medications.insert_one(med_dict)
    
    return ProcessedPrescription(
        medications=medications,
        raw_text=ai_result.get("raw_text", request.text or request.voice_transcription or "Image processed"),
        processing_notes=ai_result.get("processing_notes", "Processed with advanced medical AI")
    )

@api_router.get("/medications", response_model=List[MedicationSchedule])
async def get_medications():
    """Get all stored medications"""
    medications = await db.medications.find().to_list(1000)
    return [MedicationSchedule(**parse_from_mongo(med)) for med in medications]

@api_router.get("/medications/{medication_id}", response_model=MedicationSchedule)
async def get_medication(medication_id: str):
    """Get a specific medication by ID"""
    medication = await db.medications.find_one({"id": medication_id})
    if not medication:
        raise HTTPException(status_code=404, detail="Medication not found")
    return MedicationSchedule(**parse_from_mongo(medication))

@api_router.delete("/medications/{medication_id}")
async def delete_medication(medication_id: str):
    """Delete a medication"""
    result = await db.medications.delete_one({"id": medication_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Medication not found")
    return {"message": "Medication deleted successfully"}

@api_router.post("/medications", response_model=MedicationSchedule)
async def create_medication(medication: MedicationScheduleCreate):
    """Manually create a medication schedule"""
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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()