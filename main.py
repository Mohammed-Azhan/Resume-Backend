import os
import json
import fitz  
import docx
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import io
from dotenv import load_dotenv
from typing import List
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import crud, models, schemas
from fastapi.middleware.cors import CORSMiddleware
from scoring import ResumeScorer
from datetime import datetime
from sqlalchemy import func


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
# CORS configuration
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
import os as _os
if _os.path.exists("resumehub-frontend/public"):
    try:
        app.mount("/static", StaticFiles(directory="resumehub-frontend/public"), name="static")
    except Exception as e:
        print(f"Warning: Could not mount static files: {e}")

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
    """Serve the frontend application"""
    try:
        return FileResponse("resumehub-frontend/public/index.html")
    except FileNotFoundError:
        return {"message": "Welcome to the Resume Parser API. Go to /docs for the API documentation."}
# New endpoints to add

@app.post("/resumes/{resume_id}/analyze", tags=["Analysis"])
async def analyze_resume(resume_id: int, db: Session = Depends(get_db)):
    """
    Analyze and score an existing resume
    """
    try:
        db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
        if not db_resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        
        # BUILD COMPREHENSIVE RESUME TEXT
        resume_parts = []
        
        # Add personal info
        if db_resume.personal_info:
            resume_parts.append(f"Name: {db_resume.personal_info.name}")
            if db_resume.personal_info.email:
                resume_parts.append(f"Email: {db_resume.personal_info.email}")
            if db_resume.personal_info.phone:
                resume_parts.append(f"Phone: {db_resume.personal_info.phone}")
            if db_resume.personal_info.location:
                resume_parts.append(f"Location: {db_resume.personal_info.location}")
        
        # Add summary
        if db_resume.summary:
            resume_parts.append(f"\nSummary:\n{db_resume.summary}")
        
        # Add skills
        if db_resume.skills:
            skills_text = ', '.join([skill.name for skill in db_resume.skills])
            resume_parts.append(f"\nSkills:\n{skills_text}")
        
        # Add work experience
        if db_resume.work_experiences:
            resume_parts.append("\nWork Experience:")
            for exp in db_resume.work_experiences:
                resume_parts.append(f"\n{exp.job_title or 'Position'} at {exp.company or 'Company'}")
                if exp.start_date or exp.end_date:
                    date_range = f"{exp.start_date or 'Start'} - {exp.end_date or 'Present'}"
                    resume_parts.append(date_range)
                if exp.description:
                    resume_parts.append(exp.description)
        
        # Add projects
        if db_resume.projects:
            resume_parts.append("\nProjects:")
            for project in db_resume.projects:
                resume_parts.append(f"\n{project.name}")
                if project.description:
                    resume_parts.append(project.description)
                if project.technologies:
                    resume_parts.append(f"Technologies: {project.technologies}")
        
        # Add education
        if db_resume.educations:
            resume_parts.append("\nEducation:")
            for edu in db_resume.educations:
                resume_parts.append(f"{edu.degree or 'Degree'} from {edu.institution or 'Institution'}")
                if edu.end_date:
                    resume_parts.append(f"Graduated: {edu.end_date}")
        
        # Combine all parts
        resume_text = '\n'.join(resume_parts)
        
        # DEBUG LOGGING
        print(f"DEBUG: Analyzing resume ID {resume_id}")
        print(f"DEBUG: Resume text length: {len(resume_text)} characters")
        print(f"DEBUG: First 200 chars: {resume_text[:200]}")
        
        # Check if text is too short
        if len(resume_text.strip()) < 100:
            print("WARNING: Resume text is very short, this may affect scoring")
            # Add default text to ensure scoring works
            resume_text += "\n\nThis is a professional resume showcasing skills and experience in technology and software development."
        
        # Generate score
        scorer = ResumeScorer()
        analysis = scorer.generate_score(resume_text)
        
        print(f"DEBUG: Analysis scores - Overall: {analysis['overall_score']}, Skills: {analysis['skills_score']}, Readability: {analysis['readability_score']}, Grammar: {analysis['grammar_score']}")
        
        # Save score to database
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
        
    except Exception as e:
        print(f"CRITICAL ERROR in analyze_resume: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error analyzing resume: {str(e)}")

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


# Railway deployment configuration
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
