from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional

# This ConfigDict replaces the old `class Config: orm_mode = True`
# and makes the models compatible with SQLAlchemy.
orm_config = ConfigDict(from_attributes=True)

class PersonalInfo(BaseModel):
    name: Optional[str] = Field(None, description="Full name of the candidate.")
    email: Optional[str] = Field(None, description="Primary email address.")
    phone: Optional[str] = Field(None, description="Primary phone number.")
    location: Optional[str] = Field(None, description="City and state, e.g., 'San Francisco, CA'.")
    linkedin_url: Optional[str] = Field(None, alias="linkedin", description="URL to LinkedIn profile.")
    model_config = orm_config

class WorkExperience(BaseModel):
    company: Optional[str] = Field(None, description="Name of the company.")
    job_title: Optional[str] = Field(None, description="Job title or position.")
    start_date: Optional[str] = Field(None, description="Start date in YYYY-MM format.")
    end_date: Optional[str] = Field(None, description="End date in YYYY-MM format or 'Present'.")
    description: Optional[str] = Field(None, description="A brief summary of responsibilities and achievements.")
    model_config = orm_config

class Project(BaseModel):
    name: Optional[str] = Field(None, description="The name or title of the project.")
    description: Optional[str] = Field(None, description="A description of the project.")
    technologies: Optional[List[str]] = Field([], description="List of technologies or skills used in the project.")
    model_config = orm_config

    # This validator converts the comma-separated string from the database
    # back into a list of strings for the API response.
    @field_validator('technologies', mode='before')
    @classmethod
    def split_technologies(cls, v):
        if isinstance(v, str):
            return [tech.strip() for tech in v.split(',')]
        return v

class Education(BaseModel):
    institution: Optional[str] = Field(None, description="Name of the university or institution.")
    degree: Optional[str] = Field(None, description="Degree obtained, e.g., 'Bachelor of Science in Computer Science'.")
    end_date: Optional[str] = Field(None, description="Graduation or end date in YYYY-MM format.")
    model_config = orm_config

class ResumeData(BaseModel):
    id: Optional[int] = None 
    personal_info: PersonalInfo
    summary: Optional[str] = Field(None, description="A professional summary or objective statement from the resume.")
    skills: Optional[List[str]] = Field([], description="A list of key skills and technologies.")
    work_experience: List[WorkExperience] = []
    projects: List[Project] = []
    education: List[Education] = []
    model_config = orm_config

    # This validator converts the list of Skill objects from the database
    # into a simple list of skill names (strings) for the API response.
    @field_validator('skills', mode='before')
    @classmethod
    def skills_to_strings(cls, v):
        if v and hasattr(v[0], 'name'): # Check if it's a list of objects with a 'name' attribute
            return [skill.name for skill in v]
        return v


from pydantic import BaseModel
from typing import List, Optional

class ResumeScoreSchema(BaseModel):
    overall_score: int
    skills_score: int
    readability_score: int
    grammar_score: int
    analysis_date: str

class JobPostingCreate(BaseModel):
    title: str
    company: str
    description: str
    required_skills: List[str]

class ResumeJobMatchSchema(BaseModel):
    match_score: int
    matched_skills: List[str]
    missing_skills: List[str]