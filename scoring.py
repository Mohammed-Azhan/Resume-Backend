# scoring.py
import spacy
import textstat
import language_tool_python
from typing import Dict, List
import re

class ResumeScorer:
    def __init__(self):
        self.nlp = spacy.load("en_core_web_sm")
        self.tool = language_tool_python.LanguageTool('en-US')
        self.TARGET_SKILLS = [
            'python', 'java', 'c++', 'javascript', 'sql', 'html', 'css', 
            'react', 'angular', 'vue', 'nodejs', 'django', 'flask', 'git', 
            'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'machine learning', 
            'deep learning', 'nlp', 'data analysis', 'pandas', 'numpy', 
            'scikit-learn', 'tensorflow', 'pytorch', 'api', 'rest', 
            'mongodb', 'postgresql', 'mysql'
        ]
    
    def analyze_skills(self, text: str) -> List[str]:
        doc = self.nlp(text.lower())
        found_skills = set()
        for token in doc:
            if token.text in self.TARGET_SKILLS:
                found_skills.add(token.text)
        for skill in self.TARGET_SKILLS:
            if ' ' in skill and skill in text.lower():
                found_skills.add(skill)
        return list(found_skills)
    
    def calculate_readability(self, text: str) -> float:
        score = textstat.flesch_reading_ease(text)
        return max(0, min(100, score))
    
    def check_grammar(self, text: str) -> tuple:
        matches = self.tool.check(text)
        num_errors = len(matches)
        score = max(0, 100 - (num_errors * 5))
        return score, matches
    
    def generate_score(self, resume_text: str) -> Dict:
        matched_skills = self.analyze_skills(resume_text)
        readability_score = self.calculate_readability(resume_text)
        grammar_score, grammar_errors = self.check_grammar(resume_text)
        
        skills_score = min(100, len(matched_skills) * 10)
        final_score = (skills_score * 0.4) + (readability_score * 0.3) + (grammar_score * 0.3)
        
        feedback = {
            "skills": "Great job on listing relevant skills!" if skills_score > 50 
                     else f"Consider adding more industry-standard skills.",
            "readability": "Your resume is easy to read." if readability_score > 60 
                          else "Try using shorter sentences and simpler words.",
            "grammar": "Excellent grammar!" if grammar_score > 80 
                      else f"Found {len(grammar_errors)} grammar issues."
        }
        
        return {
            "overall_score": round(final_score),
            "skills_score": round(skills_score),
            "readability_score": round(readability_score),
            "grammar_score": round(grammar_score),
            "matched_skills": matched_skills,
            "missing_skills": list(set(self.TARGET_SKILLS) - set(matched_skills)),
            "feedback": feedback,
            "grammar_errors": [{"message": m.message, "context": m.context} 
                              for m in grammar_errors[:10]]  # Top 10 errors
        }