#!/usr/bin/env python3
"""
Simple test to check current state and verify the max-3 logic
"""

import requests
import io
import os
import sys

BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BACKEND_URL:
    print("ERROR: REACT_APP_BACKEND_URL environment variable is required but not set.", file=sys.stderr)
    print("Set REACT_APP_BACKEND_URL to your backend API base URL (e.g., https://api.example.com)", file=sys.stderr)
    sys.exit(1)
API_BASE_URL = f"{BACKEND_URL}/api"

# Test credentials - must come from environment, no repository fallbacks
CANDIDATE_EMAIL = os.environ.get("E2E_CANDIDATE_EMAIL", "candidate@test.fr")
CANDIDATE_PASSWORD = os.environ.get("E2E_CANDIDATE_PASSWORD")

def create_test_pdf():
    """Create a minimal valid PDF file"""
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
>>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<<
/Size 4
/Root 1 0 R
>>
startxref
180
%%EOF
"""
    return pdf_content

# Login
if not CANDIDATE_PASSWORD:
    print("E2E_CANDIDATE_PASSWORD not set, skipping test")
    exit(0)
    
login_data = {"email": CANDIDATE_EMAIL, "password": CANDIDATE_PASSWORD}
response = requests.post(f"{API_BASE_URL}/auth/login", json=login_data)
token = response.json()["token"]["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Check current documents
print("Checking current candidate documents...")
response = requests.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
docs = response.json()
cv_count = sum(1 for doc in docs if doc.get('category') == 'cv')
cover_letter_count = sum(1 for doc in docs if doc.get('category') == 'cover_letter')

print(f"Current state: {cv_count} CVs, {cover_letter_count} cover letters")
print(f"Total documents: {len(docs)}")

# Try to upload one more CV
print("\nTrying to upload one more CV...")
pdf_content = create_test_pdf()
files = {'file': ('test_cv_new.pdf', io.BytesIO(pdf_content), 'application/pdf')}
params = {'category': 'cv', 'title': 'Test CV New', 'description': 'Test'}

response = requests.post(
    f"{API_BASE_URL}/files/candidate-documents",
    headers=headers,
    files=files,
    params=params
)

print(f"Response status: {response.status_code}")
print(f"Response: {response.json()}")

if response.status_code == 400:
    print("\n✅ Correctly blocked upload (already have 3 CVs)")
elif response.status_code == 200:
    print(f"\n✅ Successfully uploaded (now have {cv_count + 1} CVs)")
else:
    print(f"\n❌ Unexpected response: {response.status_code}")
