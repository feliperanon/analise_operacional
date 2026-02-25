# Task: Bulk Absence Import

- [x] Design Import Logic (Columns: Matricula, Data, Ocorrencia) <!-- id: 0 -->
- [x] Fix Missing Imports in main.py `api_operational_routes`
- [ ] Add Duration/Hours column to Operational History
    - [x] Backend: Calculate duration in `api_operational_routes`
    - [x] Frontend: Add Duration column to table in `operational_history.html`
    - [x] Frontend: Fix "invisible" buttons by switching to Lucide Icons
    - [x] Frontend: Add links to Employee and Client details
    - [x] Frontend: Standardize styling
- [ ] Fix Mobile Dashboard Issues
    - [x] Timer Logic: Use manual math instead of Date object (Fix "21:00")
    - [x] Layout: Fix "Broken" appearance (responsive card)
- [x] Add Import Button/Modal to `employees.html` <!-- id: 2 -->
- [x] Test with sample data <!-- id: 3 -->

# Task: Loading Team Evaluation Module

- [ ] Create `LoadingSession` and `EmployeePerformanceReview` models <!-- id: 4 -->
- [ ] Create `/loading/performance` UI (Dashboard + Input Form) <!-- id: 5 -->
- [ ] Implement Backend Logic for Sessions and Reviews <!-- id: 6 -->

# Task: Mobile Access Control & Rankings

- [x] Rankings: Unified list, filters (Period, Shift), Metrics, Details Modal
- [x] Backend: Add valid `mobile_access` field to Employee model
- [x] Frontend: Add toggle in Employee Details
- [x] Security: Enforce access control in `/mobile` routes (Login & Dashboard)
- [ ] Rankings: Refine Frontend (Responsiveness, Modal interactions)
- [ ] Tests: Add Unit/Integration tests for Rankings logic
