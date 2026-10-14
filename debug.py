import json
from app import app

client = app.test_client()

payload = {
    "api_key": "dummy",
    "jd": "React Java Spring Boot",
    "company": "Test",
    "role": "Full Stack",
    "role_type": "Full Stack",
    "selected_projects": ["paystride"],
    "stage1": {
        "keywords": ["React", "Java"],
        "required": ["React"]
    },
    "jd_categories": ["frontend", "backend"]
}

response = client.post('/api/generate-resume', json=payload)
print(response.get_data(as_text=True))
