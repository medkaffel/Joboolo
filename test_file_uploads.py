#!/usr/bin/env python3
"""
File Upload Endpoints Testing - Bug Fix Verification
Tests all file upload endpoints after EMERGENT_LLM_KEY fix
"""

import requests
import io
import os
from datetime import datetime

# Backend URL from environment
BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://job-platform-next.preview.emergentagent.com')
API_BASE_URL = f"{BACKEND_URL}/api"

# Test credentials - must come from environment, no repository fallbacks
CANDIDATE_EMAIL = os.environ.get("E2E_CANDIDATE_EMAIL", "candidate@test.fr")
CANDIDATE_PASSWORD = os.environ.get("E2E_CANDIDATE_PASSWORD")

class FileUploadTester:
    def __init__(self):
        self.session = requests.Session()
        self.candidate_token = None
        self.test_results = []
        self.uploaded_doc_ids = []
        
    def log_test(self, test_name, success, details="", response_data=None):
        """Log test results"""
        result = {
            "test": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        if response_data:
            result["response_data"] = response_data
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")
        if details:
            print(f"    Details: {details}")
        if not success and response_data:
            print(f"    Response: {response_data}")
        print()
        
    def create_test_pdf(self):
        """Create a minimal valid PDF file for testing"""
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
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test CV) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000317 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
410
%%EOF
"""
        return pdf_content
    
    def create_test_image(self):
        """Create a minimal valid PNG image for testing"""
        # 1x1 red pixel PNG
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf'
            b'\xc0\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return png_content
    
    def login_candidate(self):
        """Login as candidate to get JWT token"""
        if not CANDIDATE_PASSWORD:
            self.log_test("Login Candidate", False, "E2E_CANDIDATE_PASSWORD not set")
            return False
        try:
            login_data = {
                "email": CANDIDATE_EMAIL,
                "password": CANDIDATE_PASSWORD
            }
            
            response = self.session.post(f"{API_BASE_URL}/auth/login", json=login_data)
            
            if response.status_code == 200:
                data = response.json()
                self.candidate_token = data["token"]["access_token"]
                self.log_test("Login Candidate", True, 
                            f"Logged in: {data['user']['email']}")
                return True
            else:
                self.log_test("Login Candidate", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Login Candidate", False, f"Error: {str(e)}")
            return False
    
    def test_upload_cv(self):
        """Test POST /api/files/upload-cv (job application flow)"""
        if not self.candidate_token:
            self.log_test("Upload CV", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            pdf_content = self.create_test_pdf()
            
            files = {
                'file': ('test_cv.pdf', io.BytesIO(pdf_content), 'application/pdf')
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/upload-cv",
                headers=headers,
                files=files
            )
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['storage_path', 'original_filename', 'content_type']
                missing_fields = [f for f in required_fields if f not in data]
                
                if missing_fields:
                    self.log_test("Upload CV", False, 
                                f"Missing fields: {missing_fields}", data)
                    return False
                
                self.log_test("Upload CV", True, 
                            f"File: {data['original_filename']}, Path: {data['storage_path']}")
                return True
            else:
                self.log_test("Upload CV", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Upload CV", False, f"Error: {str(e)}")
            return False
    
    def test_upload_candidate_document_cv(self):
        """Test POST /api/files/candidate-documents with category=cv"""
        if not self.candidate_token:
            self.log_test("Upload Candidate Document (CV)", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            pdf_content = self.create_test_pdf()
            
            files = {
                'file': ('mon_cv.pdf', io.BytesIO(pdf_content), 'application/pdf')
            }
            
            params = {
                'category': 'cv',
                'title': 'Mon CV Principal',
                'description': 'CV avec 5 ans d\'expérience en développement'
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/candidate-documents",
                headers=headers,
                files=files,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['id', 'category', 'title', 'description', 'storage_path', 'original_filename']
                missing_fields = [f for f in required_fields if f not in data]
                
                if missing_fields:
                    self.log_test("Upload Candidate Document (CV)", False, 
                                f"Missing fields: {missing_fields}", data)
                    return False
                
                if data['category'] != 'cv':
                    self.log_test("Upload Candidate Document (CV)", False, 
                                f"Wrong category: {data['category']}", data)
                    return False
                
                self.uploaded_doc_ids.append(data['id'])
                self.log_test("Upload Candidate Document (CV)", True, 
                            f"ID: {data['id']}, Title: {data['title']}")
                return True
            else:
                self.log_test("Upload Candidate Document (CV)", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Upload Candidate Document (CV)", False, f"Error: {str(e)}")
            return False
    
    def test_upload_candidate_document_cover_letter(self):
        """Test POST /api/files/candidate-documents with category=cover_letter"""
        if not self.candidate_token:
            self.log_test("Upload Candidate Document (Cover Letter)", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            pdf_content = self.create_test_pdf()
            
            files = {
                'file': ('lettre_motivation.pdf', io.BytesIO(pdf_content), 'application/pdf')
            }
            
            params = {
                'category': 'cover_letter',
                'title': 'Lettre de Motivation',
                'description': 'Lettre pour poste de développeur'
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/candidate-documents",
                headers=headers,
                files=files,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data['category'] != 'cover_letter':
                    self.log_test("Upload Candidate Document (Cover Letter)", False, 
                                f"Wrong category: {data['category']}", data)
                    return False
                
                self.uploaded_doc_ids.append(data['id'])
                self.log_test("Upload Candidate Document (Cover Letter)", True, 
                            f"ID: {data['id']}, Title: {data['title']}")
                return True
            else:
                self.log_test("Upload Candidate Document (Cover Letter)", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Upload Candidate Document (Cover Letter)", False, f"Error: {str(e)}")
            return False
    
    def test_max_documents_per_category(self):
        """Test max 3 documents per category enforcement"""
        if not self.candidate_token:
            self.log_test("Max Documents Per Category", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            pdf_content = self.create_test_pdf()
            
            # Upload 3 more CVs (we already have 1)
            for i in range(2, 5):
                files = {
                    'file': (f'cv_{i}.pdf', io.BytesIO(pdf_content), 'application/pdf')
                }
                params = {
                    'category': 'cv',
                    'title': f'CV Version {i}',
                    'description': f'CV numéro {i}'
                }
                
                response = self.session.post(
                    f"{API_BASE_URL}/files/candidate-documents",
                    headers=headers,
                    files=files,
                    params=params
                )
                
                if i <= 3:
                    # Should succeed for 2nd and 3rd CV
                    if response.status_code == 200:
                        data = response.json()
                        self.uploaded_doc_ids.append(data['id'])
                    else:
                        self.log_test("Max Documents Per Category", False, 
                                    f"Failed to upload CV {i}: HTTP {response.status_code}")
                        return False
                else:
                    # Should fail for 4th CV
                    if response.status_code == 400:
                        detail = response.json().get('detail', '')
                        if '3' in detail:
                            self.log_test("Max Documents Per Category", True, 
                                        f"Correctly blocked 4th CV: {detail}")
                            return True
                        else:
                            self.log_test("Max Documents Per Category", False, 
                                        f"Wrong error message: {detail}")
                            return False
                    else:
                        self.log_test("Max Documents Per Category", False, 
                                    f"Expected 400, got {response.status_code}")
                        return False
            
            return True
        except Exception as e:
            self.log_test("Max Documents Per Category", False, f"Error: {str(e)}")
            return False
    
    def test_invalid_category(self):
        """Test invalid category returns 400"""
        if not self.candidate_token:
            self.log_test("Invalid Category", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            pdf_content = self.create_test_pdf()
            
            files = {
                'file': ('test.pdf', io.BytesIO(pdf_content), 'application/pdf')
            }
            
            params = {
                'category': 'invalid_category',
                'title': 'Test',
                'description': 'Test'
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/candidate-documents",
                headers=headers,
                files=files,
                params=params
            )
            
            if response.status_code == 400:
                detail = response.json().get('detail', '')
                self.log_test("Invalid Category", True, 
                            f"Correctly rejected invalid category: {detail}")
                return True
            else:
                self.log_test("Invalid Category", False, 
                            f"Expected 400, got {response.status_code}")
                return False
        except Exception as e:
            self.log_test("Invalid Category", False, f"Error: {str(e)}")
            return False
    
    def test_invalid_extension(self):
        """Test invalid file extension returns 400"""
        if not self.candidate_token:
            self.log_test("Invalid Extension", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            
            files = {
                'file': ('test.txt', io.BytesIO(b'This is a text file'), 'text/plain')
            }
            
            params = {
                'category': 'cv',
                'title': 'Test',
                'description': 'Test'
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/candidate-documents",
                headers=headers,
                files=files,
                params=params
            )
            
            if response.status_code == 400:
                detail = response.json().get('detail', '')
                self.log_test("Invalid Extension", True, 
                            f"Correctly rejected .txt file: {detail}")
                return True
            else:
                self.log_test("Invalid Extension", False, 
                            f"Expected 400, got {response.status_code}")
                return False
        except Exception as e:
            self.log_test("Invalid Extension", False, f"Error: {str(e)}")
            return False
    
    def test_upload_profile_photo(self):
        """Test POST /api/files/upload-profile-photo"""
        if not self.candidate_token:
            self.log_test("Upload Profile Photo", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            png_content = self.create_test_image()
            
            files = {
                'file': ('profile.png', io.BytesIO(png_content), 'image/png')
            }
            
            response = self.session.post(
                f"{API_BASE_URL}/files/upload-profile-photo",
                headers=headers,
                files=files
            )
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['storage_path', 'original_filename', 'content_type', 'profile_photo_url']
                missing_fields = [f for f in required_fields if f not in data]
                
                if missing_fields:
                    self.log_test("Upload Profile Photo", False, 
                                f"Missing fields: {missing_fields}", data)
                    return False
                
                self.profile_photo_url = data['profile_photo_url']
                self.log_test("Upload Profile Photo", True, 
                            f"Photo URL: {data['profile_photo_url']}")
                return True
            else:
                self.log_test("Upload Profile Photo", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Upload Profile Photo", False, f"Error: {str(e)}")
            return False
    
    def test_profile_photo_in_user_profile(self):
        """Test GET /api/auth/me returns profile_photo_url"""
        if not self.candidate_token:
            self.log_test("Profile Photo in User Profile", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            response = self.session.get(f"{API_BASE_URL}/auth/me", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if 'profile_photo_url' in data and data['profile_photo_url']:
                    self.log_test("Profile Photo in User Profile", True, 
                                f"Profile photo URL: {data['profile_photo_url']}")
                    return True
                else:
                    self.log_test("Profile Photo in User Profile", False, 
                                "profile_photo_url not found or empty in user profile")
                    return False
            else:
                self.log_test("Profile Photo in User Profile", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Profile Photo in User Profile", False, f"Error: {str(e)}")
            return False
    
    def test_get_candidate_documents(self):
        """Test GET /api/files/candidate-documents"""
        if not self.candidate_token:
            self.log_test("Get Candidate Documents", False, "No candidate token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            response = self.session.get(
                f"{API_BASE_URL}/files/candidate-documents",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, list):
                    self.log_test("Get Candidate Documents", False, 
                                "Response is not a list", data)
                    return False
                
                # Check that we have the documents we uploaded
                cv_count = sum(1 for doc in data if doc.get('category') == 'cv')
                cover_letter_count = sum(1 for doc in data if doc.get('category') == 'cover_letter')
                
                self.log_test("Get Candidate Documents", True, 
                            f"Retrieved {len(data)} documents: {cv_count} CVs, {cover_letter_count} cover letters")
                return True
            else:
                self.log_test("Get Candidate Documents", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Candidate Documents", False, f"Error: {str(e)}")
            return False
    
    def test_update_candidate_document(self):
        """Test PUT /api/files/candidate-documents/{id}"""
        if not self.candidate_token or not self.uploaded_doc_ids:
            self.log_test("Update Candidate Document", False, "No candidate token or document IDs available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            doc_id = self.uploaded_doc_ids[0]
            
            update_data = {
                'title': 'CV Mis à Jour',
                'description': 'Description mise à jour'
            }
            
            response = self.session.put(
                f"{API_BASE_URL}/files/candidate-documents/{doc_id}",
                headers=headers,
                json=update_data
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('title') == 'CV Mis à Jour' and data.get('description') == 'Description mise à jour':
                    self.log_test("Update Candidate Document", True, 
                                f"Updated document {doc_id}")
                    return True
                else:
                    self.log_test("Update Candidate Document", False, 
                                "Title or description not updated correctly", data)
                    return False
            else:
                self.log_test("Update Candidate Document", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Update Candidate Document", False, f"Error: {str(e)}")
            return False
    
    def test_delete_candidate_document(self):
        """Test DELETE /api/files/candidate-documents/{id}"""
        if not self.candidate_token or not self.uploaded_doc_ids:
            self.log_test("Delete Candidate Document", False, "No candidate token or document IDs available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            doc_id = self.uploaded_doc_ids[0]
            
            response = self.session.delete(
                f"{API_BASE_URL}/files/candidate-documents/{doc_id}",
                headers=headers
            )
            
            if response.status_code == 200:
                # Verify it's no longer in the list
                list_response = self.session.get(
                    f"{API_BASE_URL}/files/candidate-documents",
                    headers=headers
                )
                
                if list_response.status_code == 200:
                    docs = list_response.json()
                    if not any(doc['id'] == doc_id for doc in docs):
                        self.log_test("Delete Candidate Document", True, 
                                    f"Deleted document {doc_id} (soft delete)")
                        return True
                    else:
                        self.log_test("Delete Candidate Document", False, 
                                    "Document still appears in list after deletion")
                        return False
                else:
                    self.log_test("Delete Candidate Document", False, 
                                "Could not verify deletion")
                    return False
            else:
                self.log_test("Delete Candidate Document", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Delete Candidate Document", False, f"Error: {str(e)}")
            return False
    
    def run_all_tests(self):
        """Run all file upload tests"""
        print("=" * 70)
        print("FILE UPLOAD ENDPOINTS - BUG FIX VERIFICATION")
        print("=" * 70)
        print(f"Testing API at: {API_BASE_URL}")
        print(f"Credentials: {CANDIDATE_EMAIL}")
        print()
        
        # Login first
        if not self.login_candidate():
            print("❌ Login failed. Cannot proceed with tests.")
            return
        
        print("📤 FILE UPLOAD TESTS")
        print("-" * 70)
        
        # Test all endpoints
        self.test_upload_cv()
        self.test_upload_candidate_document_cv()
        self.test_upload_candidate_document_cover_letter()
        self.test_max_documents_per_category()
        self.test_invalid_category()
        self.test_invalid_extension()
        self.test_upload_profile_photo()
        self.test_profile_photo_in_user_profile()
        self.test_get_candidate_documents()
        self.test_update_candidate_document()
        self.test_delete_candidate_document()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        
        passed = sum(1 for result in self.test_results if result["success"])
        failed = len(self.test_results) - passed
        
        print(f"Total Tests: {len(self.test_results)}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/len(self.test_results)*100):.1f}%")
        
        if failed > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")
        
        print("\n" + "=" * 70)
        
        # Final verdict
        if failed == 0:
            print("✅ ALL TESTS PASSED - BUG IS FIXED")
            print("File upload endpoints are working correctly.")
        else:
            print("❌ SOME TESTS FAILED - BUG NOT FULLY FIXED")
            print("Please review the failed tests above.")
        print("=" * 70)

if __name__ == "__main__":
    tester = FileUploadTester()
    tester.run_all_tests()
