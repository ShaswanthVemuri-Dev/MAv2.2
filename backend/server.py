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
            if key.endswith('_date') and isinstance(value, str):
                try:
                    item[key] = datetime.fromisoformat(value).date()
                except:
                    pass
            elif key == 'times' and isinstance(value, list):
                converted_times = []
                for time_str in value:
                    try:
                        converted_times.append(datetime.strptime(time_str, '%H:%M:%S').time())
                    except:
                        converted_times.append(time_str)
                item[key] = converted_times
    return item

# Define Models
class MedicationSchedule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    medicine_name: str
    display_name: str
    form: str  # tablet, capsule, syrup, injection, ointment, etc.
    icon: str  # emoji or icon identifier
    color: str
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
    icon: str
    color: str
    dosage: str
    frequency: int
    times: List[str]
    course_duration_days: int
    start_date: str

class PrescriptionProcessRequest(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None

class ProcessedPrescription(BaseModel):
    medications: List[MedicationSchedule]
    raw_text: str
    processing_notes: str

# Drug form to icon mapping
DRUG_FORM_ICONS = {
    "tablet": "💊",
    "capsule": "💊",
    "syrup": "🍯",
    "injection": "💉",
    "ointment": "🧴",
    "cream": "🧴",
    "drops": "💧",
    "inhaler": "💨",
    "patch": "🩹",
    "powder": "⚪",
    "gel": "🧴",
    "spray": "💨"
}

# Common drug colors
DRUG_COLORS = {
    "white": "#FFFFFF",
    "blue": "#3B82F6",
    "red": "#EF4444",
    "green": "#10B981",
    "yellow": "#F59E0B",
    "pink": "#EC4899",
    "orange": "#F97316",
    "purple": "#8B5CF6",
    "brown": "#A3A3A3"
}

async def process_prescription_with_ai(text: str = None, image_base64: str = None) -> dict:
    """Process prescription using AI vision/text processing"""
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="LLM API key not configured")

        # Create unique session ID for this processing
        session_id = f"prescription_{uuid.uuid4()}"
        
        system_message = """You are a medical prescription processing AI. Your job is to extract structured medication information from prescription text or images.

Extract the following information for each medication:
1. Medicine name (generic and brand name if available)
2. Form (tablet, capsule, syrup, injection, ointment, etc.)
3. Dosage (strength and quantity per dose)
4. Frequency (how many times per day)
5. Suggested times (based on frequency - distribute evenly through the day)
6. Course duration in days
7. Start date (if mentioned, otherwise assume today)

For colors, try to infer from common drug appearances or default to white.

Return ONLY a JSON object in this exact format:
{
  "medications": [
    {
      "medicine_name": "string",
      "display_name": "string (form + color description)",
      "form": "string",
      "dosage": "string", 
      "frequency": integer,
      "times": ["HH:MM", "HH:MM"],
      "course_duration_days": integer,
      "start_date": "YYYY-MM-DD",
      "color": "color_name"
    }
  ],
  "raw_text": "extracted or provided text",
  "processing_notes": "any notes about processing"
}

If processing an image, first extract all readable text, then process as above."""

        # Initialize chat with GPT-4o (vision model for maximum efficiency)
        chat = LlmChat(
            api_key=api_key,
            session_id=session_id,
            system_message=system_message
        ).with_model("openai", "gpt-4o")

        # Create user message
        if image_base64:
            # Process image
            image_content = ImageContent(image_base64=image_base64)
            user_message = UserMessage(
                text="Please extract and process the prescription information from this image.",
                file_contents=[image_content]
            )
        else:
            # Process text
            user_message = UserMessage(
                text=f"Please extract and process the prescription information from this text: {text}"
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
    return {"message": "Prescription Processing API"}

@api_router.post("/process-prescription", response_model=ProcessedPrescription)
async def process_prescription(request: PrescriptionProcessRequest):
    """Process prescription from text or image and return structured medication data"""
    if not request.text and not request.image_base64:
        raise HTTPException(status_code=400, detail="Either text or image_base64 must be provided")
    
    # Process with AI
    ai_result = await process_prescription_with_ai(request.text, request.image_base64)
    
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
            course_duration_days=med_data["course_duration_days"],
            start_date=med_data["start_date"]
        )
        medications.append(medication)
    
    # Store in database
    for medication in medications:
        med_dict = prepare_for_mongo(medication.dict())
        await db.medications.insert_one(med_dict)
    
    return ProcessedPrescription(
        medications=medications,
        raw_text=ai_result.get("raw_text", request.text or "Image processed"),
        processing_notes=ai_result.get("processing_notes", "Processed successfully")
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