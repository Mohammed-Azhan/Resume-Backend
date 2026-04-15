import os
import json
import hashlib
import logging
import fitz  
import docx
from google import genai
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Security
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
import io
from sqlalchemy import func, text, inspect as sa_inspect
from dotenv import load_dotenv
import hashlib
from typing import List, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import crud, models, schemas
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import joinedload
from scoring import ResumeScorer
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel as PydanticBaseModel


# Initialize scorer (add after app initialization)
scorer = ResumeScorer()

FRONTEND_URL = "https://resumehub-nsoa8u22x-mohammed-azhans-projects.vercel.app"


models.Base.metadata.create_all(bind=engine)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resumeiq")

load_dotenv()

# ── SQLite migration: ensure user_id column exists on resumes table ───────────────
try:
    with engine.connect() as _conn:
        _existing_cols = [col["name"] for col in sa_inspect(engine).get_columns("resumes")]
        if "user_id" not in _existing_cols:
            _conn.execute(text("ALTER TABLE resumes ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            _conn.commit()
            logger.info("Migration: added user_id column to resumes table")
except Exception as _migration_err:
    logger.warning(f"Migration note: {_migration_err}")

# ── SQLite migration: drop legacy UNIQUE indexes that block multi-user uploads ───
# SQLAlchemy's unique=True creates named indexes (e.g. ix_resumes_file_hash).
# We drop them here so existing databases get patched automatically on restart.
_UNIQUE_INDEXES_TO_DROP = [
    "ix_resumes_file_hash",
    "ix_personal_info_email",
    "ix_personal_info_phone",
]
try:
    with engine.begin() as _conn:
        for _idx in _UNIQUE_INDEXES_TO_DROP:
            _conn.execute(text(f"DROP INDEX IF EXISTS {_idx}"))
        # Re-create as non-unique indexes for query performance
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_resumes_file_hash ON resumes(file_hash)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_personal_info_email ON personal_info(email)"))
        _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_personal_info_phone ON personal_info(phone)"))
    logger.info("Migration: unique index constraints checked/patched")
except Exception as _idx_err:
    logger.warning(f"Index migration note: {_idx_err}")
try:
    API_KEY = os.environ["GEMINI_API_KEY"]
except KeyError:
    API_KEY = "YOUR_GEMINI_API_KEY"

if API_KEY == "YOUR_GEMINI_API_KEY":
    print("Warning: GEMINI_API_KEY is not set. Please replace 'YOUR_GEMINI_API_KEY' or set the environment variable.")

# Initialize the new SDK client
gemini_client = genai.Client(api_key=API_KEY) if API_KEY != "YOUR_GEMINI_API_KEY" else None

# ── Auth configuration ─────────────────────────────────────────────────────────────────────────────────
_SECRET_KEY_RAW = os.environ.get("SECRET_KEY")
if not _SECRET_KEY_RAW:
    logger.warning(
        "SECRET_KEY is not set in environment — using insecure default. "
        "Set SECRET_KEY in your .env file before deploying."
    )
    _SECRET_KEY_RAW = "resumeiq-super-secret-key-change-in-production-2024"
SECRET_KEY = _SECRET_KEY_RAW
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


# ── Auth Pydantic schemas ─────────────────────────────────────────────────────────
class SignupRequest(PydanticBaseModel):
    email: str
    password: str
    username: str = ""

class LoginRequest(PydanticBaseModel):
    email: str
    password: str

app = FastAPI(
    title="Resume Parser API",
    description="An API that parses resumes (PDF, DOCX) using Gemini and returns structured JSON data.",
    version="1.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r".*",  # Allow all origins including file:// protocol (null origin)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Auth helper functions ─────────────────────────────────────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def _decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        uid = payload.get("sub")
        return int(uid) if uid is not None else None
    except (JWTError, ValueError):
        return None

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    db: Session = Depends(get_db)
) -> models.User:
    """Required auth dependency — raises HTTP 401 if missing or invalid token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")
    uid = _decode_token(credentials.credentials)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user = db.query(models.User).filter(models.User.id == uid).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user

def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    db: Session = Depends(get_db)
) -> Optional[models.User]:
    """Optional auth dependency — returns None if not logged in."""
    if not credentials:
        return None
    uid = _decode_token(credentials.credentials)
    if uid is None:
        return None
    return db.query(models.User).filter(models.User.id == uid).first()

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        return text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF file: {e}")

def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing DOCX file: {e}")

async def parse_resume_with_gemini(resume_text: str) -> schemas.ResumeData:
    prompt = f"""
    You are an expert resume parsing AI. Your task is to extract key information from the following resume text and provide the output in a clean, structured JSON format.
    
CRITICAL RULES:
- ALWAYS extract CAREER SUMMARY or PROFESSIONAL SUMMARY if it exists
- DO NOT skip summary under any condition
- Summary is usually at the top of the resume
- If summary exists, it MUST be placed in "summary"
- If summary is missing, return an empty string ""

STRICT JSON ONLY. NO TEXT.

    JSON Schema:
    {json.dumps(schemas.ResumeData.model_json_schema(), indent=2)}
    
    Resume Text:
    {resume_text}
    """
    try:
        if not gemini_client:
            raise ValueError("GEMINI_API_KEY is missing")
            
        # gemini-2.5-flash: faster for structured JSON extraction than thinking models
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        # DEBUG: Print the response to terminal to see what Gemini said
        print("DEBUG Gemini Response:", response.text)

        # Clean the response
        text_content = response.text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        
        parsed_json = json.loads(text_content.strip())
        parsed_json["summary"] = parsed_json.get("summary") or resume_text[:300]
        return schemas.ResumeData(**parsed_json)

    except Exception as e:
        # THIS LINE IS CRITICAL: It will print the exact error in your VS Code terminal
        print(f"CRITICAL ERROR IN PARSING: {str(e)}")
        import traceback
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/parse-resume/", response_model=schemas.ResumeData)
async def parse_and_save_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):

    if not file.content_type in [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    file_bytes = await file.read()

    import hashlib
    
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Cache lookup scoped to this user — prevents cross-user cache collisions
    
    existing_resume = db.query(models.Resume).options(
    joinedload(models.Resume.personal_info),
    joinedload(models.Resume.skills),
    joinedload(models.Resume.projects),
    joinedload(models.Resume.work_experiences),
    joinedload(models.Resume.educations),
).filter(
    models.Resume.file_hash == file_hash,
    models.Resume.user_id == current_user.id,
).first()

    # Only serve cache if the resume is complete (has a summary)
    if existing_resume and existing_resume.summary:
        print("Returning cached resume")
        return schemas.ResumeData(
    id=existing_resume.id,
    personal_info=existing_resume.personal_info,
    summary=existing_resume.summary,
    skills=existing_resume.skills,
    work_experience=existing_resume.work_experiences,
    projects=existing_resume.projects,
    education=existing_resume.educations
)

    raw_text = ""
    if file.content_type == "application/pdf":
        raw_text = extract_text_from_pdf(file_bytes)
    else:
        raw_text = extract_text_from_docx(file_bytes)

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text.")

    structured_data = await parse_resume_with_gemini(raw_text)

    # CRUD owns all DB writes and user_id assignment — no patching in main.py
    db_resume = crud.create_or_update_resume(
        db=db,
        resume_data=structured_data,
        file_hash=file_hash,
        user_id=current_user.id,
    )

    structured_data.id = db_resume.id
    return structured_data


@app.get("/resumes/{resume_id}", response_model=schemas.ResumeData, tags=["Database"])
def read_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Retrieve a resume by ID. Only the owner may access it."""
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if db_resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        logger.warning(f"Unauthorized access attempt: user {current_user.id} → resume {resume_id}")
        raise HTTPException(status_code=403, detail="Not authorized to access this resume")
    return schemas.ResumeData(
        id=db_resume.id,
        personal_info=db_resume.personal_info,
        summary=db_resume.summary,
        skills=db_resume.skills,
        work_experience=db_resume.work_experiences,
        projects=db_resume.projects,
        education=db_resume.educations
    )

@app.get("/resumes/search/", response_model=schemas.ResumeData, tags=["Database"])
def search_resume_by_email(
    email: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Search for a resume by email. Scoped to the authenticated user's own resumes."""
    personal_info = (
        db.query(models.PersonalInfo)
        .join(models.Resume)
        .filter(
            models.PersonalInfo.email == email,
            models.Resume.user_id == current_user.id,
        )
        .first()
    )
    if personal_info is None or personal_info.resume is None:
        raise HTTPException(status_code=404, detail="Resume not found for the provided email")
    r = personal_info.resume
    return schemas.ResumeData(
        id=r.id,
        personal_info=personal_info,
        summary=r.summary,
        skills=r.skills,
        work_experience=r.work_experiences,
        projects=r.projects,
        education=r.educations
    )

@app.get("/resumes/", response_model=List[schemas.ResumeData], tags=["Database"])
def list_all_resumes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Returns ONLY the resumes owned by the currently authenticated user."""
    resumes = db.query(models.Resume).filter(
        models.Resume.user_id == current_user.id
    ).all()
    result = []
    for db_resume in resumes:
        resume_data = schemas.ResumeData(
            id=db_resume.id,
            personal_info=db_resume.personal_info,
            summary=db_resume.summary,
            skills=db_resume.skills,
            work_experience=db_resume.work_experiences,
            projects=db_resume.projects,
            education=db_resume.educations
        )
        result.append(resume_data)
    return result

@app.delete("/resumes/{resume_id}", tags=["Database"])
def delete_resume_by_id_legacy(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Delete a resume by ID. Only the owner of the resume can delete it.
    Requires a valid JWT Bearer token.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if db_resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to delete this resume")
    db.delete(db_resume)
    db.commit()
    return {"message": f"Resume with ID {resume_id} has been deleted successfully"}


@app.get("/", tags=["Root"])
async def read_root():
    return RedirectResponse(url="/landing.html")


@app.post("/resumes/{resume_id}/analyze", tags=["Analysis"])
async def analyze_resume(
    resume_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Analyze and score an existing resume.
    Returns cached DB score on repeat calls — no Gemini round-trip needed.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    existing_score = db.query(models.ResumeScore).filter(
        models.ResumeScore.resume_id == resume_id
    ).first()

    # ── Return cached DB score if it already exists (avoid Gemini call) ──────
    if existing_score:
        return {
            "overall_score":     existing_score.overall_score,
            "skills_score":      existing_score.skills_score,
            "readability_score": existing_score.readability_score,
            "grammar_score":     existing_score.grammar_score,
            "matched_skills":    json.loads(existing_score.matched_skills) if existing_score.matched_skills else [],
            "target_skills":     [], # Leaving target_skills empty is fine, frontend only needs matched/missing
            "missing_skills":    json.loads(existing_score.missing_skills) if existing_score.missing_skills else [],
            "feedback": {
                "skills":      "Great job on listing relevant skills!" if existing_score.skills_score > 50 else "Consider adding more role-specific skills.",
                "readability": "Your resume is easy to read."        if existing_score.readability_score > 60 else "Try using shorter sentences.",
                "grammar":     "Excellent grammar!"                  if existing_score.grammar_score > 80 else "Found grammar issues.",
            },
            "grammar_errors": [],
        }

    # ── First-time analysis: reconstruct text and call Gemini ────────────────
    resume_text = (
        f"{db_resume.summary or ''}\n"
        f"{' '.join(skill.name for skill in db_resume.skills)}\n"
        f"{' '.join(exp.description or '' for exp in db_resume.work_experiences)}"
    )

    # Use the global singleton scorer (SpaCy model already loaded)
    # The scorer itself has an in-memory cache that accurately preserves matched_skills & missing_skills
    analysis = await scorer.generate_score(resume_text)

    # ── Persist score to DB ──────────────────────────────────────────────────
    new_score = models.ResumeScore(
        resume_id=resume_id,
        overall_score=analysis["overall_score"],
        skills_score=analysis["skills_score"],
        readability_score=analysis["readability_score"],
        grammar_score=analysis["grammar_score"],
        matched_skills=json.dumps(analysis.get("matched_skills", [])),
        missing_skills=json.dumps(analysis.get("missing_skills", [])),
        analysis_date=datetime.now().isoformat()
    )
    db.add(new_score)
        
    db.commit()
    return analysis

@app.post("/jobs/", tags=["Job Matching"])
async def create_job_posting(job: schemas.JobPostingCreate, db: Session = Depends(get_db)):
    """
    Create a new job posting for matching
    """
    from datetime import datetime
    import json
    
    db_job = models.JobPosting(
        title=job.title,
        company=job.company,
        description=job.description,
        required_skills=json.dumps(job.required_skills),
        created_at=datetime.now().isoformat()
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job


@app.post("/match/resume/{resume_id}/job/{job_id}", tags=["Job Matching"])
async def match_resume_to_job(
    resume_id: int, 
    job_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Match a resume to a job posting and calculate compatibility score
    """
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    job = db.query(models.JobPosting).filter(models.JobPosting.id == job_id).first()
    
    if not resume or not job:
        raise HTTPException(status_code=404, detail="Resume or Job not found")
    if resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    import json
    from datetime import datetime
    
    # Get resume skills
    resume_skills = set([skill.name.lower() for skill in resume.skills])
    
    # Get required job skills
    required_skills = set([s.lower() for s in json.loads(job.required_skills)])
    
    # Calculate match
    matched = resume_skills.intersection(required_skills)
    match_percentage = (len(matched) / len(required_skills) * 100) if required_skills else 0
    
    # Save match
    db_match = models.ResumeJobMatch(
        resume_id=resume_id,
        job_id=job_id,
        match_score=int(match_percentage),
        matched_skills=json.dumps(list(matched)),
        created_at=datetime.now().isoformat()
    )
    db.add(db_match)
    db.commit()
    
    return {
        "match_score": int(match_percentage),
        "matched_skills": list(matched),
        "missing_skills": list(required_skills - resume_skills),
        "total_required": len(required_skills),
        "total_matched": len(matched)
    }

@app.get("/resumes/{resume_id}/suggestions", tags=["AI Suggestions"])
async def get_resume_suggestions(
    resume_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Get AI-powered suggestions to improve resume (uses gemini-2.5-flash for speed)
    """
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    resume_context = (
        f"Summary: {resume.summary}\n"
        f"Skills: {', '.join(s.name for s in resume.skills)}\n"
        f"Experience: {len(resume.work_experiences)} positions\n"
        f"Projects: {len(resume.projects)} projects\n"
        f"Education: {len(resume.educations)} degrees"
    )

    prompt = f"""Analyze this resume and provide 5-7 specific, actionable suggestions to improve it:
{resume_context}

Focus on:
1. Missing important sections
2. Skill gaps based on his field/interests (only useful skills for the user's current field)
3. How to better highlight achievements
4. Formatting and structure improvements
5. Keywords to add for ATS systems

Return as JSON array of suggestions with "category" and "suggestion" fields."""

    # gemini-2.5-flash is 3-5x faster than gemini-2.5-flash for structured JSON tasks
    response = await gemini_client.aio.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)

    suggestions_text = response.text
    if "```json" in suggestions_text:
        suggestions_text = suggestions_text.split("```json")[1].split("```")[0]

    return json.loads(suggestions_text.strip())

@app.get("/analytics/dashboard", tags=["Analytics"])
async def get_dashboard_analytics(db: Session = Depends(get_db)):
    """
    Get overall platform analytics
    """
    total_resumes = db.query(models.Resume).count()
    total_jobs = db.query(models.JobPosting).count()
    avg_score = db.query(func.avg(models.ResumeScore.overall_score)).scalar() or 0
    
    # Top skills across all resumes
    top_skills = db.query(
        models.Skill.name, 
        func.count(models.resume_skill_association.c.resume_id).label('count')
    ).join(
        models.resume_skill_association
    ).group_by(
        models.Skill.name
    ).order_by(
        func.count(models.resume_skill_association.c.resume_id).desc()
    ).limit(10).all()
    
    return {
        "total_resumes": total_resumes,
        "total_jobs": total_jobs,
        "average_resume_score": round(avg_score, 2),
        "top_skills": [{"skill": s[0], "count": s[1]} for s in top_skills]
    }
@app.post("/analyze-resume/{email}")
async def analyze_resume_v2(email: str, db: Session = Depends(get_db)):
    """
    Analyzes a resume and returns detailed scoring
    """
    try:
        # Get resume from database
        personal_info = db.query(models.PersonalInfo).filter(
            models.PersonalInfo.email == email
        ).first()
        
        if not personal_info:
            raise HTTPException(status_code=404, detail="Resume not found")
        
        resume = personal_info.resume
        
        # Compile resume text for analysis
        resume_text = f"""
        Name: {personal_info.name}
        Email: {personal_info.email}
        Phone: {personal_info.phone}
        
        Skills: {', '.join([skill.name for skill in resume.skills])}
        
        Projects:
        """
        
        for project in resume.projects:
            resume_text += f"\n{project.name}: {project.description}"
        
        for edu in resume.educations:
            resume_text += f"\n{edu.degree} at {edu.institution}"
        
        # Generate score using ResumeScorer
        score_data = await scorer.generate_score(resume_text)
        
        # Save score to database
        existing_score = db.query(models.ResumeScore).filter(
            models.ResumeScore.resume_id == resume.id
        ).first()
        
        if existing_score:
            existing_score.overall_score = score_data["overall_score"]
            existing_score.skills_score = score_data["skills_score"]
            existing_score.readability_score = score_data["readability_score"]
            existing_score.grammar_score = score_data["grammar_score"]
            existing_score.matched_skills = json.dumps(score_data.get("matched_skills", []))
            existing_score.missing_skills = json.dumps(score_data.get("missing_skills", []))
            existing_score.analysis_date = datetime.now().isoformat()
        else:
            new_score = models.ResumeScore(
                resume_id=resume.id,
                overall_score=score_data["overall_score"],
                skills_score=score_data["skills_score"],
                readability_score=score_data["readability_score"],
                grammar_score=score_data["grammar_score"],
                matched_skills=json.dumps(score_data.get("matched_skills", [])),
                missing_skills=json.dumps(score_data.get("missing_skills", [])),
                analysis_date=datetime.now().isoformat()
            )
            db.add(new_score)
        
        db.commit()
        
        return score_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ENDPOINT 2: Get AI-Powered Suggestions
@app.get("/get-suggestions/{email}")
async def get_suggestions(email: str, db: Session = Depends(get_db)):
    """
    Get AI-powered suggestions for resume improvement using Gemini
    """
    try:
        # Get resume from database
        personal_info = db.query(models.PersonalInfo).filter(
            models.PersonalInfo.email == email
        ).first()
        
        if not personal_info:
            raise HTTPException(status_code=404, detail="Resume not found")
        
        resume = personal_info.resume
        
        # Compile resume data
        resume_data = {
            "name": personal_info.name,
            "email": personal_info.email,
            "skills": [skill.name for skill in resume.skills],
            "projects": [
                {
                    "name": p.name,
                    "description": p.description,
                    "technologies": p.technologies
                } for p in resume.projects
            ],
            "education": [
                {
                    "degree": e.degree,
                    "institution": e.institution
                } for e in resume.educations
            ],
            "work_experience": [
                {
                    "company": w.company,
                    "title": w.job_title,
                    "description": w.description
                } for w in resume.work_experiences
            ]
        }
        
        # Create prompt for Gemini
        prompt = f"""
        Analyze this resume and provide specific, actionable suggestions for improvement.
        
        Resume Data:
        {json.dumps(resume_data, indent=2)}
        
        Provide suggestions in 4 categories:
        1. Content Improvements (how to better describe experience, achievements)
        2. Skills Enhancement (missing skills, skills to highlight)
        3. Formatting & Structure (organization, clarity)
        4. Professional Impact (how to make resume stand out)
        
        For each category, provide 3-5 specific suggestions.
        Format your response as JSON with this structure:
        {{
            "content": [
                {{"text": "suggestion text", "example": "example if applicable"}}
            ],
            "skills": [...],
            "formatting": [...],
            "impact": [...]
        }}
        
        Make suggestions specific and actionable.
        """
        
        # Get suggestions from Gemini (async – does not block the event loop)
        response = await gemini_client.aio.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)
        
        # Parse JSON response
        suggestions_text = response.text.strip()
        if suggestions_text.startswith("```json"):
            suggestions_text = suggestions_text.replace("```json", "").replace("```", "").strip()
        
        suggestions = json.loads(suggestions_text)
        
        return suggestions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# # ENDPOINT 3: Get All Resumes (for My Resumes page — used by index.html)
# @app.get("/resumes/")
# async def get_all_resumes(db: Session = Depends(get_db)):
#     """
#     Get list of all resumes
#     """
#     try:
#         resumes = db.query(models.PersonalInfo).all()
        
#         result = []
#         for info in resumes:
#             resume = info.resume
#             result.append({
#                 "name": info.name,
#                 "email": info.email,
#                 "phone": info.phone,
#                 "skills_count": len(resume.skills),
#                 "projects_count": len(resume.projects),
#                 "education": resume.educations[0].institution if resume.educations else None,
#                 "has_score": resume.score is not None
#             })
        
#         return result
        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# ENDPOINT 4: Get Resume by Email (legacy — kept for reference but not used by frontend)
# Frontend uses GET /resumes/ for lists and POST /resumes/{id}/analyze for details.
@app.get("/resume/{email}", tags=["Database"])
async def get_resume_by_email(email: str, db: Session = Depends(get_db)):
    """
    Get complete resume data by email (legacy endpoint, kept for backward compatibility)
    """
    personal_info = db.query(models.PersonalInfo).filter(
        models.PersonalInfo.email == email
    ).first()
    
    if not personal_info:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    resume = personal_info.resume
    
    return {
        "personal_info": {
            "name": personal_info.name,
            "email": personal_info.email,
            "phone": personal_info.phone,
            "location": personal_info.location,
            "linkedin": personal_info.linkedin_url
        },
        "skills": [skill.name for skill in resume.skills],
        "projects": [
            {
                "name": p.name,
                "description": p.description,
                "technologies": p.technologies.split(',') if p.technologies else []
            } for p in resume.projects
        ],
        "education": [
            {
                "degree": e.degree,
                "institution": e.institution,
                "end_date": e.end_date
            } for e in resume.educations
        ],
        "work_experience": [
            {
                "company": w.company,
                "job_title": w.job_title,
                "description": w.description,
                "start_date": w.start_date,
                "end_date": w.end_date
            } for w in resume.work_experiences
        ],
        "score": {
            "overall": resume.score.overall_score if resume.score else None,
            "skills": resume.score.skills_score if resume.score else None,
            "readability": resume.score.readability_score if resume.score else None,
            "grammar": resume.score.grammar_score if resume.score else None
        } if resume.score else None
    }
# ENDPOINT 5: Delete Resume
@app.delete("/resume/{email}")
async def delete_resume(email: str, db: Session = Depends(get_db)):
    """
    Delete a resume by email
    """
    try:
        personal_info = db.query(models.PersonalInfo).filter(
            models.PersonalInfo.email == email
        ).first()
        
        if not personal_info:
            raise HTTPException(status_code=404, detail="Resume not found")
        
        resume = personal_info.resume
        
        # Delete resume (cascade will delete related records)
        db.delete(resume)
        db.commit()
        
        return {"message": "Resume deleted successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── NEW: Resume Versioning Endpoints ──────────────────────────────────────────

import uuid as _uuid

@app.post("/resumes/{resume_id}/create-version", tags=["Versioning"])
async def create_resume_version(
    resume_id: int,
    version_data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Create a new shareable version snapshot of a resume.
    Pre-fills from the existing resume; caller may override any field.
    Returns the unique shareable URL token.
    """
    # Fetch the source resume
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Generate a collision-safe 8-char unique token
    for _ in range(10):         # retry loop in case of collision (extremely unlikely)
        token = str(_uuid.uuid4())[:8]
        if not db.query(models.ResumeVersion).filter(
            models.ResumeVersion.unique_url == token
        ).first():
            break

    # Build defaults from the source resume
    default_skills = json.dumps([s.name for s in db_resume.skills])
    default_experience = json.dumps([
        {
            "company":    exp.company,
            "job_title":  exp.job_title,
            "start_date": exp.start_date,
            "end_date":   exp.end_date,
            "description": exp.description
        }
        for exp in db_resume.work_experiences
    ])
    default_projects = json.dumps([
        {
            "name":         proj.name,
            "description":  proj.description,
            "technologies": proj.technologies
        }
        for proj in db_resume.projects
    ])
    default_education = json.dumps([
        {
            "institution": edu.institution,
            "degree":      edu.degree,
            "end_date":    edu.end_date
        }
        for edu in db_resume.educations
    ])

    # Allow caller to override individual fields
    version = models.ResumeVersion(
        resume_id=resume_id,
        version_name=version_data.get("version_name", "My Version"),
        unique_url=token,
        summary=version_data.get("summary", db_resume.summary or ""),
        skills=version_data.get("skills", default_skills),
        experience=version_data.get("experience", default_experience),
        projects=version_data.get("projects", default_projects),
        education=version_data.get("education", default_education),
        created_at=datetime.now().isoformat()
    )

    db.add(version)
    db.commit()
    db.refresh(version)

    return {
        "id":           version.id,
        "resume_id":    version.resume_id,
        "version_name": version.version_name,
        "unique_url":   version.unique_url,
        "created_at":   version.created_at,
        "share_link": f"{FRONTEND_URL}/resume_view.html?url={version.unique_url}"
    }


@app.get("/resumes/{resume_id}/versions", tags=["Versioning"])
def list_resume_versions(
    resume_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    List all versions created for a given resume.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    versions = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.resume_id == resume_id
    ).all()

    def safe_json(text, fallback):
        if not text:
            return fallback
        try:
            return json.loads(text)
        except:
            return fallback

    return [
{
    "id": v.id,
    "version_name": v.version_name,
    "summary": v.summary,
    "skills": safe_json(v.skills, []),          # ✅ FIX
    "experience": safe_json(v.experience, []),  # ✅ FIX
    "projects": safe_json(v.projects, []),      # ✅ FIX
    "education": safe_json(v.education, []),    # ✅ FIX
    "unique_url": v.unique_url,
    "created_at": v.created_at
}
for v in versions
]

@app.get("/resume/view/{unique_url}", tags=["Versioning"])
def view_resume_version(unique_url: str, db: Session = Depends(get_db)):
    """
    Public endpoint — no auth required.
    Returns the full content of a specific resume version by its unique_url token.
    """
    version = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.unique_url == unique_url
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")

    # Safely parse JSON fields; fall back to sensible defaults
    def safe_json(text, fallback):
        if not text:
            return fallback
        try:
            return json.loads(text)
        except Exception:
            return fallback

    return {
        "id":           version.id,
        "resume_id":    version.resume_id,
        "version_name": version.version_name,
        "unique_url":   version.unique_url,
        "created_at":   version.created_at,
        "summary":      version.summary or "",
        "skills":       safe_json(version.skills, []),
        "experience":   safe_json(version.experience, []),
        "projects":     safe_json(version.projects, []),
        "education":    safe_json(version.education, []),
    }


@app.delete("/resumes/{resume_id}/versions/{version_id}", tags=["Versioning"])
def delete_resume_version(
    resume_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Delete a specific resume version by ID. Only the resume owner may delete it.
    """
    # Verify the parent resume exists and belongs to this user
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.user_id != current_user.id:
        logger.warning(f"Unauthorized version delete: user {current_user.id} → resume {resume_id}")
        raise HTTPException(status_code=403, detail="Not authorized")

    version = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.id == version_id,
        models.ResumeVersion.resume_id == resume_id
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    logger.info(f"Version '{version.version_name}' (id={version_id}) deleted by user {current_user.id}")
    db.delete(version)
    db.commit()
    return {"message": f"Version '{version.version_name}' deleted successfully"}


@app.get("/v/{unique_url}", tags=["Versioning"])
def shortlink_redirect(unique_url: str, db: Session = Depends(get_db)):
    """
    Clean shareable short URL — redirects to the public resume view page.
    Works from any device on the same network.
    """
    version = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.unique_url == unique_url
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")
    return RedirectResponse(
    url=f"{FRONTEND_URL}/resume_view.html?url={unique_url}"
)



# ── Auth Endpoints ────────────────────────────────────────────────────────────────────────────────────────

@app.post("/auth/signup", tags=["Auth"])
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """Create a new user account and return a JWT access token."""
    existing = db.query(models.User).filter(models.User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    user = models.User(
        email=request.email,
        username=request.username.strip() or request.email.split("@")[0],
        hashed_password=get_password_hash(request.password),
        created_at=datetime.now().isoformat()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }


@app.post("/auth/login", tags=["Auth"])
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email + password and return a JWT access token."""
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }


@app.get("/auth/me", tags=["Auth"])
def get_me(current_user: models.User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return {"id": current_user.id, "email": current_user.email, "username": current_user.username}





@app.put("/resumes/{resume_id}/versions/{version_id}", tags=["Versioning"])
def update_resume_version(
    resume_id: int,
    version_id: int,
    updated_data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Check ownership
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if db_resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Get version
    version = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.id == version_id,
        models.ResumeVersion.resume_id == resume_id
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # 🔥 Update fields (only if provided)
    if "version_name" in updated_data:
        version.version_name = updated_data["version_name"]

    if "summary" in updated_data:
        version.summary = updated_data["summary"]

    if "skills" in updated_data:
        version.skills = updated_data["skills"]

    if "experience" in updated_data:
        version.experience = updated_data["experience"]

    if "projects" in updated_data:
        version.projects = updated_data["projects"]

    if "education" in updated_data:
        version.education = updated_data["education"]

    db.commit()
    db.refresh(version)

    return {"message": "Version updated successfully"}


# ── Serve frontend static files ──────────────────────────────────────────────
# Mount AFTER all API routes so API paths take precedence
try:
    app.mount("", StaticFiles(directory="resumehub-frontend/public", html=True), name="frontend")
except Exception:
    pass  # Skip if directory not found (e.g., in tests)

