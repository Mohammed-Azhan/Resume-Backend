# scoring.py
import asyncio
import hashlib
import spacy
import textstat
from google import genai
import os
from dotenv import load_dotenv
import json
from typing import Dict, List


load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) 

# ─── Singleton: load SpaCy once at import time, not per request ───────────────
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except:
            from spacy.cli import download
            download("en_core_web_sm")
            _nlp = spacy.load("en_core_web_sm")
    return _nlp

# ─── Simple in-process result cache  {text_hash -> analysis_dict} ─────────────
_analysis_cache: dict = {}


class ResumeScorer:

    def __init__(self):
        # Reuse the module-level SpaCy model — no re-loading cost per request
        self.nlp = get_nlp()

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _text_hash(self, text: str) -> str:
        """Stable hash for cache keying."""
        return hashlib.md5(text.encode()).hexdigest()

    def normalize_skill(self, skill):
        if isinstance(skill, list):
            return " ".join(skill).lower().replace(".", "").strip()
        if isinstance(skill, str):
            return skill.lower().replace(".", "").strip()
        return ""

    # ──────────────────────────────────────────────────────────────────────────
    # Gemini calls  (both use gemini-2.5-flash — faster for structured JSON)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_target_skills_from_ai(self, text: str) -> List[str]:
        prompt = f"""Resume:
{text[:3000]}

Step 1: Identify the job role of this resume.
Step 2: List the most important skills required for that role.

Return ONLY a JSON array of skill names. Example:
["inventory management", "retail", "vendor management"]"""

        try:
            res = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            content = res.text

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]

            return json.loads(content)

        except Exception as e:
            print("Gemini failed:", str(e))
            return []

    async def get_ai_missing_skills(self, text: str) -> List[str]:
        prompt = f"""Resume Text:
{text[:3000]}

Check for missing skills in this resume. If skills relevant to its field are absent, suggest them.
Return ONLY a JSON array of skill names.
"""

        try:
            res = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            content = res.text or ""   # ✅ VERY IMPORTANT
            print(content)

            # ✅ Remove markdown if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]

            parsed = json.loads(content)

            # ✅ Ensure it's always a list
            if isinstance(parsed, list):
                return parsed
            else:
                return []

        except Exception as e:
            print("Gemini error:", str(e))
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Local (non-LLM) scoring
    # ──────────────────────────────────────────────────────────────────────────
    

    def analyze_skills(self, text: str, target_skills: List[str]) -> List[str]:
        text_lower = text.lower().replace(".", "")
        found_skills = set()
        for skill in target_skills:
            norm_skill = self.normalize_skill(skill)
            if norm_skill in text_lower:
                found_skills.add(norm_skill)
        return list(found_skills)

    def calculate_readability(self, text: str) -> float:
        score = textstat.flesch_reading_ease(text)
        return max(0, min(100, score))

    def check_grammar(self, text: str) -> tuple:
        doc = self.nlp(text)

        total_sentences = 0
        valid_sentences = 0
        errors = []

        for sent in doc.sents:
            sentence = sent.text.strip()

            # ✅ Ignore short fragments (like "Skills:", "Projects:")
            if len(sentence.split()) < 4:
                continue

            total_sentences += 1

            has_verb = any(token.pos_ == "VERB" for token in sent)
            has_subject = any(token.dep_ in ("nsubj", "nsubjpass") for token in sent)

            # ✅ Allow action-verb sentences (resume style)
            starts_with_verb = sent[0].pos_ == "VERB"

            if (has_subject and has_verb) or starts_with_verb:
                valid_sentences += 1
            else:
                errors.append(sentence)

        # ✅ If only fragments → neutral score
        if total_sentences == 0:
            return 70, []

        score = (valid_sentences / total_sentences) * 100

        return round(score), errors[:5]
    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def generate_score(self, resume_text: str) -> Dict:

        # ── Cache check ──────────────────────────────────────────────────────
        cache_key = self._text_hash(resume_text)
        if cache_key in _analysis_cache:
            return _analysis_cache[cache_key]

        # ── Run both Gemini calls in parallel ────────────────────────────────
        target_skills, ai_missing_skills = await asyncio.gather(
            self.get_target_skills_from_ai(resume_text),
            self.get_ai_missing_skills(resume_text),
        )
        if not target_skills and not ai_missing_skills:
             return {
        "overall_score": 0,
        "skills_score": 0,
        "readability_score": 0,
        "grammar_score": 0,
        "matched_skills": [],
        "target_skills": [],
        "missing_skills": [],
        "feedback": {
            "skills": "AI failed. Try again later.",
            "readability": "",
            "grammar": ""
        },
        "grammar_errors": []
    }
        # ✅ Clean target skills (flatten + remove bad data)
        cleaned_target = []
        for s in target_skills:
            if isinstance(s, list):
                cleaned_target.extend(s)
            elif isinstance(s, str):
                cleaned_target.append(s)

        target_skills = cleaned_target
        cleaned_missing = []
        for s in ai_missing_skills:
            if isinstance(s, list):
                cleaned_missing.extend(s)
            elif isinstance(s, str):
                cleaned_missing.append(s)

        ai_missing_skills = cleaned_missing

        # ── Local scoring (fast, no network) ────────────────────────────────
        matched_skills = self.analyze_skills(resume_text, target_skills)
        readability_score = self.calculate_readability(resume_text)
        grammar_score, grammar_errors = self.check_grammar(resume_text)

        normalized_target  = [self.normalize_skill(s) for s in target_skills]
        normalized_matched = [self.normalize_skill(s) for s in matched_skills]
        
        # Merge AI's suggested missing skills with mathematically missing target skills
        mathematically_missing = list(set(normalized_target) - set(normalized_matched))
        missing_skills = list(set(ai_missing_skills + mathematically_missing))


        # 🚨 HANDLE NO SKILLS CASE FIRST
        if len(matched_skills) == 0:
            skills_score = 0

            # ❌ DO NOT RESET THESE
            final_score = (
                (skills_score * 0.4)
                + (readability_score * 0.3)
                + (grammar_score * 0.3)
            )

            feedback = {
                "skills": "No skills detected. Try improving your resume.",
                "readability": "",
                "grammar": ""
    }

        else:
            skills_score = min(100, len(matched_skills) * 10)

            final_score = (
                (skills_score * 0.4)
                + (readability_score * 0.3)
                + (grammar_score * 0.3)
            )

            feedback = {
                "skills": (
                    "Great job on listing relevant skills!"
            if skills_score > 50
            else "Consider adding more role-specific skills."
        ),
        "readability": (
            "Your resume is easy to read."
            if readability_score > 60
            else "Try using shorter sentences."
        ),
        "grammar": (
            "Excellent grammar!"
            if grammar_score > 80
            else f"Found {len(grammar_errors)} grammar issues."
        ),
    }
        result = {
            "overall_score":    round(final_score),
            "skills_score":     round(skills_score),
            "readability_score": round(readability_score),
            "grammar_score":    round(grammar_score),
            "matched_skills":   matched_skills,
            "target_skills":    target_skills,
            "missing_skills":   missing_skills,
            "feedback":         feedback,
            "grammar_errors": grammar_errors,
        }

        # ── Store in cache ───────────────────────────────────────────────────
        _analysis_cache[cache_key] = result
        return result
