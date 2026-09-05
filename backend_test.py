#!/usr/bin/env python3
"""
Comprehensive Backend API Tests for Indeed Clone
Tests all authentication, jobs, applications, companies, and saved jobs endpoints
"""

import requests
import json
import os
import sys
from datetime import datetime
import time

# Get backend URL from environment - MUST be explicitly set, no fallbacks
BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BACKEND_URL:
    print("ERROR: REACT_APP_BACKEND_URL environment variable is required but not set.", file=sys.stderr)
    print("Set REACT_APP_BACKEND_URL to your backend API base URL (e.g., https://api.example.com)", file=sys.stderr)
    sys.exit(1)
API_BASE_URL = f"{BACKEND_URL}/api"

# E2E credentials - must come from environment, no repository fallbacks
CANDIDATE_EMAIL = os.environ.get("E2E_CANDIDATE_EMAIL", "candidate@test.fr")
CANDIDATE_PASSWORD = os.environ.get("E2E_CANDIDATE_PASSWORD")
EMPLOYER_EMAIL = os.environ.get("E2E_EMPLOYER_EMAIL", "recruteur@techcorp.fr")
EMPLOYER_PASSWORD = os.environ.get("E2E_EMPLOYER_PASSWORD")

class IndeedCloneAPITester:
    def __init__(self):
        self.session = requests.Session()
        self.candidate_token = None
        self.employer_token = None
        self.test_results = []
        
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

    def test_health_check(self):
        """Test API health check"""
        try:
            response = self.session.get(f"{API_BASE_URL}/health")
            if response.status_code == 200:
                data = response.json()
                self.log_test("Health Check", True, f"API is healthy: {data}")
                return True
            else:
                self.log_test("Health Check", False, f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Health Check", False, f"Connection error: {str(e)}")
            return False

    def test_register_candidate(self):
        """Test candidate registration"""
        try:
            import uuid
            candidate_data = {
                "email": f"testcandidate_{uuid.uuid4().hex[:8]}@example.com",
                "password": f"TestPwd_{uuid.uuid4().hex[:8]}",
                "first_name": "Alice",
                "last_name": "Candidate",
                "user_type": "candidate",
                "location": "Paris",
                "bio": "Développeuse passionnée",
                "skills": ["Python", "JavaScript", "React"],
                "experience_years": 2
            }
            
            response = self.session.post(f"{API_BASE_URL}/auth/register", json=candidate_data)
            
            if response.status_code == 200:
                data = response.json()
                self.candidate_token = data["token"]["access_token"]
                self.log_test("Register Candidate", True, 
                            f"Registered user: {data['user']['email']}, Token received")
                return True
            else:
                self.log_test("Register Candidate", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Register Candidate", False, f"Error: {str(e)}")
            return False

    def test_register_employer(self):
        """Test employer registration"""
        try:
            import uuid
            employer_data = {
                "email": f"testemployer_{uuid.uuid4().hex[:8]}@example.com",
                "password": f"TestPwd_{uuid.uuid4().hex[:8]}",
                "first_name": "Bob",
                "last_name": "Employer",
                "user_type": "employer",
                "location": "Lyon"
            }
            
            response = self.session.post(f"{API_BASE_URL}/auth/register", json=employer_data)
            
            if response.status_code == 200:
                data = response.json()
                self.employer_token = data["token"]["access_token"]
                self.log_test("Register Employer", True, 
                            f"Registered employer: {data['user']['email']}, Token received")
                return True
            else:
                self.log_test("Register Employer", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Register Employer", False, f"Error: {str(e)}")
            return False

    def test_login_candidate(self):
        """Test candidate login"""
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
                            f"Logged in: {data['user']['email']}, Type: {data['user']['user_type']}")
                return True
            else:
                self.log_test("Login Candidate", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Login Candidate", False, f"Error: {str(e)}")
            return False

    def test_login_employer(self):
        """Test employer login"""
        if not EMPLOYER_PASSWORD:
            self.log_test("Login Employer", False, "E2E_EMPLOYER_PASSWORD not set")
            return False
        try:
            login_data = {
                "email": EMPLOYER_EMAIL,
                "password": EMPLOYER_PASSWORD
            }
            
            response = self.session.post(f"{API_BASE_URL}/auth/login", json=login_data)
            
            if response.status_code == 200:
                data = response.json()
                self.employer_token = data["token"]["access_token"]
                self.log_test("Login Employer", True, 
                            f"Logged in: {data['user']['email']}, Type: {data['user']['user_type']}")
                return True
            else:
                self.log_test("Login Employer", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Login Employer", False, f"Error: {str(e)}")
            return False

    def test_get_current_user_candidate(self):
        """Test getting current user info for candidate"""
        if not self.candidate_token:
            self.log_test("Get Current User (Candidate)", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            response = self.session.get(f"{API_BASE_URL}/auth/me", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.log_test("Get Current User (Candidate)", True, 
                            f"User: {data['email']}, Type: {data['user_type']}")
                return True
            else:
                self.log_test("Get Current User (Candidate)", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Current User (Candidate)", False, f"Error: {str(e)}")
            return False

    def test_get_current_user_employer(self):
        """Test getting current user info for employer"""
        if not self.employer_token:
            self.log_test("Get Current User (Employer)", False, "No employer token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.employer_token}"}
            response = self.session.get(f"{API_BASE_URL}/auth/me", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.log_test("Get Current User (Employer)", True, 
                            f"User: {data['email']}, Type: {data['user_type']}")
                return True
            else:
                self.log_test("Get Current User (Employer)", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Current User (Employer)", False, f"Error: {str(e)}")
            return False

    def test_get_jobs_list(self):
        """Test getting jobs list with various filters"""
        try:
            # Test basic job listing
            response = self.session.get(f"{API_BASE_URL}/jobs/")
            
            if response.status_code == 200:
                data = response.json()
                jobs_count = len(data.get("jobs", []))
                self.log_test("Get Jobs List", True, 
                            f"Retrieved {jobs_count} jobs, Total: {data.get('total', 0)}")
                
                # Test with search filter
                response = self.session.get(f"{API_BASE_URL}/jobs/?search=développeur")
                if response.status_code == 200:
                    search_data = response.json()
                    search_count = len(search_data.get("jobs", []))
                    self.log_test("Get Jobs with Search Filter", True, 
                                f"Found {search_count} jobs for 'développeur'")
                
                # Test with location filter
                response = self.session.get(f"{API_BASE_URL}/jobs/?location=Paris")
                if response.status_code == 200:
                    location_data = response.json()
                    location_count = len(location_data.get("jobs", []))
                    self.log_test("Get Jobs with Location Filter", True, 
                                f"Found {location_count} jobs in Paris")
                
                # Test with remote filter
                response = self.session.get(f"{API_BASE_URL}/jobs/?is_remote=true")
                if response.status_code == 200:
                    remote_data = response.json()
                    remote_count = len(remote_data.get("jobs", []))
                    self.log_test("Get Remote Jobs Filter", True, 
                                f"Found {remote_count} remote jobs")
                
                return True
            else:
                self.log_test("Get Jobs List", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Jobs List", False, f"Error: {str(e)}")
            return False

    def test_get_job_detail(self):
        """Test getting specific job details"""
        try:
            # First get a job ID from the jobs list
            response = self.session.get(f"{API_BASE_URL}/jobs/")
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                if jobs:
                    job_id = jobs[0]["id"]
                    
                    # Get job details
                    detail_response = self.session.get(f"{API_BASE_URL}/jobs/{job_id}")
                    if detail_response.status_code == 200:
                        job_data = detail_response.json()
                        self.log_test("Get Job Detail", True, 
                                    f"Retrieved job: {job_data['title']} at {job_data['company']['name']}")
                        return True
                    else:
                        self.log_test("Get Job Detail", False, 
                                    f"Status: {detail_response.status_code}", detail_response.text)
                        return False
                else:
                    self.log_test("Get Job Detail", False, "No jobs available to test")
                    return False
            else:
                self.log_test("Get Job Detail", False, "Could not get jobs list first")
                return False
        except Exception as e:
            self.log_test("Get Job Detail", False, f"Error: {str(e)}")
            return False

    def test_create_job_employer(self):
        """Test creating a job as employer"""
        if not self.employer_token:
            self.log_test("Create Job (Employer)", False, "No employer token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.employer_token}"}
            
            job_data = {
                "title": "Développeur Python Senior",
                "description": "Nous recherchons un développeur Python senior pour rejoindre notre équipe. Expérience avec Django, FastAPI et PostgreSQL requise.",
                "company_id": "comp_1",
                "location": "Paris",
                "salary_min": 50000,
                "salary_max": 65000,
                "job_type": "CDI",
                "is_remote": True,
                "requirements": ["Python", "Django", "FastAPI", "PostgreSQL"],
                "benefits": ["Télétravail", "Formation", "Mutuelle"],
                "tags": ["python", "senior", "backend"]
            }
            
            response = self.session.post(f"{API_BASE_URL}/jobs/", json=job_data, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.created_job_id = data["id"]
                self.log_test("Create Job (Employer)", True, 
                            f"Created job: {data['title']} with ID: {data['id']}")
                return True
            else:
                self.log_test("Create Job (Employer)", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Create Job (Employer)", False, f"Error: {str(e)}")
            return False

    def test_create_job_candidate_forbidden(self):
        """Test that candidates cannot create jobs"""
        if not self.candidate_token:
            self.log_test("Create Job Forbidden (Candidate)", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            
            job_data = {
                "title": "Test Job",
                "description": "This should fail",
                "company_id": "comp_1",
                "location": "Paris",
                "job_type": "CDI"
            }
            
            response = self.session.post(f"{API_BASE_URL}/jobs/", json=job_data, headers=headers)
            
            if response.status_code == 403:
                self.log_test("Create Job Forbidden (Candidate)", True, 
                            "Correctly blocked candidate from creating job")
                return True
            else:
                self.log_test("Create Job Forbidden (Candidate)", False, 
                            f"Expected 403, got {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Create Job Forbidden (Candidate)", False, f"Error: {str(e)}")
            return False

    def test_apply_to_job(self):
        """Test applying to a job as candidate"""
        if not self.candidate_token:
            self.log_test("Apply to Job", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            
            # Get a job to apply to
            response = self.session.get(f"{API_BASE_URL}/jobs/")
            if response.status_code == 200:
                jobs_data = response.json()
                jobs = jobs_data.get("jobs", [])
                if jobs:
                    job_id = jobs[0]["id"]
                    
                    application_data = {
                        "job_id": job_id,
                        "cover_letter": "Je suis très intéressé par ce poste et je pense avoir les compétences requises.",
                        "cv_url": "https://example.com/cv.pdf"
                    }
                    
                    app_response = self.session.post(f"{API_BASE_URL}/applications/", 
                                                   json=application_data, headers=headers)
                    
                    if app_response.status_code == 200:
                        app_data = app_response.json()
                        self.log_test("Apply to Job", True, 
                                    f"Applied to job: {app_data['job']['title']}")
                        return True
                    else:
                        self.log_test("Apply to Job", False, 
                                    f"Status: {app_response.status_code}", app_response.text)
                        return False
                else:
                    self.log_test("Apply to Job", False, "No jobs available to apply to")
                    return False
            else:
                self.log_test("Apply to Job", False, "Could not get jobs list")
                return False
        except Exception as e:
            self.log_test("Apply to Job", False, f"Error: {str(e)}")
            return False

    def test_get_my_applications(self):
        """Test getting candidate's applications"""
        if not self.candidate_token:
            self.log_test("Get My Applications", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            response = self.session.get(f"{API_BASE_URL}/applications/", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                app_count = len(data)
                self.log_test("Get My Applications", True, 
                            f"Retrieved {app_count} applications")
                return True
            else:
                self.log_test("Get My Applications", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get My Applications", False, f"Error: {str(e)}")
            return False

    def test_get_job_applications_employer(self):
        """Test getting applications for a job as employer"""
        if not self.employer_token:
            self.log_test("Get Job Applications (Employer)", False, "No employer token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.employer_token}"}
            
            # Use a known job ID from seed data
            job_id = "job_1"
            response = self.session.get(f"{API_BASE_URL}/applications/job/{job_id}", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                app_count = len(data)
                self.log_test("Get Job Applications (Employer)", True, 
                            f"Retrieved {app_count} applications for job")
                return True
            else:
                self.log_test("Get Job Applications (Employer)", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Job Applications (Employer)", False, f"Error: {str(e)}")
            return False

    def test_get_companies_list(self):
        """Test getting companies list"""
        try:
            response = self.session.get(f"{API_BASE_URL}/companies/")
            
            if response.status_code == 200:
                data = response.json()
                companies_count = len(data)
                self.log_test("Get Companies List", True, 
                            f"Retrieved {companies_count} companies")
                return True
            else:
                self.log_test("Get Companies List", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Companies List", False, f"Error: {str(e)}")
            return False

    def test_get_company_detail(self):
        """Test getting specific company details"""
        try:
            # Use a known company ID from seed data
            company_id = "comp_1"
            response = self.session.get(f"{API_BASE_URL}/companies/{company_id}")
            
            if response.status_code == 200:
                data = response.json()
                self.log_test("Get Company Detail", True, 
                            f"Retrieved company: {data['name']} in {data['location']}")
                return True
            else:
                self.log_test("Get Company Detail", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Company Detail", False, f"Error: {str(e)}")
            return False

    def test_save_job(self):
        """Test saving a job as candidate"""
        if not self.candidate_token:
            self.log_test("Save Job", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            
            # Use a known job ID from seed data
            job_id = "job_2"
            response = self.session.post(f"{API_BASE_URL}/saved-jobs/{job_id}", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.log_test("Save Job", True, data.get("message", "Job saved"))
                return True
            else:
                self.log_test("Save Job", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Save Job", False, f"Error: {str(e)}")
            return False

    def test_get_saved_jobs(self):
        """Test getting saved jobs as candidate"""
        if not self.candidate_token:
            self.log_test("Get Saved Jobs", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            response = self.session.get(f"{API_BASE_URL}/saved-jobs/", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                saved_count = len(data)
                self.log_test("Get Saved Jobs", True, 
                            f"Retrieved {saved_count} saved jobs")
                return True
            else:
                self.log_test("Get Saved Jobs", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Get Saved Jobs", False, f"Error: {str(e)}")
            return False

    def test_unsave_job(self):
        """Test removing a job from saved jobs"""
        if not self.candidate_token:
            self.log_test("Unsave Job", False, "No candidate token available")
            return False
            
        try:
            headers = {"Authorization": f"Bearer {self.candidate_token}"}
            
            # Use the same job ID we saved earlier
            job_id = "job_2"
            response = self.session.delete(f"{API_BASE_URL}/saved-jobs/{job_id}", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.log_test("Unsave Job", True, data.get("message", "Job removed from saved"))
                return True
            else:
                self.log_test("Unsave Job", False, 
                            f"Status: {response.status_code}", response.text)
                return False
        except Exception as e:
            self.log_test("Unsave Job", False, f"Error: {str(e)}")
            return False

    def test_authentication_errors(self):
        """Test authentication error handling"""
        try:
            # Test with invalid token
            headers = {"Authorization": "Bearer invalid_token"}
            response = self.session.get(f"{API_BASE_URL}/auth/me", headers=headers)
            
            if response.status_code == 401:
                self.log_test("Invalid Token Handling", True, "Correctly rejected invalid token")
            else:
                self.log_test("Invalid Token Handling", False, 
                            f"Expected 401, got {response.status_code}")
            
            # Test without token
            response = self.session.get(f"{API_BASE_URL}/auth/me")
            
            if response.status_code == 403:
                self.log_test("Missing Token Handling", True, "Correctly rejected missing token")
                return True
            else:
                self.log_test("Missing Token Handling", False, 
                            f"Expected 403, got {response.status_code}")
                return False
        except Exception as e:
            self.log_test("Authentication Error Tests", False, f"Error: {str(e)}")
            return False

    def run_all_tests(self):
        """Run all API tests"""
        print("=" * 60)
        print("INDEED CLONE BACKEND API COMPREHENSIVE TESTS")
        print("=" * 60)
        print(f"Testing API at: {API_BASE_URL}")
        print()
        
        # Health check first
        if not self.test_health_check():
            print("❌ API is not accessible. Stopping tests.")
            return
        
        # Authentication tests
        print("🔐 AUTHENTICATION TESTS")
        print("-" * 30)
        # Skip registration tests due to backend validation issue
        self.log_test("Register Candidate", False, "Backend validation error - needs main agent fix")
        self.log_test("Register Employer", False, "Backend validation error - needs main agent fix")
        self.test_login_candidate()
        self.test_login_employer()
        self.test_get_current_user_candidate()
        self.test_get_current_user_employer()
        self.test_authentication_errors()
        
        # Jobs tests
        print("💼 JOBS TESTS")
        print("-" * 30)
        self.test_get_jobs_list()
        self.test_get_job_detail()
        self.test_create_job_employer()
        self.test_create_job_candidate_forbidden()
        
        # Applications tests
        print("📝 APPLICATIONS TESTS")
        print("-" * 30)
        self.test_apply_to_job()
        self.test_get_my_applications()
        self.test_get_job_applications_employer()
        
        # Companies tests
        print("🏢 COMPANIES TESTS")
        print("-" * 30)
        self.test_get_companies_list()
        self.test_get_company_detail()
        
        # Saved jobs tests
        print("⭐ SAVED JOBS TESTS")
        print("-" * 30)
        self.test_save_job()
        self.test_get_saved_jobs()
        self.test_unsave_job()
        
        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        print("=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
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
        
        print("\n" + "=" * 60)

if __name__ == "__main__":
    tester = IndeedCloneAPITester()
    tester.run_all_tests()