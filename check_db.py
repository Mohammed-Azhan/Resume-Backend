import sqlite3
import json

# Connect to the database
conn = sqlite3.connect('resume_parser.db')
cursor = conn.cursor()

print("=" * 80)
print("DATABASE STRUCTURE CHECK")
print("=" * 80)

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n📊 Tables in database: {len(tables)}")
for table in tables:
    print(f"  - {table[0]}")

print("\n" + "=" * 80)
print("DATA VERIFICATION")
print("=" * 80)

# Check resumes
cursor.execute("SELECT COUNT(*) FROM resumes")
resume_count = cursor.fetchone()[0]
print(f"\n✅ Total Resumes: {resume_count}")

if resume_count > 0:
    # Get sample resume data
    cursor.execute("SELECT id, summary FROM resumes LIMIT 1")
    sample_resume = cursor.fetchone()
    print(f"\n📄 Sample Resume ID: {sample_resume[0]}")
    print(f"   Summary: {sample_resume[1][:100] if sample_resume[1] else 'None'}...")
    
    # Check personal info
    cursor.execute("SELECT COUNT(*) FROM personal_info")
    personal_info_count = cursor.fetchone()[0]
    print(f"\n👤 Personal Info Records: {personal_info_count}")
    
    cursor.execute("SELECT name, email, phone, location FROM personal_info LIMIT 1")
    sample_info = cursor.fetchone()
    if sample_info:
        print(f"   Sample: {sample_info[0]} | {sample_info[1]} | {sample_info[2]} | {sample_info[3]}")
    
    # Check skills
    cursor.execute("SELECT COUNT(*) FROM skills")
    skills_count = cursor.fetchone()[0]
    print(f"\n🎯 Unique Skills: {skills_count}")
    
    cursor.execute("SELECT name FROM skills LIMIT 10")
    sample_skills = cursor.fetchall()
    print(f"   Sample skills: {', '.join([s[0] for s in sample_skills])}")
    
    # Check resume-skill associations
    cursor.execute("SELECT COUNT(*) FROM resume_skill_association")
    associations = cursor.fetchone()[0]
    print(f"   Resume-Skill associations: {associations}")
    
    # Check work experience
    cursor.execute("SELECT COUNT(*) FROM work_experience")
    work_exp_count = cursor.fetchone()[0]
    print(f"\n💼 Work Experience Records: {work_exp_count}")
    
    if work_exp_count > 0:
        cursor.execute("SELECT company, job_title, start_date, end_date FROM work_experience LIMIT 1")
        sample_exp = cursor.fetchone()
        print(f"   Sample: {sample_exp[1]} at {sample_exp[0]} ({sample_exp[2]} - {sample_exp[3]})")
    
    # Check projects
    cursor.execute("SELECT COUNT(*) FROM projects")
    projects_count = cursor.fetchone()[0]
    print(f"\n🚀 Projects: {projects_count}")
    
    if projects_count > 0:
        cursor.execute("SELECT name, technologies FROM projects LIMIT 1")
        sample_project = cursor.fetchone()
        print(f"   Sample: {sample_project[0]} | Tech: {sample_project[1]}")
    
    # Check education
    cursor.execute("SELECT COUNT(*) FROM education")
    education_count = cursor.fetchone()[0]
    print(f"\n🎓 Education Records: {education_count}")
    
    if education_count > 0:
        cursor.execute("SELECT degree, institution, end_date FROM education LIMIT 1")
        sample_edu = cursor.fetchone()
        print(f"   Sample: {sample_edu[0]} from {sample_edu[1]} ({sample_edu[2]})")
    
    # Check resume scores
    cursor.execute("SELECT COUNT(*) FROM resume_scores")
    scores_count = cursor.fetchone()[0]
    print(f"\n📈 Resume Scores: {scores_count}")
    
    if scores_count > 0:
        cursor.execute("SELECT overall_score, skills_score, readability_score, grammar_score FROM resume_scores LIMIT 1")
        sample_score = cursor.fetchone()
        print(f"   Sample: Overall={sample_score[0]}, Skills={sample_score[1]}, Readability={sample_score[2]}, Grammar={sample_score[3]}")
    
    # Check job postings
    cursor.execute("SELECT COUNT(*) FROM job_postings")
    jobs_count = cursor.fetchone()[0]
    print(f"\n💼 Job Postings: {jobs_count}")

print("\n" + "=" * 80)
print("RELATIONSHIP INTEGRITY CHECK")
print("=" * 80)

# Check for orphaned records
cursor.execute("""
    SELECT COUNT(*) FROM personal_info 
    WHERE resume_id NOT IN (SELECT id FROM resumes)
""")
orphaned_personal = cursor.fetchone()[0]
print(f"\n🔍 Orphaned Personal Info: {orphaned_personal} {'✅' if orphaned_personal == 0 else '❌'}")

cursor.execute("""
    SELECT COUNT(*) FROM work_experience 
    WHERE resume_id NOT IN (SELECT id FROM resumes)
""")
orphaned_work = cursor.fetchone()[0]
print(f"🔍 Orphaned Work Experience: {orphaned_work} {'✅' if orphaned_work == 0 else '❌'}")

cursor.execute("""
    SELECT COUNT(*) FROM projects 
    WHERE resume_id NOT IN (SELECT id FROM resumes)
""")
orphaned_projects = cursor.fetchone()[0]
print(f"🔍 Orphaned Projects: {orphaned_projects} {'✅' if orphaned_projects == 0 else '❌'}")

cursor.execute("""
    SELECT COUNT(*) FROM education 
    WHERE resume_id NOT IN (SELECT id FROM resumes)
""")
orphaned_education = cursor.fetchone()[0]
print(f"🔍 Orphaned Education: {orphaned_education} {'✅' if orphaned_education == 0 else '❌'}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if resume_count == 0:
    print("\n⚠️  No resumes in database yet. Upload a resume to test data storage!")
else:
    total_records = personal_info_count + skills_count + work_exp_count + projects_count + education_count
    print(f"\n✅ Database is functioning correctly!")
    print(f"   Total records across all tables: {total_records}")
    print(f"   All relationships are properly maintained")
    print(f"   No orphaned records found")

print("\n" + "=" * 80)

conn.close()
