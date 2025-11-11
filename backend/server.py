from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Set, Tuple
import uuid
from datetime import datetime, date, time, timezone
import base64
import json
import asyncio
import io
import mimetypes
import re

try:
    from icons_color_algorithm import ColorInputs, load_manifest, recolor_svg
except ImportError:  # pragma: no cover - optional during certain tests
    ColorInputs = None  # type: ignore
    load_manifest = None  # type: ignore
    recolor_svg = None  # type: ignore

try:
    import icons_sv_storage
except ImportError:  # pragma: no cover
    icons_sv_storage = None  # type: ignore

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

ICON_MANIFEST_PATH = ROOT_DIR / "icons.color.manifest.json"
ICON_MANIFEST_DATA = (
    load_manifest(ICON_MANIFEST_PATH) if load_manifest and ICON_MANIFEST_PATH.exists() else None
)
AVAILABLE_ICON_KEYS: Set[str] = (
    set(icons_sv_storage.ICON_SVGS.keys()) if getattr(icons_sv_storage, "ICON_SVGS", None) else set()
)
ICON_COLOR_READY = bool(
    ColorInputs and recolor_svg and icons_sv_storage and ICON_MANIFEST_DATA and AVAILABLE_ICON_KEYS
)

DEFAULT_FREQUENCY = 1
DEFAULT_QUANTITY = 1.0
DEFAULT_ADMINISTRATION_INSTRUCTION = "After meals"

BOTTLE_FORMS = {"mouthwash", "lotion", "syrup", "ointment", "sprays"}

DEFAULT_TIMES_BY_FREQUENCY: Dict[int, List[str]] = {
    1: ["08:00"],
    2: ["08:00", "20:00"],
    3: ["08:00", "14:00", "20:00"],
    4: ["06:00", "12:00", "18:00", "22:00"],
}

TIME_KEYWORD_TO_24H: Dict[str, str] = {
    "morning": "08:00",
    "noon": "12:00",
    "afternoon": "13:00",
    "evening": "18:00",
    "night": "22:00",
    "midnight": "00:00",
    "breakfast": "08:00",
    "lunch": "13:00",
    "dinner": "20:00",
    "bedtime": "22:30",
    "before_breakfast": "07:00",
    "after_breakfast": "09:00",
    "before_lunch": "12:00",
    "after_lunch": "14:00",
    "before_dinner": "18:00",
    "after_dinner": "21:00",
}

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
class IconColorSlots(BaseModel):
    background: Optional[str] = None
    ascent1: Optional[str] = None
    ascent2: Optional[str] = None
    cap: Optional[str] = None


class MedicationSchedule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    medicine_name: Optional[str] = None
    display_name: Optional[str] = None
    form: Optional[str] = None  # tablet, capsule, syrup, injection, ointment, etc.
    icon_svg: Optional[str] = None  # Base64 SVG data URI for the recolored icon
    medication_color: Optional[str] = None  # actual medication/pill color (hex)
    background_color: Optional[str] = None  # packaging/sheet color (hex)
    icon_colors: Optional[IconColorSlots] = None
    quantity: Optional[float] = None
    dosage: Optional[str] = None
    frequency: Optional[int] = None  # times per day
    times: Optional[List[str]] = None  # list of time strings like ["08:00", "14:00", "20:00"]
    course_duration_days: Optional[int] = None
    administration_instruction: Optional[str] = None
    start_date: Optional[str] = None  # ISO date string
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MedicationScheduleCreate(BaseModel):
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    medicine_name: Optional[str] = None
    display_name: Optional[str] = None
    form: Optional[str] = None
    icon_svg: Optional[str] = None  # Base64 SVG data URI for the recolored icon
    medication_color: Optional[str] = None
    background_color: Optional[str] = None
    icon_colors: Optional[IconColorSlots] = None
    quantity: Optional[float] = None
    dosage: Optional[str] = None
    frequency: Optional[int] = None
    times: Optional[List[str]] = None
    course_duration_days: Optional[int] = None
    administration_instruction: Optional[str] = None
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

# Medication type catalog with subtype normalization
MEDICATION_TYPE_SECTORS: Dict[str, List[str]] = {
    "Tablets": [
        "Immediate-release (plain)",
        "Film-coated",
        "Sugar-coated",
        "Enteric-coated",
        "Extended-release",
        "Prolonged-release",
        "Chewable",
        "Effervescent",
        "Orally disintegrating (ODT)",
        "Dispersible",
        "Tablet for solution",
        "Sublingual",
        "Buccal",
        "Scored",
        "Multilayer"
    ],
    "Capsules": [
        "Hard capsule",
        "Softgel",
        "Liquid-filled capsule",
        "Pellet/bead-filled",
        "Sprinkle capsule",
        "Enteric/delayed-release capsule",
        "Extended/modified-release capsule"
    ],
    "Sachets": [
        "Powder for solution",
        "Powder for suspension",
        "Granules for solution",
        "Granules for suspension",
        "Effervescent powder/granules",
        "ORS sachet"
    ],
    "Gum": [
        "Nicotine gum",
        "Medicated chewing gum"
    ],
    "Inserts": [
        "Rectal insert",
        "Vaginal insert",
        "Urethral insert"
    ],
    "Ointment": [
        "Skin ointment",
        "Ophthalmic ointment",
        "Otic ointment",
        "Nasal ointment",
        "Rectal/vaginal ointment"
    ],
    "Lotion": [
        "Topical lotion",
        "Scalp lotion",
        "Calamine lotion",
        "Antiseptic/medicated lotion"
    ],
    "Patches": [
        "Transdermal medicated patch",
        "Medicated plaster",
        "Hydrocolloid patch",
        "Hydrogel patch",
        "Adhesive bandage",
        "Pimple patch",
        "Wound dressing patch"
    ],
    "Syrup": [
        "Syrup (oral solution)",
        "Cough syrup/linctus",
        "Dry syrup (reconstitute)"
    ],
    "Mouthwash": [
        "Mouthwash",
        "Gargle"
    ],
    "Sprays": [
        "Nasal spray",
        "Throat/oromucosal spray",
        "Topical/cutaneous spray",
        "Metered spray",
        "Sublingual spray"
    ],
    "Drops": [
        "Eye drops (solution)",
        "Eye drops (suspension)",
        "Ear drops",
        "Nasal drops"
    ],
    "Injections": [
        "Intravenous (IV) injection",
        "IV infusion (drip)",
        "Intramuscular (IM) injection",
        "Subcutaneous (SC) injection",
        "Intradermal injection",
        "Prefilled syringe",
        "Autoinjector/pen",
        "Vial",
        "Ampoule",
        "Lyophilized powder (reconstitute)",
        "Liposomal/extended-release injection"
    ],
    "Inhalers": [
        "Metered-dose inhaler (MDI)",
        "Dry powder inhaler (DPI)",
        "Soft mist inhaler (SMI)",
        "Breath-actuated inhaler",
        "Nebulizer solution/suspension"
    ]
}


def _normalize_form_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _slugify_sector_name(name: str) -> str:
    return _normalize_form_key(name).replace(" ", "_")


SUBTYPE_TO_SECTOR: Dict[str, str] = {}
ICON_KEY_TO_SECTOR: Dict[str, str] = {}


def _register_form_mapping(key: str, sector: str) -> None:
    if key:
        SUBTYPE_TO_SECTOR.setdefault(key, sector)


for sector_name, subtypes in MEDICATION_TYPE_SECTORS.items():
    sector_key = _normalize_form_key(sector_name)
    _register_form_mapping(sector_key, sector_name)
    ICON_KEY_TO_SECTOR[_slugify_sector_name(sector_name)] = sector_name

    singular_sector = sector_name[:-1] if sector_name.endswith("s") else sector_name
    normalized_singular = _normalize_form_key(singular_sector)
    if normalized_singular:
        _register_form_mapping(normalized_singular, sector_name)

    for subtype in subtypes:
        full_key = _normalize_form_key(subtype)
        _register_form_mapping(full_key, sector_name)

        without_parentheses = re.sub(r"\s*\(.*?\)\s*", " ", subtype)
        cleaned_key = _normalize_form_key(without_parentheses)
        _register_form_mapping(cleaned_key, sector_name)

        if normalized_singular:
            combined_singular = _normalize_form_key(f"{without_parentheses} {singular_sector}")
            _register_form_mapping(combined_singular, sector_name)

        combined_plural = _normalize_form_key(f"{without_parentheses} {sector_name}")
        _register_form_mapping(combined_plural, sector_name)


def normalize_medication_sector(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = _normalize_form_key(value)
    if not key:
        return None
    return SUBTYPE_TO_SECTOR.get(key, value.strip())


def icon_key_for_sector(sector: Optional[str]) -> Optional[str]:
    """Return the icon storage key for a normalized sector if assets are available."""
    if not sector:
        return None
    slug = _slugify_sector_name(sector)
    if not slug:
        return None
    return slug if slug in AVAILABLE_ICON_KEYS else None


ICON_COLOR_ALIAS_MAP: Dict[str, List[str]] = {
    "background": ["background", "background_color", "strip_color", "packaging_color", "package_color", "wrapper_color"],
    "ascent1": ["ascent1", "accent1", "primary_color", "medication_color", "pill_color", "sn1"],
    "ascent2": ["ascent2", "accent2", "secondary_color", "shadow_color", "sn2"],
    "cap": ["cap", "cap_color", "capColor", "bottle_cap_color"],
}


def _first_non_empty(container: Dict[str, Any], candidate_keys: List[str]) -> Optional[str]:
    for key in candidate_keys:
        value = container.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def extract_icon_color_inputs(med_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Merge/sanitize potential color fields coming from AI."""
    if not isinstance(med_data, dict):
        return {}

    merged: Dict[str, Any] = {}
    icon_colors = med_data.get("icon_colors")
    if isinstance(icon_colors, dict):
        merged.update(icon_colors)

    icon_section = med_data.get("icon")
    if isinstance(icon_section, dict):
        nested_colors = icon_section.get("colors")
        if isinstance(nested_colors, dict):
            merged.update(nested_colors)
        for slot in ICON_COLOR_ALIAS_MAP.keys():
            slot_val = icon_section.get(slot)
            if isinstance(slot_val, str) and slot_val.strip():
                merged.setdefault(slot, slot_val)

    sanitized: Dict[str, Optional[str]] = {}
    for slot, alias_keys in ICON_COLOR_ALIAS_MAP.items():
        raw_value = merged.get(slot) or _first_non_empty(med_data, alias_keys)
        cleaned = sanitize_hex_color(raw_value)
        if cleaned:
            sanitized[slot] = cleaned
    return sanitized


def parse_quantity(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        match = re.search(r"(\d+(?:\.\d+)?)", value.replace(",", ""))
        if match:
            value = match.group(1)
    try:
        qty = float(value)
        if qty <= 0:
            return None
        return round(qty, 2)
    except (TypeError, ValueError):
        return None


def parse_frequency(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        freq = int(round(float(value)))
        return freq if freq > 0 else None
    except (TypeError, ValueError):
        return None


def parse_positive_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        num = int(str(value).strip())
        return num if num > 0 else None
    except (ValueError, TypeError):
        return None


def parse_frequency_label(label: Optional[str]) -> Optional[int]:
    if not label or not isinstance(label, str):
        return None
    text = label.strip().lower()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(x|times)\s*/?\s*(day|daily)?", text)
    if match:
        return max(1, int(round(float(match.group(1)))))
    if "once" in text or "single" in text:
        return 1
    if any(word in text for word in ("twice", "bid", "bd", "two")):
        return 2
    if any(word in text for word in ("thrice", "tid", "tds", "three")):
        return 3
    if any(word in text for word in ("qid", "four", "4x")):
        return 4
    return None


def parse_duration_label(label: Optional[str]) -> Optional[int]:
    if not label or not isinstance(label, str):
        return None
    text = label.strip().lower()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months)", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit.startswith("day"):
        return int(round(value))
    if unit.startswith("week"):
        return int(round(value * 7))
    if unit.startswith("month"):
        return int(round(value * 30))
    return None


def _tokenize_time_string(raw: str) -> List[str]:
    cleaned = (
        raw.replace("/", ",")
        .replace("&", ",")
        .replace(" and ", ",")
        .replace(" AND ", ",")
    )
    tokens = [seg.strip() for seg in cleaned.split(",") if seg and seg.strip()]
    return tokens or [raw.strip()]


def _parse_clock_time(token: str) -> Optional[str]:
    match = re.match(r"(?i)^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", token)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3)
    if ampm:
        ampm = ampm.lower()
        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12
    hour %= 24
    minute %= 60
    return f"{hour:02d}:{minute:02d}"


def _keyword_to_time(token: str) -> Optional[str]:
    key = token.strip().lower().replace(" ", "_")
    if key in TIME_KEYWORD_TO_24H:
        return TIME_KEYWORD_TO_24H[key]
    for keyword, value in TIME_KEYWORD_TO_24H.items():
        if keyword in key:
            return value
    return None


def normalize_times_field(value: Any) -> List[str]:
    if value is None:
        return []

    raw_entries: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_entries.extend(_tokenize_time_string(item))
            elif isinstance(item, dict):
                for key in ("time", "label", "name", "value"):
                    candidate = item.get(key)
                    if isinstance(candidate, str):
                        raw_entries.extend(_tokenize_time_string(candidate))
                        break
    elif isinstance(value, str):
        raw_entries.extend(_tokenize_time_string(value))

    normalized: List[str] = []
    for entry in raw_entries:
        if not entry:
            continue
        candidate = _parse_clock_time(entry)
        if not candidate:
            candidate = _keyword_to_time(entry)
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def default_times_for_frequency(frequency: int) -> List[str]:
    if frequency in DEFAULT_TIMES_BY_FREQUENCY:
        return DEFAULT_TIMES_BY_FREQUENCY[frequency][:]
    return DEFAULT_TIMES_BY_FREQUENCY[DEFAULT_FREQUENCY][:]


def ensure_times_for_frequency(times: List[str], frequency: int) -> List[str]:
    if frequency <= 0:
        frequency = DEFAULT_FREQUENCY
    deduped: List[str] = []
    for t in times:
        if t not in deduped:
            deduped.append(t)
    if not deduped:
        deduped = default_times_for_frequency(frequency)
    elif len(deduped) < frequency:
        defaults = default_times_for_frequency(frequency)
        for slot in defaults:
            if len(deduped) >= frequency:
                break
            if slot not in deduped:
                deduped.append(slot)
    return deduped


def _manifest_icon_entry(icon_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ICON_MANIFEST_DATA or not icon_key:
        return None
    return ICON_MANIFEST_DATA.get("icons", {}).get(icon_key)


def _manifest_slot(icon_key: Optional[str], role: str) -> Optional[Dict[str, Any]]:
    entry = _manifest_icon_entry(icon_key)
    if not entry:
        return None
    for slot in entry.get("slots", []):
        if slot.get("role") == role:
            return slot
    return None


def _normalize_manifest_color(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return sanitize_hex_color(value)


def _darken_hex(color: str, pct: float = 0.15) -> Optional[str]:
    candidate = sanitize_hex_color(color)
    if not candidate:
        return None
    r = int(candidate[1:3], 16)
    g = int(candidate[3:5], 16)
    b = int(candidate[5:7], 16)
    r = max(0, min(255, int(r * (1 - pct))))
    g = max(0, min(255, int(g * (1 - pct))))
    b = max(0, min(255, int(b * (1 - pct))))
    return f"#{r:02X}{g:02X}{b:02X}"


def _derive_ascent2_color(icon_key: Optional[str], color_inputs: Dict[str, Optional[str]]) -> Optional[str]:
    provided = color_inputs.get("ascent2")
    if provided:
        return provided
    a1 = color_inputs.get("ascent1")
    if not a1:
        a1_slot = _manifest_slot(icon_key, "ascent1")
        if a1_slot:
            a1 = _normalize_manifest_color(a1_slot.get("default_color"))
    if not a1:
        slot = _manifest_slot(icon_key, "ascent2")
        return _normalize_manifest_color(slot.get("default_color")) if slot else None
    if a1 in ("#FFF", "#FFFFFF"):
        return "#D6D6D6"
    derived = _darken_hex(a1)
    return derived or "#D6D6D6"


def finalize_icon_colors(icon_key: Optional[str], color_inputs: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    slots = ["background", "ascent1", "ascent2", "cap"]
    final: Dict[str, Optional[str]] = {}
    for slot in slots:
        if not icon_key:
            final[slot] = color_inputs.get(slot)
            continue
        if slot == "ascent2":
            final[slot] = _derive_ascent2_color(icon_key, color_inputs)
            continue
        slot_meta = _manifest_slot(icon_key, slot)
        if color_inputs.get(slot):
            final[slot] = color_inputs[slot]
        elif slot_meta:
            final[slot] = _normalize_manifest_color(slot_meta.get("default_color"))
        else:
            final[slot] = None
    return final


def _assumptions_to_text(assumptions: List[str], validation_summary: Optional[str]) -> str:
    lines: List[str] = []
    if validation_summary:
        lines.append(validation_summary)
    for assumption in assumptions:
        if assumption:
            lines.append(f"- {assumption}")
    return "\n".join(lines).strip()


def _sanitize_color_value(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    if token.lower() == "use_default":
        return None
    normalized = sanitize_hex_color(token)
    if normalized:
        return normalized
    compact = token.lower().replace(" ", "")
    if compact in CSS_COLOR_MAP:
        return CSS_COLOR_MAP[compact].upper()
    match = RGB_COLOR_PATTERN.match(token.lower())
    if match:
        r, g, b = (max(0, min(255, int(part))) for part in match.groups())
        return f"#{r:02X}{g:02X}{b:02X}"
    return None


def convert_ai_v2_payload(ai_result: Dict[str, Any], fallback_text: Optional[str]) -> Dict[str, Any]:
    meds_out: List[Dict[str, Any]] = []
    meds_in = ai_result.get("medications") or []
    assumptions: List[str] = []
    notes_block = ai_result.get("processing_notes") or {}
    validation_summary = None
    if isinstance(notes_block, dict):
        assumptions = notes_block.get("assumptions") or []
        validation_summary = notes_block.get("validation_summary")
    processing_notes_text = _assumptions_to_text(assumptions, validation_summary) or validation_summary or "Processed with advanced medical AI"
    raw_text = ai_result.get("raw_text") or fallback_text or ""

    for entry in meds_in:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        form_label = entry.get("form")
        icon_section = entry.get("icon") or {}
        icon_key = icon_section.get("key")
        if not icon_key and isinstance(form_label, str):
            icon_key = _slugify_sector_name(form_label)
        sector_from_icon = ICON_KEY_TO_SECTOR.get(icon_key or "", None)
        resolved_form = form_label or sector_from_icon
        normalized_form = normalize_medication_sector(resolved_form) or sector_from_icon or (form_label.title() if isinstance(form_label, str) else None)

        colors_in = icon_section.get("colors") or {}
        raw_colors = {
            "background": colors_in.get("background"),
            "ascent1": colors_in.get("ascent1"),
            "ascent2": colors_in.get("ascent2"),
            "cap": colors_in.get("cap"),
        }
        sanitized_colors: Dict[str, Optional[str]] = {
            "background": _sanitize_color_value(colors_in.get("background")),
            "ascent1": _sanitize_color_value(colors_in.get("ascent1")),
            "ascent2": _sanitize_color_value(colors_in.get("ascent2")),
            "cap": _sanitize_color_value(colors_in.get("cap")),
        }
        logging.info("[ai_raw] name=%s form=%s icon_key=%s raw_colors=%s sanitized=%s",
                     name or "unknown",
                     resolved_form or "unknown",
                     icon_key or "n/a",
                     raw_colors,
                     sanitized_colors)
        form_slug = (resolved_form or "").strip().lower()
        if form_slug not in BOTTLE_FORMS:
            sanitized_colors["cap"] = None

        quantity_val = parse_quantity(entry.get("quantity"))
        frequency_val = parse_frequency_label(entry.get("frequency"))
        times_raw = entry.get("times") if isinstance(entry.get("times"), list) else []
        course_duration_days = parse_duration_label(entry.get("course_duration"))
        instructions = entry.get("instructions")

        medication = {
            "medicine_name": name,
            "display_name": None,
            "form": normalized_form,
            "dosage": None,
            "frequency": frequency_val,
            "times": times_raw,
            "course_duration_days": course_duration_days,
            "start_date": None,
            "medication_color": sanitized_colors.get("ascent1"),
            "background_color": sanitized_colors.get("background"),
            "quantity": quantity_val,
            "administration_instruction": instructions.strip() if isinstance(instructions, str) and instructions.strip() else None,
            "icon_colors": sanitized_colors,
            "icon_colors_raw": raw_colors,
            "icon_key_hint": icon_key,
        }
        meds_out.append(medication)

    return {
        "medications": meds_out,
        "raw_text": raw_text,
        "processing_notes_text": processing_notes_text,
        "processing_notes_meta": {
            "assumptions": assumptions,
            "validation_summary": validation_summary,
        },
    }


def normalize_ai_output(ai_result: Dict[str, Any], fallback_text: Optional[str]) -> Dict[str, Any]:
    meds = ai_result.get("medications") or []
    if meds and isinstance(meds[0], dict) and "medicine_name" in meds[0]:
        notes = ai_result.get("processing_notes")
        notes_text = notes if isinstance(notes, str) else json.dumps(notes) if notes else "Processed with advanced medical AI"
        return {
            "medications": meds,
            "raw_text": ai_result.get("raw_text", fallback_text or ""),
            "processing_notes_text": notes_text,
            "processing_notes_meta": {},
        }
    return convert_ai_v2_payload(ai_result, fallback_text)


def log_icon_summary(entries: List[Dict[str, Any]]) -> None:
    if not entries:
        return
    storage_status = "✔" if icons_sv_storage else "✖"
    manifest_status = "✔" if ICON_MANIFEST_DATA else "✖"
    logging.info("[icons] storage loaded %s  manifest loaded %s", storage_status, manifest_status)
    logging.info("[icons] requests: %d", len(entries))
    status_counts = {"ok": 0, "warn": 0, "err": 0}
    for entry in entries:
        status = entry.get("status", "ok")
        status_counts[status] = status_counts.get(status, 0) + 1
        colors = entry.get("colors", {})
        ai_colors = entry.get("ai_colors", {})
        raw_colors = entry.get("raw_colors", {})
        bg = colors.get("background") or "default"
        a1 = colors.get("ascent1") or "default"
        a2 = colors.get("ascent2") or "default"
        cap = colors.get("cap") or "-"
        label = entry.get("label") or entry.get("icon_key") or "unknown"
        warnings = entry.get("warnings") or []
        warning_note = f" [{' | '.join(warnings)}]" if warnings else ""
        glyph = {"ok": "✔", "warn": "⚠", "err": "✖"}.get(status, "•")
        logging.info(
            "  • %s (key=%s) … icon_colors(background=%s, ascent1=%s, ascent2=%s, cap=%s) %s%s",
            label,
            entry.get("icon_key") or "n/a",
            bg,
            a1,
            a2,
            cap,
            glyph,
            warning_note,
        )
        logging.info("      raw_colors=%s  ai_sanitized=%s", raw_colors or "{}", ai_colors or "{}")
    logging.info(
        "[icons] done: ok=%d warn=%d err=%d",
        status_counts.get("ok", 0),
        status_counts.get("warn", 0),
        status_counts.get("err", 0),
    )


def build_colored_icon(icon_key: Optional[str], color_inputs: Dict[str, Optional[str]]) -> Optional[str]:
    """Generate a base64 SVG data URI for the given icon key and color inputs."""
    if not icon_key or not ICON_COLOR_READY or not ColorInputs or not recolor_svg or not icons_sv_storage or not ICON_MANIFEST_DATA:
        return None
    try:
        colors = ColorInputs.from_dict(color_inputs)
        svg = recolor_svg(icon_key, colors, icons_sv_storage, ICON_MANIFEST_DATA)
        data_uri = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{data_uri}"
    except Exception as exc:  # pragma: no cover - log but do not fail request
        logging.error(f"Icon recolor failed for {icon_key}: {exc}")
        return None


HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
RGB_COLOR_PATTERN = re.compile(r"rgb\s*\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")
CSS_COLOR_MAP: Dict[str, str] = {
    "white": "#ffffff",
    "black": "#000000",
    "silver": "#d6d6d6",
    "gray": "#9ca3af",
    "grey": "#9ca3af",
    "lightgray": "#d1d5db",
    "lightgrey": "#d1d5db",
    "darkgray": "#4b5563",
    "darkgrey": "#4b5563",
    "blue": "#2563eb",
    "lightblue": "#60a5fa",
    "skyblue": "#38bdf8",
    "navy": "#1e3a8a",
    "teal": "#0d9488",
    "aqua": "#0891b2",
    "cyan": "#06b6d4",
    "green": "#22c55e",
    "darkgreen": "#15803d",
    "lime": "#84cc16",
    "yellow": "#facc15",
    "amber": "#f59e0b",
    "orange": "#f97316",
    "red": "#dc2626",
    "maroon": "#7f1d1d",
    "pink": "#ec4899",
    "magenta": "#db2777",
    "purple": "#9333ea",
    "violet": "#8b5cf6",
    "brown": "#92400e",
    "gold": "#fbbf24",
    "beige": "#f5f5dc",
    "cream": "#fff4e6",
}


def sanitize_hex_color(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if not candidate.startswith("#"):
        candidate = f"#{candidate}"
    if not HEX_COLOR_PATTERN.fullmatch(candidate):
        return None
    if len(candidate) == 4:
        candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
    return candidate.upper()


def basic_text_parse(text: str) -> Dict[str, Any]:
    """Very simple heuristic parser for common patterns when LLM is unavailable."""
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
    frequency = freq if freq is not None else DEFAULT_FREQUENCY
    normalized_form = normalize_medication_sector(form) if form else None
    times = default_times_for_frequency(frequency)

    med: Dict[str, Any] = {
        "medicine_name": medicine_name,
        "display_name": None,
        "form": normalized_form or (form if form else None),
        "dosage": dosage,
        "frequency": frequency,
        "times": times,
        "course_duration_days": duration,
        "start_date": None,
        "medication_color": None,
        "background_color": None,
        "quantity": DEFAULT_QUANTITY,
        "administration_instruction": DEFAULT_ADMINISTRATION_INSTRUCTION,
        "icon_colors": {
            "background": None,
            "ascent1": None,
            "ascent2": None,
            "cap": None,
        },
    }

    notes = "Parsed with heuristic fallback; values may be incomplete and require user confirmation."
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

        system_message = """Role: You are an extraction + structuring agent for medication prescriptions (image, text, or audio+ASR). Produce a single JSON object that our backend can ingest without missing required fields.

HARD RULES (obey exactly):
1. Never omit `icon.colors` roles. If unsure, output `"use_default"` and the server will substitute manifest defaults.
2. `background` and `ascent1` are always required (HEX or `"use_default"`).
3. `ascent2` must always be present; if you cannot derive it, set `"use_default"` (backend derives from ascent1).
4. `cap` is ONLY used for bottle forms {mouthwash, lotion, syrup, ointment, sprays}. For all other forms you must omit the cap key entirely.
5. If you cannot determine a color even after reasonable inference, return `"use_default"` (never leave blanks, never use named colors or rgb()).
6. Icon key must be one of our 14 kebab-case identifiers: tablets, capsules, sachets, gum, inserts, ointment, lotion, patches, syrup, mouthwash, sprays, drops, injections, inhalers.
7. If the form is unclear, infer the most plausible category from context, output it, and note the assumption under `processing_notes.assumptions`.
8. Keep `display_name` empty (users will supply their own).
9. Validation echo: populate `processing_notes.validation_summary` with a checklist like `Validated: count ✔, schema ✔, required_colors ✔, caps ✔, times ✔`.

COLOR FORMAT
• Use lowercase HEX `#rrggbb`.  
• `"use_default"` means “fallback to manifest default.”  
• Never output rgb()/hsl() or named colors.  
• When an image is provided, inspect the real pill/blister/bottle colors (packaging background, pill body, cap). Only fall back to `"use_default"` when the surface is genuinely obscured in the photo.
• Tablets/Capsules/Sachets/Gum: `background` must reflect the blister/strip color seen in the image (silver, blue, etc.). Do not use `"use_default"` unless the sheet is not visible.
• If any slot is forced to `"use_default"`, add an assumption explaining why (e.g., "background not visible in photo"). If the surface is visible, approximate the HEX color and provide it—never return `"use_default"` just because it is difficult.

ICON KEY REFERENCE
• tablets, capsules, sachets, gum, inserts, ointment, lotion, patches, syrup, mouthwash, sprays, drops, injections, inhalers

TIMING / QUANTITY
• `quantity` is free text (e.g., "10 tablets", "1 strip").  
• `frequency` is human-readable ("2x/day", "once nightly").  
• `times` list should contain normalized labels or HH:MM slots if provided.  
• `course_duration` stays textual ("5 days", "2 weeks")—use empty string if unknown.  
• `instructions` is any patient directive such as "After meals".

OUTPUT SCHEMA (return ONLY this JSON object):
{
  "source": "image|audio|text",
  "medications": [
    {
      "name": "string",
      "form": "tablets|capsules|sachets|gum|inserts|ointment|lotion|patches|syrup|mouthwash|sprays|drops|injections|inhalers",
      "quantity": "string",
      "frequency": "string",
      "times": ["string"],
      "course_duration": "string",
      "instructions": "string",
      "icon": {
        "key": "one-of-14-keys",
        "colors": {
          "background": "#rrggbb|use_default",
          "ascent1": "#rrggbb|use_default",
          "ascent2": "#rrggbb|use_default",
          "cap": "#rrggbb|use_default"   // include ONLY for bottle forms
        }
      },
      "meta": {
        "confidence": 0.0
      }
    }
  ],
  "processing_notes": {
    "assumptions": ["string"],
    "validation_summary": "Validated: count ✔, schema ✔, required_colors ✔, caps ✔, times ✔"
  }
}

ASSUMPTIONS & FALLBACKS
• Every time you output `"use_default"` for any color slot, record the reason in `processing_notes.assumptions` (e.g., "background not visible on photo").
• If a blister/bottle color is visible in the image, approximate its HEX value (even if estimated) and use it instead of `"use_default"`.
• Mention other inference leaps (e.g., "form inferred as tablets based on wording") in the assumptions list as well.

MINI FEW-SHOT GUIDANCE
• Tablets example: background `"use_default"`, ascent1 `#ffffff`, no cap key.  
• Syrup example: include cap (`#ff9900`), times like ["morning","afternoon","night"].  
• Lotion defaulting colors: set every slot to `"use_default"` if uncertain.

GENERAL REMINDERS
• Always set `icon.colors.background` and `icon.colors.ascent1` (HEX or `"use_default"`).  
• If you default anything, mention it in `processing_notes.assumptions`.  
• Ensure final JSON validates against the schema above. No extra fields, no trailing commentary.
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
        logging.info("[ai_full_response] %s", response_text)
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
    fallback_text = request.text or request.voice_transcription or ("Image processed" if request.image_base64 else "")
    normalized_ai = normalize_ai_output(ai_result, fallback_text)
    medications: List[MedicationSchedule] = []
    current_start_date = datetime.now(timezone.utc).date().isoformat()
    max_meds = int(os.getenv('MAX_MEDICATIONS_PER_REQUEST', '20'))
    meds_in = normalized_ai.get("medications", [])[:max_meds]
    icon_logs: List[Dict[str, Any]] = []
    for med_data in meds_in:
        raw_form = med_data.get("form")
        normalized_form = normalize_medication_sector(raw_form) if raw_form else None
        icon_key_hint = med_data.get("icon_key_hint")
        icon_key = None
        if icon_key_hint and icon_key_hint in AVAILABLE_ICON_KEYS:
            icon_key = icon_key_hint
        else:
            icon_key = icon_key_for_sector(normalized_form)
        color_inputs = extract_icon_color_inputs(med_data)
        icon_svg = build_colored_icon(icon_key, color_inputs)

        icon_colors_final = finalize_icon_colors(icon_key, color_inputs)
        medication_color = icon_colors_final.get("ascent1") or sanitize_hex_color(med_data.get("medication_color"))
        background_color = icon_colors_final.get("background") or sanitize_hex_color(med_data.get("background_color"))

        quantity = parse_quantity(med_data.get("quantity"))
        if quantity is None:
            quantity = DEFAULT_QUANTITY

        frequency_raw = med_data.get("frequency")
        frequency = None
        if isinstance(frequency_raw, int) and frequency_raw > 0:
            frequency = frequency_raw
        else:
            frequency = parse_frequency(frequency_raw) or parse_frequency_label(str(frequency_raw)) if frequency_raw else None
        normalized_times = normalize_times_field(med_data.get("times"))
        if frequency is None:
            frequency = len(normalized_times) if normalized_times else DEFAULT_FREQUENCY
        times_in = ensure_times_for_frequency(normalized_times, frequency)
        frequency = frequency or len(times_in) or DEFAULT_FREQUENCY

        course_duration_days = med_data.get("course_duration_days")
        parsed_duration = parse_positive_int(course_duration_days)

        admin_instruction = med_data.get("administration_instruction") or med_data.get("meal_instruction") or med_data.get("timing_instruction")
        if isinstance(admin_instruction, str):
            admin_instruction = admin_instruction.strip() or None
        if not admin_instruction:
            admin_instruction = DEFAULT_ADMINISTRATION_INSTRUCTION

        medication = MedicationSchedule(
            user_id=request.user_id,
            device_id=request.device_id,
            medicine_name=med_data.get("medicine_name"),
            display_name=None,
            form=normalized_form or (raw_form.strip() if isinstance(raw_form, str) and raw_form.strip() else None),
            icon_svg=icon_svg,
            medication_color=medication_color,
            background_color=background_color,
            icon_colors=IconColorSlots(**icon_colors_final),
            quantity=quantity,
            dosage=med_data.get("dosage"),
            frequency=frequency,
            times=times_in,
            course_duration_days=parsed_duration,
            administration_instruction=admin_instruction,
            start_date=current_start_date
        )
        medications.append(medication)

        warnings: List[str] = []
        status = "ok"
        if not icon_key:
            status = "err"
            warnings.append("icon key missing")
        if not icon_svg:
            status = "warn" if status != "err" else "err"
            warnings.append("icon svg missing")
        if not icon_colors_final.get("background"):
            warnings.append("background defaulted")
        if not icon_colors_final.get("ascent1"):
            warnings.append("ascent1 defaulted")
        if normalized_form and normalized_form.lower() in BOTTLE_FORMS and not icon_colors_final.get("cap"):
            warnings.append("cap defaulted")
        if warnings and status == "ok":
            status = "warn"
        icon_logs.append({
            "label": normalized_form or raw_form,
            "icon_key": icon_key,
            "colors": icon_colors_final,
            "ai_colors": color_inputs,
            "raw_colors": med_data.get("icon_colors_raw"),
            "status": status,
            "warnings": warnings,
        })

    log_icon_summary(icon_logs)
    
    # Store in database
    if db is not None and medications:
        for medication in medications:
            med_dict = prepare_for_mongo(medication.dict())
            await db.medications.insert_one(med_dict)
    
    processing_notes_text = normalized_ai.get("processing_notes_text", "Processed with advanced medical AI")
    raw_text_out = normalized_ai.get("raw_text", fallback_text)

    return ProcessedPrescription(
        medications=medications,
        raw_text=raw_text_out or fallback_text or "Processed prescription",
        processing_notes=processing_notes_text
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
