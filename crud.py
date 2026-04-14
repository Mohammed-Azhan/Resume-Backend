from sqlalchemy.orm import Session
import models, schemas

def get_or_create_skill(db: Session, skill_name: str):
    """Finds an existing skill or creates a new one."""
    skill = db.query(models.Skill).filter(models.Skill.name == skill_name).first()
    if not skill:
        skill = models.Skill(name=skill_name)
        db.add(skill)
        db.commit()
        db.refresh(skill)
    return skill

def create_or_update_resume(db: Session, resume_data: schemas.ResumeData, file_hash: str = None):
    """
    Creates a new resume record or updates an existing one based on email or phone number.
    Stores the file_hash for dedup caching so identical re-uploads skip the Gemini API call.
    """
    email = resume_data.personal_info.email
    phone = resume_data.personal_info.phone

    # Find an existing resume by checking for a match in personal_info
    existing_info = None
    if email:
        existing_info = db.query(models.PersonalInfo).filter(models.PersonalInfo.email == email).first()
    if not existing_info and phone:
        existing_info = db.query(models.PersonalInfo).filter(models.PersonalInfo.phone == phone).first()

    if existing_info:
        db_resume = existing_info.resume
        print(f"--- Updating existing resume ID: {db_resume.id} ---")

        db_resume.summary = resume_data.summary

        db_resume.skills.clear()
        db_resume.work_experiences.clear()
        db_resume.projects.clear()
        db_resume.educations.clear()

        if file_hash:
            db_resume.file_hash = file_hash

        existing_info.name = resume_data.personal_info.name
        existing_info.email = resume_data.personal_info.email
        existing_info.phone = resume_data.personal_info.phone
        existing_info.location = resume_data.personal_info.location
        existing_info.linkedin_url = resume_data.personal_info.linkedin_url

    else:
        print("--- Creating new resume ---")
        db_resume = models.Resume(file_hash=file_hash, summary=resume_data.summary )
        db.add(db_resume)
        # Create new PersonalInfo and link it
        personal_info_data = resume_data.personal_info.model_dump()
        db_personal_info = models.PersonalInfo(**personal_info_data, resume=db_resume)
        db.add(db_personal_info)

    
    # Skills (Many-to-Many)
    if resume_data.skills:
        for skill_name in resume_data.skills:
            skill = get_or_create_skill(db, skill_name)
            db_resume.skills.append(skill)
            
    # Work Experience
    if resume_data.work_experience:
        for exp in resume_data.work_experience:
            db_resume.work_experiences.append(models.WorkExperience(**exp.model_dump()))

    # Projects
    if resume_data.projects:
        for proj in resume_data.projects:
            proj_data = proj.model_dump()
            if proj_data.get("technologies"):
                proj_data["technologies"] = ", ".join(proj_data["technologies"])
            db_resume.projects.append(models.Project(**proj_data))

    # Education
    if resume_data.education:
        for edu in resume_data.education:
            db_resume.educations.append(models.Education(**edu.model_dump()))

    db.commit()
    db.refresh(db_resume)
    return db_resume