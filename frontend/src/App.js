import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import Home from "./pages/Home";
import CandidateProfile from "./pages/CandidateProfile";
import MyApplications from "./pages/MyApplications";
import SavedJobs from "./pages/SavedJobs";
import MyAlerts from "./pages/MyAlerts";
import SavedSearches from "./pages/SavedSearches";
import MyCV from "./pages/MyCV";
import MyCoverLetters from "./pages/MyCoverLetters";
import PostJob from "./pages/PostJob";
import MyJobs from "./pages/MyJobs";
import ApplicationsForJob from "./pages/ApplicationsForJob";
import EmployerDashboard from "./pages/EmployerDashboard";
import JobDetail from "./pages/JobDetail";
import AuthCallback from "./pages/AuthCallback";
import AdminDashboard from "./pages/AdminDashboard";
import RecruiterLanding from "./pages/RecruiterLanding";
import PartnerDashboard from "./pages/PartnerDashboard";
import PaymentSuccess from "./pages/PaymentSuccess";
import PaymentCancel from "./pages/PaymentCancel";
import Recommendations from "./pages/Recommendations";
import Messages from "./pages/Messages";
import RecruiterAnalytics from "./pages/RecruiterAnalytics";
import { Toaster } from "./components/ui/toaster";

function AppRoutes() {
  const location = useLocation();
  // Handle Emergent Google Auth callback (session_id in URL fragment) before normal routing
  if (location.hash && location.hash.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/recruteur" element={<RecruiterLanding />} />
      <Route path="/jobs/:jobId" element={<JobDetail />} />
      <Route path="/profile" element={<CandidateProfile />} />
      <Route path="/my-applications" element={<MyApplications />} />
      <Route path="/saved-jobs" element={<SavedJobs />} />
      <Route path="/my-alerts" element={<MyAlerts />} />
      <Route path="/saved-searches" element={<SavedSearches />} />
      <Route path="/my-cv" element={<MyCV />} />
      <Route path="/my-cover-letters" element={<MyCoverLetters />} />
      <Route path="/my-jobs" element={<MyJobs />} />
      <Route path="/my-jobs/:jobId/applications" element={<ApplicationsForJob />} />
      <Route path="/post-job" element={<PostJob />} />
      <Route path="/employer-dashboard" element={<EmployerDashboard />} />
      <Route path="/adminos" element={<AdminDashboard />} />
      <Route path="/partenaire" element={<PartnerDashboard />} />
      <Route path="/payment/success" element={<PaymentSuccess />} />
      <Route path="/payment/cancel" element={<PaymentCancel />} />
      <Route path="/recommendations" element={<Recommendations />} />
      <Route path="/messages" element={<Messages />} />
      <Route path="/recruiter-analytics" element={<RecruiterAnalytics />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
          <Toaster />
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
