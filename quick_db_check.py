import sqlite3

conn = sqlite3.connect('resume_parser.db')
cursor = conn.cursor()

# Get table count
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]

# Get counts
cursor.execute("SELECT COUNT(*) FROM resumes")
resumes = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM personal_info")
personal = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM skills")
skills = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM work_experience")
work_exp = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM projects")
projects = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM education")
education = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM resume_scores")
scores = cursor.fetchone()[0]

print(f"Tables: {len(tables)}")
print(f"Resumes: {resumes}")
print(f"Personal Info: {personal}")
print(f"Skills: {skills}")
print(f"Work Experience: {work_exp}")
print(f"Projects: {projects}")
print(f"Education: {education}")
print(f"Resume Scores: {scores}")

if resumes > 0:
    cursor.execute("SELECT name, email FROM personal_info LIMIT 1")
    sample = cursor.fetchone()
    print(f"Sample: {sample[0]} - {sample[1]}")
    print("DATABASE OK")
else:
    print("NO DATA YET - Upload a resume to test")

conn.close()
