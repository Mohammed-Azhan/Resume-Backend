# ResumeHub -  AI Resume Intelligence Platform

A comprehensive AI-powered resume parsing and analysis platform built with FastAPI and Google Gemini. This application provides intelligent resume parsing, detailed scoring, AI-powered suggestions, and analytics capabilities through both a REST API and an interactive web interface.
<img width="1481" height="939" alt="Screenshot 2026-01-02 130550" src="https://github.com/user-attachments/assets/75cad960-188c-4efb-9cdc-5e196d770a97" />
<img width="1545" height="902" alt="Screenshot 2026-01-02 130837" src="https://github.com/user-attachments/assets/bdc0866e-24ee-4882-b7c5-6a25388e5ba7" />
<img width="1284" height="777" alt="Screenshot 2026-01-02 130945" src="https://github.com/user-attachments/assets/c898ab0e-a692-4c92-94b4-1a45eb329069" />
<img width="1348" height="949" alt="Screenshot 2026-01-02 131102" src="https://github.com/user-attachments/assets/330c1d36-5b20-4edb-850e-c4c50ab4637d" />




## Overview

ResumeHub automates the entire resume processing workflow by combining advanced AI capabilities with a user-friendly interface. The platform extracts structured data from resumes, analyzes their quality, provides actionable improvement suggestions, and offers insights through comprehensive analytics.

**Key Capabilities:**
- Intelligent parsing of PDF and DOCX resume files
- Multi-dimensional resume scoring and analysis
- AI-powered improvement suggestions using Google Gemini
- Job matching and skill gap analysis
- Real-time analytics dashboard
- Modern, responsive web interface

## Architecture

The application follows a modern full-stack architecture with clear separation of concerns:

```mermaid
graph TD;
    A[User] -- Uploads Resume --> B(Web Interface);
    B -- HTTP Request --> C{FastAPI Backend};
    C -- File Processing --> D[Document Parser];
    D -- PDF --> E[PyMuPDF];
    D -- DOCX --> F[python-docx];
    E -- Raw Text --> G(Gemini AI);
    F -- Raw Text --> G;
    G -- Structured Data --> H(Pydantic Validation);
    H -- Validated Data --> I(SQLAlchemy ORM);
    I -- Persist --> J[(SQLite Database)];
    I -- Retrieve --> K(Resume Scorer);
    K -- NLP Analysis --> L[spaCy + LanguageTool];
    L -- Scores --> I;
    G -- AI Suggestions --> M(Suggestions Engine);
    M -- Recommendations --> B;
    I -- Analytics --> N(Dashboard);
    N -- Insights --> B;
```

## Features

### Core Functionality

**Resume Parsing**
- Multi-format support for PDF and DOCX files
- Extraction of personal information, skills, work experience, education, and projects
- AI-powered text understanding using Google Gemini 2.5 Flash
- Automatic data validation and structuring

**Resume Analysis**
- Overall quality scoring based on multiple factors
- Skills assessment against industry standards
- Readability analysis using Flesch Reading Ease
- Grammar and language quality checking
- Identification of matched and missing skills

**AI-Powered Suggestions**
- Personalized improvement recommendations
- Content enhancement suggestions
- Skills gap identification
- Formatting and structure improvements
- ATS optimization tips

**Job Matching**
- Create and manage job postings
- Automatic skill-based matching
- Compatibility score calculation
- Missing skills identification

**Analytics Dashboard**
- Platform-wide statistics
- Top skills analysis
- Average resume scores
- Trend visualization

### Web Interface

The ResumeHub frontend provides an intuitive, modern interface with:
- Drag-and-drop resume upload
- Real-time processing progress
- Resume library management
- Interactive analysis visualization
- AI suggestions display
- Comprehensive analytics dashboard

## Technology Stack

### Backend
- **Framework:** FastAPI (modern, high-performance Python web framework)
- **AI/ML:** Google Gemini API (advanced language understanding)
- **NLP:** spaCy (natural language processing)
- **Grammar:** LanguageTool Python (grammar and style checking)
- **Readability:** textstat (readability metrics)
- **Database:** SQLAlchemy ORM with SQLite
- **Validation:** Pydantic (data validation and serialization)
- **Document Processing:** PyMuPDF (PDF), python-docx (DOCX)
- **Server:** Uvicorn (ASGI server)

### Frontend
- **Framework:** React 18 (component-based UI)
- **Styling:** Tailwind CSS (utility-first CSS framework)
- **Build:** Babel Standalone (in-browser JSX transformation)
- **Icons:** Custom SVG components

### Database Schema
- Resume (main entity)
- PersonalInfo (one-to-one)
- Skills (many-to-many)
- WorkExperience (one-to-many)
- Projects (one-to-many)
- Education (one-to-many)
- ResumeScore (one-to-one)
- JobPosting (independent entity)
- ResumeJobMatch (many-to-many relationship)

## Installation and Setup

### Prerequisites

- Python 3.9 or higher
- Git
- Google Gemini API Key (obtain from [Google AI Studio](https://makersuite.google.com/app/apikey))

### Step-by-Step Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/mohitsharmas97/AI-Resume-Parser.git
   cd AI-Resume-Parser
   ```

2. **Create and activate virtual environment**
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Download spaCy language model**
   ```bash
   python -m spacy download en_core_web_sm
   ```

5. **Configure environment variables**
   
   Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   ```

6. **Initialize the database**
   
   The database will be created automatically on first run. The application uses SQLite with the file `resume_parser.db`.

7. **Start the application**
   ```bash
   uvicorn main:app --reload
   ```

   The API will be available at `http://127.0.0.1:8000`

8. **Access the application**
   - API Documentation: `http://127.0.0.1:8000/docs`
   - Web Interface: Open `resumehub-frontend/public/index.html` in your browser

## API Endpoints

### Resume Management

**Upload and Parse Resume**
```http
POST /parse-resume/
Content-Type: multipart/form-data

Response: Structured resume data (JSON)
```

**Get Resume by ID**
```http
GET /resumes/{resume_id}

Response: Complete resume data
```

**Search Resume by Email**
```http
GET /resumes/search/?email={email}

Response: Resume data for specified email
```

**List All Resumes**
```http
GET /resumes/

Response: Array of all resumes
```

**Delete Resume**
```http
DELETE /resumes/{resume_id}

Response: Confirmation message
```

### Analysis and Suggestions

**Analyze Resume**
```http
POST /resumes/{resume_id}/analyze

Response: Detailed scoring and analysis
```

**Get AI Suggestions**
```http
GET /resumes/{resume_id}/suggestions

Response: Array of improvement suggestions
```

**Analyze by Email**
```http
POST /analyze-resume/{email}

Response: Complete analysis with scores
```

**Get Suggestions by Email**
```http
GET /get-suggestions/{email}

Response: Categorized suggestions
```

### Job Matching

**Create Job Posting**
```http
POST /jobs/
Content-Type: application/json

Body: {
  "title": "Software Engineer",
  "company": "Tech Corp",
  "description": "...",
  "required_skills": ["Python", "FastAPI", "React"]
}
```

**Match Resume to Job**
```http
POST /match/resume/{resume_id}/job/{job_id}

Response: Match score and skill analysis
```

### Analytics

**Get Dashboard Analytics**
```http
GET /analytics/dashboard

Response: Platform statistics and insights
```

## Project Structure

```
AI-Resume-Parser/
├── main.py                          # FastAPI application and endpoints
├── models.py                        # SQLAlchemy database models
├── schemas.py                       # Pydantic validation schemas
├── crud.py                          # Database CRUD operations
├── database.py                      # Database configuration
├── scoring.py                       # Resume scoring engine
├── requirements.txt                 # Python dependencies
├── .env                            # Environment variables (API keys)
├── .gitignore                      # Git ignore rules
├── resume_parser.db                # SQLite database (auto-generated)
├── resumehub-frontend/             # Frontend application
│   └── public/
│       ├── index.html              # Main web interface
│       ├── analysis.html           # Analysis page
│       └── suggestions.html        # Suggestions page
└── README.md                       # This file
```

## Configuration

### Environment Variables

Create a `.env` file with the following:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### CORS Configuration

The API is configured to accept requests from all origins, including local file protocol. This is set in `main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Database Configuration

The application uses SQLite by default. To use PostgreSQL or MySQL, modify `database.py`:

```python
# For PostgreSQL
SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost/dbname"

# For MySQL
SQLALCHEMY_DATABASE_URL = "mysql://user:password@localhost/dbname"
```

## Usage Examples

### Uploading a Resume via API

```python
import requests

url = "http://localhost:8000/parse-resume/"
files = {"file": open("resume.pdf", "rb")}
response = requests.post(url, files=files)
print(response.json())
```

### Analyzing a Resume

```python
import requests

resume_id = 1
url = f"http://localhost:8000/resumes/{resume_id}/analyze"
response = requests.post(url)
analysis = response.json()

print(f"Overall Score: {analysis['overall_score']}")
print(f"Skills Score: {analysis['skills_score']}")
print(f"Matched Skills: {analysis['matched_skills']}")
```

### Getting AI Suggestions

```python
import requests

resume_id = 1
url = f"http://localhost:8000/resumes/{resume_id}/suggestions"
response = requests.get(url)
suggestions = response.json()

for suggestion in suggestions:
    print(f"{suggestion['category']}: {suggestion['suggestion']}")
```

## Resume Scoring Methodology

The scoring system evaluates resumes across multiple dimensions:

**Skills Score (40% weight)**
- Matches against 30+ industry-standard skills
- Technologies: Python, Java, JavaScript, React, Docker, AWS, etc.
- Frameworks and tools assessment
- Score: 10 points per matched skill (max 100)

**Readability Score (30% weight)**
- Flesch Reading Ease calculation
- Sentence structure analysis
- Clarity and conciseness evaluation
- Target: 60-80 for professional documents

**Grammar Score (30% weight)**
- Grammar and spelling checks
- Punctuation accuracy
- Style consistency
- Deduction: 5 points per error

**Overall Score**
- Weighted average of all components
- Range: 0-100
- Provides actionable feedback for each category

## Development

### Running in Development Mode

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black .
isort .
```

## Deployment

### Production Deployment

1. **Set production environment variables**
2. **Use a production-grade database** (PostgreSQL recommended)
3. **Configure proper CORS settings**
4. **Use a production ASGI server** (Gunicorn with Uvicorn workers)
5. **Set up SSL/TLS certificates**
6. **Implement rate limiting and authentication**

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Contributing

Contributions are welcome and appreciated. To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

### Contribution Guidelines

- Follow PEP 8 style guidelines for Python code
- Write clear, descriptive commit messages
- Add tests for new features
- Update documentation as needed
- Ensure all tests pass before submitting PR

## Troubleshooting

### Common Issues

**Issue: GEMINI_API_KEY not found**
- Solution: Ensure `.env` file exists with valid API key

**Issue: spaCy model not found**
- Solution: Run `python -m spacy download en_core_web_sm`

**Issue: CORS errors in frontend**
- Solution: Ensure backend is running and CORS is properly configured

**Issue: Database locked errors**
- Solution: Close other connections or switch to PostgreSQL for production

**Issue: File upload fails**
- Solution: Check file format (PDF/DOCX only) and size limits

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Acknowledgments

- Google Gemini API for advanced AI capabilities
- FastAPI framework for excellent developer experience
- spaCy for robust NLP processing
- The open-source community for various tools and libraries

## Contact and Support

For questions, issues, or suggestions:
- Open an issue on GitHub
- Contact the maintainer: [Your Contact Information]

## Roadmap

Future enhancements planned:
- Resume template generation
- Multi-language support
- Advanced job matching algorithms
- Resume comparison features
- Export to various formats
- Integration with ATS systems
- Machine learning-based scoring improvements
- Real-time collaboration features

---

Built with FastAPI, Google Gemini AI, React, and Tailwind CSS
