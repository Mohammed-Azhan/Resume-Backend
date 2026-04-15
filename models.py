from sqlalchemy import Column, Integer, String, Text, ForeignKey, Table
from sqlalchemy.orm import relationship
from database import Base

# ── User model (auth) ─────────────────────────────────────────────────────────
class User(Base):
    """
    Stores authenticated user accounts.
    Each user owns a set of resumes (via user_id FK on Resume).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(String, nullable=True)

    # back-reference to owned resumes
    resumes = relationship("Resume", back_populates="owner")

# Association table for the many-to-many relationship between Resume and Skill
resume_skill_association = Table('resume_skill_association', Base.metadata,
    Column('resume_id', Integer, ForeignKey('resumes.id')),
    Column('skill_id', Integer, ForeignKey('skills.id'))
)

class Resume(Base):
    __tablename__ = "resumes"
    id = Column(Integer, primary_key=True, index=True)
    summary = Column(Text, nullable=True)
    file_hash = Column(String, nullable=True, index=True)  # SHA-256 of raw file bytes for dedup caching (per-user)
    
    personal_info = relationship("PersonalInfo", back_populates="resume", uselist=False, cascade="all, delete-orphan")
    skills = relationship("Skill", secondary=resume_skill_association, back_populates="resumes")
    work_experiences = relationship("WorkExperience", back_populates="resume", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="resume", cascade="all, delete-orphan")
    educations = relationship("Education", back_populates="resume", cascade="all, delete-orphan")
    score = relationship("ResumeScore", back_populates="resume", uselist=False, cascade="all, delete-orphan")

    # owner (nullable so old/anonymous resumes keep working)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    owner = relationship("User", back_populates="resumes")

class PersonalInfo(Base):
    __tablename__ = "personal_info"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    name = Column(String, index=True)
    email = Column(String, index=True, nullable=True)
    phone = Column(String, index=True, nullable=True)
    location = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    resume = relationship("Resume", back_populates="personal_info")

class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    resumes = relationship("Resume", secondary=resume_skill_association, back_populates="skills")

class WorkExperience(Base):
    __tablename__ = "work_experience"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    company = Column(String)
    job_title = Column(String)
    start_date = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    resume = relationship("Resume", back_populates="work_experiences")

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    name = Column(String)
    description = Column(Text, nullable=True)
    technologies = Column(String, nullable=True)
    resume = relationship("Resume", back_populates="projects")

class Education(Base):
    __tablename__ = "education"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    institution = Column(String)
    degree = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    resume = relationship("Resume", back_populates="educations")

class ResumeScore(Base):
    __tablename__ = "resume_scores"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), unique=True)
    overall_score = Column(Integer)
    skills_score = Column(Integer)
    readability_score = Column(Integer)
    grammar_score = Column(Integer)
    matched_skills = Column(Text, nullable=True) # JSON string
    missing_skills = Column(Text, nullable=True) # JSON string
    analysis_date = Column(String)
    resume = relationship("Resume", back_populates="score")

class JobPosting(Base):
    __tablename__ = "job_postings"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    company = Column(String)
    description = Column(Text)
    required_skills = Column(Text)
    created_at = Column(String)
    matches = relationship("ResumeJobMatch", back_populates="job")

class ResumeJobMatch(Base):
    __tablename__ = "resume_job_matches"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    job_id = Column(Integer, ForeignKey("job_postings.id"))
    match_score = Column(Integer)
    matched_skills = Column(Text)
    created_at = Column(String)
    resume = relationship("Resume")
    job = relationship("JobPosting", back_populates="matches")


# ── NEW: Resume Versioning ─────────────────────────────────────────────────────
class ResumeVersion(Base):
    """
    Stores editable snapshots of a resume, each with a unique shareable URL.
    Does NOT touch or modify any column of the existing Resume model.
    """
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"))

    version_name = Column(String)
    unique_url = Column(String, unique=True, index=True)

    summary = Column(Text)
    skills = Column(Text)        # JSON string: ["Python", "React", ...]
    experience = Column(Text)    # JSON string: [{company, job_title, ...}, ...]
    projects = Column(Text)      # JSON string: [{name, description, ...}, ...]
    education = Column(Text)     # JSON string: [{institution, degree, ...}, ...]

    created_at = Column(String)