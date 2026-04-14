import os
import json
import hashlib
import fitz  
import docx
from google import genai
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import io
from sqlalchemy import func
from dotenv import load_dotenv
import hashlib
from typing import List
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import crud, models, schemas
from fastapi.middleware.cors import CORSMiddleware
from scoring import ResumeScorer
from datetime import datetime


# Initialize scorer (add after app initialization)
scorer = ResumeScorer()


models.Base.metadata.create_all(bind=engine)

load_dotenv()
try:
    API_KEY = os.environ["GEMINI_API_KEY"]
except KeyError:
    API_KEY = "YOUR_GEMINI_API_KEY"

if API_KEY == "YOUR_GEMINI_API_KEY":
    print("Warning: GEMINI_API_KEY is not set. Please replace 'YOUR_GEMINI_API_KEY' or set the environment variable.")

# Initialize the new SDK client
gemini_client = genai.Client(api_key=API_KEY) if API_KEY != "YOUR_GEMINI_API_KEY" else None

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
async def parse_and_save_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):

    if not file.content_type in [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    file_bytes = await file.read()

    import hashlib
    
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    existing_resume = db.query(models.Resume).filter(
        models.Resume.file_hash == file_hash
    ).first()

    # ✅ Only use cache if summary exists
    if existing_resume:
        print("Returning cached resume")
        return schemas.ResumeData.model_validate(existing_resume)


    raw_text = ""
    if file.content_type == "application/pdf":
        raw_text = extract_text_from_pdf(file_bytes)
    else:
        raw_text = extract_text_from_docx(file_bytes)
    
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text.")

    structured_data = await parse_resume_with_gemini(raw_text)

    # Save to DB with the hash for future caching
    db_resume = crud.create_or_update_resume(db=db, resume_data=structured_data, file_hash=file_hash)
    
    # Ensure ID is included in the response
    structured_data.id = db_resume.id
    return structured_data

@app.get("/resumes/{resume_id}", response_model=schemas.ResumeData, tags=["Database"])
def read_resume(resume_id: int, db: Session = Depends(get_db)):
    """
    Retrieve a parsed resume from the database by its ID.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if db_resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    return schemas.ResumeData(
        personal_info=db_resume.personal_info,
        summary=db_resume.summary,
        skills=db_resume.skills,
        work_experience=db_resume.work_experiences,
        projects=db_resume.projects,
        education=db_resume.educations
    )

@app.get("/resumes/search/", response_model=schemas.ResumeData, tags=["Database"])
def search_resume_by_email(email: str, db: Session = Depends(get_db)):
    """
    Retrieve a parsed resume from the database by the candidate's email address.
    """
    personal_info = db.query(models.PersonalInfo).filter(models.PersonalInfo.email == email).first()
    if personal_info is None or personal_info.resume is None:
        raise HTTPException(status_code=404, detail="Resume not found for the provided email")
    
    # Convert SQLAlchemy model to Pydantic schema
    return schemas.ResumeData(
        personal_info=personal_info,
        summary=personal_info.resume.summary,
        skills=personal_info.resume.skills,
        work_experience=personal_info.resume.work_experiences,
        projects=personal_info.resume.projects,
        education=personal_info.resume.educations
    )

@app.get("/resumes/", response_model=List[schemas.ResumeData], tags=["Database"])
def list_all_resumes(db: Session = Depends(get_db)):
    resumes = db.query(models.Resume).all()
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
def delete_resume_by_id_legacy(resume_id: int, db: Session = Depends(get_db)):
    """
    Delete a resume from the database by its ID.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if db_resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    db.delete(db_resume)
    db.commit()
    return {"message": f"Resume with ID {resume_id} has been deleted successfully"}


@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Resume Parser API. Go to /docs for the API documentation."}


@app.post("/resumes/{resume_id}/analyze", tags=["Analysis"])
async def analyze_resume(resume_id: int, db: Session = Depends(get_db)):
    """
    Analyze and score an existing resume.
    Returns cached DB score on repeat calls — no Gemini round-trip needed.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

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
async def match_resume_to_job(resume_id: int, job_id: int, db: Session = Depends(get_db)):
    """
    Match a resume to a job posting and calculate compatibility score
    """
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    job = db.query(models.JobPosting).filter(models.JobPosting.id == job_id).first()
    
    if not resume or not job:
        raise HTTPException(status_code=404, detail="Resume or Job not found")
    
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
async def get_resume_suggestions(resume_id: int, db: Session = Depends(get_db)):
    """
    Get AI-powered suggestions to improve resume (uses gemini-2.5-flash for speed)
    """
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

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
    db: Session = Depends(get_db)
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
        "share_link":   f"/resume/view/{version.unique_url}"
    }


@app.get("/resumes/{resume_id}/versions", tags=["Versioning"])
def list_resume_versions(resume_id: int, db: Session = Depends(get_db)):
    """
    List all versions created for a given resume.
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    versions = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.resume_id == resume_id
    ).all()

    return [
        {
            "id":           v.id,
            "version_name": v.version_name,
            "unique_url":   v.unique_url,
            "created_at":   v.created_at,
            "share_link":   f"/resume/view/{v.unique_url}"
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
def delete_resume_version(resume_id: int, version_id: int, db: Session = Depends(get_db)):
    """
    Delete a specific resume version by ID.
    """
    version = db.query(models.ResumeVersion).filter(
        models.ResumeVersion.id == version_id,
        models.ResumeVersion.resume_id == resume_id
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
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
    return RedirectResponse(url=f"/app/resume_view.html?url={unique_url}")


# ── Serve frontend static files ──────────────────────────────────────────────
# Mount AFTER all API routes so API paths take precedence
try:
    app.mount("/app", StaticFiles(directory="resumehub-frontend/public", html=True), name="frontend")
except Exception:
    pass  # Skip if directory not found (e.g., in tests)
