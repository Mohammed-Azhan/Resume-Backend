import os
import json
import fitz  
import docx
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
import io
from dotenv import load_dotenv
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
genai.configure(api_key=API_KEY)

app = FastAPI(
    title="Resume Parser API",
    description="An API that parses resumes (PDF, DOCX) using Gemini and returns structured JSON data.",
    version="1.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",  # Allow all origins including file:// protocol (null origin)
    allow_credentials=True,
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
    The JSON output must strictly adhere to the following schema.
    JSON Schema:
    {json.dumps(schemas.ResumeData.model_json_schema(), indent=2)}
    
    Resume Text:
    {resume_text}
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        # Use await correctly
        response = await model.generate_content_async(prompt)
        
        # DEBUG: Print the response to terminal to see what Gemini said
        print("DEBUG Gemini Response:", response.text)

        # Clean the response
        text_content = response.text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        
        parsed_json = json.loads(text_content.strip())
        return schemas.ResumeData(**parsed_json)

    except Exception as e:
        # THIS LINE IS CRITICAL: It will print the exact error in your VS Code terminal
        print(f"CRITICAL ERROR IN PARSING: {str(e)}")
        import traceback
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/parse-resume/", response_model=schemas.ResumeData, tags=["Resume Parsing"])
async def parse_and_save_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload a resume file (PDF or DOCX), parse it, save the result to the database,
    and return the structured content.
    """
    if not file.content_type in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        raise HTTPException(status_code=400, detail="Unsupported file type. Please upload a PDF or DOCX file.")
    
    file_bytes = await file.read()
    raw_text = ""
    
    if file.content_type == "application/pdf":
        raw_text = extract_text_from_pdf(file_bytes)
    else:
        raw_text = extract_text_from_docx(file_bytes)
    
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from the document.")
    
    structured_data = await parse_resume_with_gemini(raw_text)
    crud.create_or_update_resume(db=db, resume_data=structured_data)
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
            id=db_resume.id,  # Add this line
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
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
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
# New endpoints to add

@app.post("/resumes/{resume_id}/analyze", tags=["Analysis"])
async def analyze_resume(resume_id: int, db: Session = Depends(get_db)):
    """
    Analyze and score an existing resume
    """
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Reconstruct resume text for analysis
    resume_text = f"""
    {db_resume.summary or ''}
    {' '.join([skill.name for skill in db_resume.skills])}
    {' '.join([exp.description or '' for exp in db_resume.work_experiences])}
    """
    
    scorer = ResumeScorer()
    analysis = scorer.generate_score(resume_text)
    
    # Save score to database
    from datetime import datetime
    existing_score = db.query(models.ResumeScore).filter(
        models.ResumeScore.resume_id == resume_id
    ).first()
    
    if existing_score:
        existing_score.overall_score = analysis["overall_score"]
        existing_score.skills_score = analysis["skills_score"]
        existing_score.readability_score = analysis["readability_score"]
        existing_score.grammar_score = analysis["grammar_score"]
        existing_score.analysis_date = datetime.now().isoformat()
    else:
        new_score = models.ResumeScore(
            resume_id=resume_id,
            overall_score=analysis["overall_score"],
            skills_score=analysis["skills_score"],
            readability_score=analysis["readability_score"],
            grammar_score=analysis["grammar_score"],
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
    Get AI-powered suggestions to improve resume
    """
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Generate suggestions using Gemini
    resume_context = f"""
    Summary: {resume.summary}
    Skills: {', '.join([s.name for s in resume.skills])}
    Experience: {len(resume.work_experiences)} positions
    Projects: {len(resume.projects)} projects
    Education: {len(resume.educations)} degrees
    """
    
    prompt = f"""
    Analyze this resume and provide 5-7 specific, actionable suggestions to improve it:
    {resume_context}
    
    Focus on:
    1. Missing important sections
    2. Skill gaps for current market
    3. How to better highlight achievements
    4. Formatting and structure improvements
    5. Keywords to add for ATS systems
    
    Return as JSON array of suggestions with "category" and "suggestion" fields.
    """
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = await model.generate_content_async(prompt)
    
    import json
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
    from sqlalchemy import func
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
async def analyze_resume(email: str, db: Session = Depends(get_db)):
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
        score_data = scorer.generate_score(resume_text)
        
        # Save score to database
        existing_score = db.query(models.ResumeScore).filter(
            models.ResumeScore.resume_id == resume.id
        ).first()
        
        if existing_score:
            existing_score.overall_score = score_data["overall_score"]
            existing_score.skills_score = score_data["skills_score"]
            existing_score.readability_score = score_data["readability_score"]
            existing_score.grammar_score = score_data["grammar_score"]
            existing_score.analysis_date = datetime.now().isoformat()
        else:
            new_score = models.ResumeScore(
                resume_id=resume.id,
                overall_score=score_data["overall_score"],
                skills_score=score_data["skills_score"],
                readability_score=score_data["readability_score"],
                grammar_score=score_data["grammar_score"],
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
        
        # Get suggestions from Gemini
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        
        # Parse JSON response
        suggestions_text = response.text.strip()
        if suggestions_text.startswith("```json"):
            suggestions_text = suggestions_text.replace("```json", "").replace("```", "").strip()
        
        suggestions = json.loads(suggestions_text)
        
        return suggestions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ENDPOINT 3: Get All Resumes (for My Resumes page)
@app.get("/resumes/")
async def get_all_resumes(db: Session = Depends(get_db)):
    """
    Get list of all resumes
    """
    try:
        resumes = db.query(models.PersonalInfo).all()
        
        result = []
        for info in resumes:
            resume = info.resume
            result.append({
                "name": info.name,
                "email": info.email,
                "phone": info.phone,
                "skills_count": len(resume.skills),
                "projects_count": len(resume.projects),
                "education": resume.educations[0].institution if resume.educations else None,
                "has_score": resume.score is not None
            })
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ENDPOINT 4: Get Resume by Email (for View page)
@app.get("/resume/{email}")
async def get_resume_by_email(email: str, db: Session = Depends(get_db)):
    """
    Get complete resume data by email
    """
    try:
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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