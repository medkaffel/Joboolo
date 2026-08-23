#!/usr/bin/env python3
"""
FINAL FILE UPLOAD BUG FIX VERIFICATION
Tests all scenarios from the review request
"""

import requests
import io
import os
from datetime import datetime

BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://job-platform-next.preview.emergentagent.com')
API_BASE_URL = f"{BACKEND_URL}/api"

CANDIDATE_EMAIL = "candidate@test.fr"
CANDIDATE_PASSWORD = "password123"

class FinalFileUploadTest:
    def __init__(self):
        self.session = requests.Session()
        self.token = None
        self.results = []
        
    def log(self, test_name, success, details=""):
        """Log test results"""
        status = "✅" if success else "❌"
        print(f"{status} {test_name}")
        if details:
            print(f"   {details}")
        self.results.append({"test": test_name, "success": success, "details": details})
        
    def create_test_pdf(self):
        """Create a minimal valid PDF"""
        return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
180
%%EOF
"""
    
    def create_test_image(self):
        """Create a minimal valid PNG"""
        return (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf'
            b'\xc0\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
    
    def login(self):
        """Login as candidate"""
        try:
            response = self.session.post(f"{API_BASE_URL}/auth/login", 
                                        json={"email": CANDIDATE_EMAIL, "password": CANDIDATE_PASSWORD})
            if response.status_code == 200:
                self.token = response.json()["token"]["access_token"]
                self.log("Login", True, f"Logged in as {CANDIDATE_EMAIL}")
                return True
            else:
                self.log("Login", False, f"HTTP {response.status_code}")
                return False
        except Exception as e:
            self.log("Login", False, str(e))
            return False
    
    def test_1_upload_cv(self):
        """Test 1: POST /api/files/upload-cv (job application flow)"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('application_cv.pdf', io.BytesIO(self.create_test_pdf()), 'application/pdf')}
        
        response = self.session.post(f"{API_BASE_URL}/files/upload-cv", headers=headers, files=files)
        
        if response.status_code == 200:
            data = response.json()
            if all(k in data for k in ['storage_path', 'original_filename', 'content_type']):
                self.log("POST /api/files/upload-cv", True, 
                        f"File: {data['original_filename']}, Path: {data['storage_path']}")
                return True
            else:
                self.log("POST /api/files/upload-cv", False, f"Missing fields in response")
                return False
        else:
            self.log("POST /api/files/upload-cv", False, 
                    f"HTTP {response.status_code}: {response.json().get('detail', response.text)}")
            return False
    
    def test_2_candidate_documents_cv(self):
        """Test 2: POST /api/files/candidate-documents with category=cv"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('mon_cv_profile.pdf', io.BytesIO(self.create_test_pdf()), 'application/pdf')}
        params = {'category': 'cv', 'title': 'CV Profil Test', 'description': 'CV pour mon profil'}
        
        response = self.session.post(f"{API_BASE_URL}/files/candidate-documents", 
                                    headers=headers, files=files, params=params)
        
        # Check current count first
        list_resp = self.session.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
        current_cvs = sum(1 for doc in list_resp.json() if doc.get('category') == 'cv')
        
        if current_cvs >= 3:
            # Should fail with 400
            if response.status_code == 400 and '3' in response.json().get('detail', ''):
                self.log("POST /api/files/candidate-documents (CV, max-3 check)", True, 
                        f"Correctly blocked (already have {current_cvs} CVs)")
                return True
            elif response.status_code == 200:
                self.log("POST /api/files/candidate-documents (CV, max-3 check)", False, 
                        f"Should have blocked upload (already have {current_cvs} CVs)")
                return False
        else:
            # Should succeed
            if response.status_code == 200:
                data = response.json()
                if data.get('category') == 'cv':
                    self.log("POST /api/files/candidate-documents (CV)", True, 
                            f"ID: {data['id']}, Title: {data['title']}")
                    return True
                else:
                    self.log("POST /api/files/candidate-documents (CV)", False, 
                            f"Wrong category: {data.get('category')}")
                    return False
            else:
                self.log("POST /api/files/candidate-documents (CV)", False, 
                        f"HTTP {response.status_code}: {response.json().get('detail', '')}")
                return False
    
    def test_3_candidate_documents_cover_letter(self):
        """Test 3: POST /api/files/candidate-documents with category=cover_letter"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('lettre.pdf', io.BytesIO(self.create_test_pdf()), 'application/pdf')}
        params = {'category': 'cover_letter', 'title': 'Lettre Test', 'description': 'Ma lettre de motivation'}
        
        response = self.session.post(f"{API_BASE_URL}/files/candidate-documents", 
                                    headers=headers, files=files, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('category') == 'cover_letter':
                self.log("POST /api/files/candidate-documents (cover_letter)", True, 
                        f"ID: {data['id']}, Title: {data['title']}")
                self.cover_letter_id = data['id']
                return True
            else:
                self.log("POST /api/files/candidate-documents (cover_letter)", False, 
                        f"Wrong category: {data.get('category')}")
                return False
        else:
            self.log("POST /api/files/candidate-documents (cover_letter)", False, 
                    f"HTTP {response.status_code}: {response.json().get('detail', '')}")
            return False
    
    def test_4_invalid_category(self):
        """Test 4: Invalid category returns 400"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('test.pdf', io.BytesIO(self.create_test_pdf()), 'application/pdf')}
        params = {'category': 'invalid', 'title': 'Test', 'description': 'Test'}
        
        response = self.session.post(f"{API_BASE_URL}/files/candidate-documents", 
                                    headers=headers, files=files, params=params)
        
        if response.status_code == 400:
            detail = response.json().get('detail', '')
            if 'catégorie' in detail.lower() or 'category' in detail.lower():
                self.log("Invalid category rejection", True, f"Correctly rejected: {detail}")
                return True
        
        self.log("Invalid category rejection", False, f"Expected 400, got {response.status_code}")
        return False
    
    def test_5_invalid_extension(self):
        """Test 5: Invalid extension returns 400"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('test.txt', io.BytesIO(b'text file'), 'text/plain')}
        params = {'category': 'cv', 'title': 'Test', 'description': 'Test'}
        
        response = self.session.post(f"{API_BASE_URL}/files/candidate-documents", 
                                    headers=headers, files=files, params=params)
        
        if response.status_code == 400:
            detail = response.json().get('detail', '')
            if 'format' in detail.lower() or 'extension' in detail.lower():
                self.log("Invalid extension rejection", True, f"Correctly rejected: {detail}")
                return True
        
        self.log("Invalid extension rejection", False, f"Expected 400, got {response.status_code}")
        return False
    
    def test_6_upload_profile_photo(self):
        """Test 6: POST /api/files/upload-profile-photo"""
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {'file': ('profile.png', io.BytesIO(self.create_test_image()), 'image/png')}
        
        response = self.session.post(f"{API_BASE_URL}/files/upload-profile-photo", 
                                    headers=headers, files=files)
        
        if response.status_code == 200:
            data = response.json()
            if 'profile_photo_url' in data:
                self.log("POST /api/files/upload-profile-photo", True, 
                        f"Photo URL: {data['profile_photo_url']}")
                self.photo_url = data['profile_photo_url']
                return True
            else:
                self.log("POST /api/files/upload-profile-photo", False, 
                        "Missing profile_photo_url in response")
                return False
        else:
            self.log("POST /api/files/upload-profile-photo", False, 
                    f"HTTP {response.status_code}: {response.json().get('detail', '')}")
            return False
    
    def test_7_profile_photo_in_me(self):
        """Test 7: GET /api/auth/me returns profile_photo_url"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.session.get(f"{API_BASE_URL}/auth/me", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if 'profile_photo_url' in data and data['profile_photo_url']:
                self.log("GET /api/auth/me (profile_photo_url)", True, 
                        f"Photo URL present: {data['profile_photo_url']}")
                return True
            else:
                self.log("GET /api/auth/me (profile_photo_url)", False, 
                        "profile_photo_url not found or empty")
                return False
        else:
            self.log("GET /api/auth/me (profile_photo_url)", False, 
                    f"HTTP {response.status_code}")
            return False
    
    def test_8_get_candidate_documents(self):
        """Test 8: GET /api/files/candidate-documents"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.session.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                cv_count = sum(1 for doc in data if doc.get('category') == 'cv')
                cl_count = sum(1 for doc in data if doc.get('category') == 'cover_letter')
                self.log("GET /api/files/candidate-documents", True, 
                        f"Retrieved {len(data)} docs: {cv_count} CVs, {cl_count} cover letters")
                self.doc_list = data
                return True
            else:
                self.log("GET /api/files/candidate-documents", False, 
                        "Response is not a list")
                return False
        else:
            self.log("GET /api/files/candidate-documents", False, 
                    f"HTTP {response.status_code}")
            return False
    
    def test_9_update_candidate_document(self):
        """Test 9: PUT /api/files/candidate-documents/{id}"""
        if not hasattr(self, 'cover_letter_id'):
            # Get any document to update
            headers = {"Authorization": f"Bearer {self.token}"}
            response = self.session.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
            docs = response.json()
            if not docs:
                self.log("PUT /api/files/candidate-documents/{id}", False, "No documents to update")
                return False
            doc_id = docs[0]['id']
        else:
            doc_id = self.cover_letter_id
        
        headers = {"Authorization": f"Bearer {self.token}"}
        update_data = {'title': 'Titre Mis à Jour', 'description': 'Description mise à jour'}
        
        response = self.session.put(f"{API_BASE_URL}/files/candidate-documents/{doc_id}", 
                                   headers=headers, json=update_data)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('title') == 'Titre Mis à Jour':
                self.log("PUT /api/files/candidate-documents/{id}", True, 
                        f"Updated doc {doc_id}")
                return True
            else:
                self.log("PUT /api/files/candidate-documents/{id}", False, 
                        "Title not updated correctly")
                return False
        else:
            self.log("PUT /api/files/candidate-documents/{id}", False, 
                    f"HTTP {response.status_code}")
            return False
    
    def test_10_delete_candidate_document(self):
        """Test 10: DELETE /api/files/candidate-documents/{id}"""
        if not hasattr(self, 'cover_letter_id'):
            # Get any document to delete
            headers = {"Authorization": f"Bearer {self.token}"}
            response = self.session.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
            docs = response.json()
            if not docs:
                self.log("DELETE /api/files/candidate-documents/{id}", False, "No documents to delete")
                return False
            doc_id = docs[-1]['id']  # Delete the last one
        else:
            doc_id = self.cover_letter_id
        
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.session.delete(f"{API_BASE_URL}/files/candidate-documents/{doc_id}", 
                                      headers=headers)
        
        if response.status_code == 200:
            # Verify it's gone
            list_resp = self.session.get(f"{API_BASE_URL}/files/candidate-documents", headers=headers)
            docs = list_resp.json()
            if not any(doc['id'] == doc_id for doc in docs):
                self.log("DELETE /api/files/candidate-documents/{id}", True, 
                        f"Deleted doc {doc_id} (soft delete)")
                return True
            else:
                self.log("DELETE /api/files/candidate-documents/{id}", False, 
                        "Document still in list after deletion")
                return False
        else:
            self.log("DELETE /api/files/candidate-documents/{id}", False, 
                    f"HTTP {response.status_code}")
            return False
    
    def run_all_tests(self):
        """Run all tests"""
        print("=" * 80)
        print("FILE UPLOAD BUG FIX VERIFICATION - FINAL TEST")
        print("=" * 80)
        print(f"API: {API_BASE_URL}")
        print(f"User: {CANDIDATE_EMAIL}")
        print()
        
        if not self.login():
            print("\n❌ Login failed. Cannot proceed.")
            return
        
        print("\n" + "=" * 80)
        print("RUNNING TESTS")
        print("=" * 80)
        
        self.test_1_upload_cv()
        self.test_2_candidate_documents_cv()
        self.test_3_candidate_documents_cover_letter()
        self.test_4_invalid_category()
        self.test_5_invalid_extension()
        self.test_6_upload_profile_photo()
        self.test_7_profile_photo_in_me()
        self.test_8_get_candidate_documents()
        self.test_9_update_candidate_document()
        self.test_10_delete_candidate_document()
        
        self.print_summary()
    
    def print_summary(self):
        """Print summary"""
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        passed = sum(1 for r in self.results if r["success"])
        failed = len(self.results) - passed
        
        print(f"Total: {len(self.results)} tests")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/len(self.results)*100):.1f}%")
        
        if failed > 0:
            print("\n❌ FAILED TESTS:")
            for r in self.results:
                if not r["success"]:
                    print(f"  • {r['test']}: {r['details']}")
        
        print("\n" + "=" * 80)
        if failed == 0:
            print("✅ BUG IS FIXED - ALL FILE UPLOAD ENDPOINTS WORKING")
            print("No 5xx errors observed. All endpoints return correct responses.")
        else:
            print("⚠️  SOME TESTS FAILED - REVIEW REQUIRED")
        print("=" * 80)

if __name__ == "__main__":
    tester = FinalFileUploadTest()
    tester.run_all_tests()
