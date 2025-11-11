Backend API (Mobile-ready)

Overview
- FastAPI service providing AI-assisted prescription processing and CRUD for medication schedules.
- Designed to tolerate missing fields. If AI cannot extract items, fields remain null and can be completed client-side.
- AWS-friendly: Configure via environment variables; compatible with API Gateway/LB. MongoDB via `MONGO_URL`.

Environment
- Copy `.env.example` to `.env` and set values.
- Required: `MONGO_URL` (MongoDB Atlas/DocumentDB) and `DB_NAME`.
- Optional: `OPENAI_API_KEY` (enables Whisper transcription and GPT-4o OCR/field extraction). When absent, a heuristic parser supplies best-effort results.
- Safety limits: `MAX_IMAGE_SIZE_MB`, `MAX_AUDIO_SIZE_MB`, and `MAX_MEDICATIONS_PER_REQUEST`.

Key Endpoints (prefix `/api`)
- `POST /transcribe-audio` — `{ text, confidence?, duration? }` (multipart `file` or JSON `{audio_base64,mime_type}`; caps size and optional duration)
- `GET /health` — `{ status, db, time }`.
- `POST /process-prescription` — `{ medications: Medication[], raw_text, processing_notes }`.
  - Body: `{ text?, image_base64?, voice_transcription?, user_id?, device_id? }`.
  - Stores returned medications to DB (when DB connected), tagged with `user_id` and `device_id` if provided.
- `GET /medications?user_id&device_id` — list of medications, optionally filtered.
- `GET /medications/{id}` — medication by id.
- `POST /medications` — create manually (all fields optional).
- `DELETE /medications/{id}` — delete.

Medication Model
```
{
  id: string,
  user_id?: string,
  device_id?: string,
  medicine_name?: string,
  display_name?: string,
  form?: string,
  icon_svg?: string (base64 SVG data URI),
  medication_color?: string (hex),
  background_color?: string (hex),
  icon_colors?: {
    background?: string,
    ascent1?: string,
    ascent2?: string,
    cap?: string,
  },
  quantity?: number,
  dosage?: string,
  frequency?: number,
  times?: string[],
  course_duration_days?: number,
  administration_instruction?: string,
  start_date?: string (YYYY-MM-DD),
  created_at: ISO datetime
}
```

SVG Icon Pipeline
- Base SVGs live in `icons_sv_storage.py` and are never modified directly.
- `icons_color_algorithm.py` + `icons.color.manifest.json` define how fills get swapped for the slots (`background`, `ascent1`, `ascent2`, `cap`).
- The AI response must supply the `icon_colors` object (HEX values). The backend recolors the correct base icon, converts it to a `data:image/svg+xml;base64,...` URI, and returns/stores it in `icon_svg` along with finalized colors inside `icon_colors`.
- `medication_color` mirrors `icon_colors.ascent1` and `background_color` mirrors `icon_colors.background` for legacy UI styling.

Prescription Defaults
- `display_name` is always left null so patients can add their own nicknames.
- `start_date` is auto-set to the processing date; AI should not fill it.
- `frequency` defaults to 1 if omitted, and `times` are auto-generated (08:00 for once daily, 08:00/20:00 for twice daily, etc.).
- `quantity` defaults to `1.0` when the source does not specify a value.
- `administration_instruction` defaults to `"After meals"` unless the prescription explicitly says otherwise.
- Missing icon colors fall back to the manifest defaults, ensuring every medication ships with a consistent color payload.

Mobile Integration Notes
- Native apps can call the REST endpoints directly; no web dependencies required.
- Use `user_id` (and optionally `device_id`) to scope data per user/device.
- The service returns partial objects. Clients should allow users to confirm/correct fields.
- When `OPENAI_API_KEY` is not configured, the fallback parser supports simple phrases and OD/BD/TDS/QDS.

Scalability
- Async I/O via FastAPI + Motor for MongoDB.
- DB indexes on `id`, `user_id`, `device_id` created on startup.
- Use AWS API Gateway/ALB for TLS, rate limiting, and WAF. Horizontal scale via containers.

CORS
- Controlled via `CORS_ORIGINS` env var (comma-separated), defaults to `*` for development.
