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
            'mongodb', 'postgresql', 'mysql', 'fastapi', 'socket.io', 
            'webrtc', 'efficientnet', 'gemini', 'llm', 'openweathermap'
        ]
    
    def analyze_skills(self, text: str) -> List[str]:
        """Extract skills from resume text"""
        if not text or len(text.strip()) == 0:
            return []
        
        doc = self.nlp(text.lower())
        found_skills = set()
        
        # Single word skills
        for token in doc:
            if token.text in self.TARGET_SKILLS:
                found_skills.add(token.text)
        
        # Multi-word skills
        for skill in self.TARGET_SKILLS:
            if ' ' in skill and skill in text.lower():
                found_skills.add(skill)
        
        return list(found_skills)
    
    def calculate_readability(self, text: str) -> float:
        """Calculate readability score with proper error handling"""
        if not text or len(text.strip()) < 100:
            print(f"WARNING: Text too short for readability analysis ({len(text)} chars)")
            # Return a neutral score for very short text
            return 50.0
        
        try:
            # Flesch Reading Ease returns 0-100 (higher = easier to read)
            score = textstat.flesch_reading_ease(text)
            
            # Handle edge cases
            if score < 0:
                score = 0
            elif score > 100:
                score = 100
            
            print(f"DEBUG: Readability score calculated: {score}")
            return float(score)
            
        except Exception as e:
            print(f"ERROR calculating readability: {e}")
            return 50.0  # Return neutral score on error
    
    def check_grammar(self, text: str) -> tuple:
        """Check grammar and return score + errors"""
        if not text or len(text.strip()) < 10:
            return 100.0, []
        
        try:
            # Limit text length to avoid timeouts
            if len(text) > 5000:
                text = text[:5000]
            
            matches = self.tool.check(text)
            num_errors = len(matches)
            
            # Calculate score (max 20 errors before hitting 0)
            score = max(0, 100 - (num_errors * 5))
            
            print(f"DEBUG: Grammar check found {num_errors} errors, score: {score}")
            return float(score), matches
            
        except Exception as e:
            print(f"ERROR in grammar check: {e}")
            return 75.0, []  # Return decent score on error
    
    def generate_score(self, resume_text: str) -> Dict:
        """Generate comprehensive resume score"""
        
        # Validate input
        if not resume_text or len(resume_text.strip()) < 50:
            print("WARNING: Resume text is too short or empty")
            return {
                "overall_score": 0,
                "skills_score": 0,
                "readability_score": 0,
                "grammar_score": 0,
                "matched_skills": [],
                "missing_skills": self.TARGET_SKILLS,
                "feedback": {
                    "skills": "No content to analyze. Please ensure resume has sufficient content.",
                    "readability": "Insufficient text for readability analysis.",
                    "grammar": "Insufficient text for grammar analysis."
                },
                "grammar_errors": []
            }
        
        print(f"DEBUG: Generating score for {len(resume_text)} characters of text")
        
        # Analyze components
        matched_skills = self.analyze_skills(resume_text)
        readability_score = self.calculate_readability(resume_text)
        grammar_score, grammar_errors = self.check_grammar(resume_text)
        
        # Calculate skills score (cap at 100)
        skills_score = min(100, len(matched_skills) * 10)
        
        # Calculate weighted final score
        final_score = (
            (skills_score * 0.4) + 
            (readability_score * 0.3) + 
            (grammar_score * 0.3)
        )
        
        # Generate feedback
        feedback = {
            "skills": (
                "Great job on listing relevant skills!" 
                if skills_score > 50 
                else f"Consider adding more industry-standard skills. Found {len(matched_skills)} skills."
            ),
            "readability": (
                "Your resume is easy to read." 
                if readability_score > 60 
                else "Try using shorter sentences and simpler words."
            ),
            "grammar": (
                "Excellent grammar!" 
                if grammar_score > 80 
                else f"Found {len(grammar_errors)} grammar issues."
            )
        }
        
        result = {
            "overall_score": round(final_score),
            "skills_score": round(skills_score),
            "readability_score": round(readability_score),
            "grammar_score": round(grammar_score),
            "matched_skills": matched_skills,
            "missing_skills": list(set(self.TARGET_SKILLS) - set(matched_skills)),
            "feedback": feedback,
            "grammar_errors": [
                {"message": m.message, "context": m.context} 
                for m in grammar_errors[:10]
            ]
        }
        
        print(f"DEBUG: Final scores - Overall: {result['overall_score']}, Skills: {result['skills_score']}, Readability: {result['readability_score']}, Grammar: {result['grammar_score']}")
        
        return result