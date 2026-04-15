from sqlalchemy.orm import Session
import models, schemas


def get_or_create_skill(db: Session, skill_name: str) -> models.Skill:
    """
    Finds an existing skill (case-insensitive) or creates a new one.
    All skill names are stored in lowercase to prevent duplicates like 'Python' vs 'python'.
    Does NOT commit — the caller is responsible for committing.
    """
    normalized = skill_name.strip().lower()
    skill = db.query(models.Skill).filter(models.Skill.name == normalized).first()
    if not skill:
        skill = models.Skill(name=normalized)
        db.add(skill)
        db.flush()   # flush so the skill gets an ID within this transaction
    return skill


def create_or_update_resume(
    db: Session,
    resume_data: schemas.ResumeData,
    file_hash: str = None,
    user_id: int = None,        # ← CRUD now owns user_id assignment
) -> models.Resume:
    """
    Creates a new resume record or updates an existing one.

    Isolation rules (production-grade):
    - Email / phone lookup is scoped to the same user_id so two users
      with the same email never collide.
    - file_hash cache lookup is also scoped to user_id for the same reason.
    - user_id is always assigned here; callers never need to patch it afterward.
    - A single db.commit() is executed at the very end.
    """
    email = resume_data.personal_info.email
    phone = resume_data.personal_info.phone

    # ── 1. Find an existing resume scoped to this user ─────────────────────
    existing_info = None

    if email and user_id is not None:
        existing_info = (
            db.query(models.PersonalInfo)
            .join(models.Resume)
            .filter(
                models.PersonalInfo.email == email,
                models.Resume.user_id == user_id,
            )
            .first()
        )

    if not existing_info and phone and user_id is not None:
        existing_info = (
            db.query(models.PersonalInfo)
            .join(models.Resume)
            .filter(
                models.PersonalInfo.phone == phone,
                models.Resume.user_id == user_id,
            )
            .first()
        )

    # ── 2. Update existing or create new ──────────────────────────────────
    if existing_info:
        db_resume = existing_info.resume
        print(f"--- Updating existing resume ID: {db_resume.id} ---")

        db_resume.summary = resume_data.summary
        if file_hash:
            db_resume.file_hash = file_hash
        # Always (re-)assign owner on update so orphaned records get fixed
        if user_id is not None:
            db_resume.user_id = user_id

        # Clear child collections before repopulating
        db_resume.skills.clear()
        db_resume.work_experiences.clear()
        db_resume.projects.clear()
        db_resume.educations.clear()

        existing_info.name = resume_data.personal_info.name
        existing_info.email = resume_data.personal_info.email
        existing_info.phone = resume_data.personal_info.phone
        existing_info.location = resume_data.personal_info.location
        existing_info.linkedin_url = resume_data.personal_info.linkedin_url

    else:
        print("--- Creating new resume ---")
        db_resume = models.Resume(
            file_hash=file_hash,
            summary=resume_data.summary,
            user_id=user_id,        # always set at creation time
        )
        db.add(db_resume)
        personal_info_data = resume_data.personal_info.model_dump()
        db_personal_info = models.PersonalInfo(**personal_info_data, resume=db_resume)
        db.add(db_personal_info)
        db.flush()  # gives db_resume its PK before appending children

    # ── 3. Skills (Many-to-Many, case-insensitive, single transaction) ──────
    if resume_data.skills:
        for skill_name in resume_data.skills:
            skill = get_or_create_skill(db, skill_name)   # no commit inside
            db_resume.skills.append(skill)

    # ── 4. Work Experience ───────────────────────────────────────────────────
    if resume_data.work_experience:
        for exp in resume_data.work_experience:
            db_resume.work_experiences.append(models.WorkExperience(**exp.model_dump()))

    # ── 5. Projects ──────────────────────────────────────────────────────────
    if resume_data.projects:
        for proj in resume_data.projects:
            proj_data = proj.model_dump()
            if proj_data.get("technologies"):
                proj_data["technologies"] = ", ".join(proj_data["technologies"])
            db_resume.projects.append(models.Project(**proj_data))

    # ── 6. Education ─────────────────────────────────────────────────────────
    if resume_data.education:
        for edu in resume_data.education:
            db_resume.educations.append(models.Education(**edu.model_dump()))

    # ── 7. Single commit for the entire operation ─────────────────────────────
    db.commit()
    db.refresh(db_resume)
    return db_resume