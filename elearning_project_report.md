# EduNova eLearning System Project Report

## Title Page

EduNova: Intelligent eLearning Platform

Project Report submitted in partial fulfillment of the requirements for the degree of Bachelor of Engineering in Computer Science.

Submitted by: [Student Name]

Supervisor: [Supervisor Name]

Department of Computer Science

[College / University Name]

Month, Year

---

## Declaration

I hereby declare that this project report entitled "EduNova: Intelligent eLearning Platform" is my original work and has not been submitted earlier for any degree or diploma at any university.

---

## Certificate

This is to certify that the project report titled "EduNova: Intelligent eLearning Platform" has been carried out by [Student Name] under my supervision and guidance.

Signature of Guide: ______________________

Signature of Student: ______________________

Date: ______________

---

## Acknowledgement

I would like to express my sincere gratitude to my project guide, faculty members, and peers for their support during the development of EduNova. Their guidance helped shape the architecture, design decisions, and final implementation of this eLearning system.

I would also like to thank the department, the university library, internet resources, and all those who contributed to the research and development of this project.

---

## Abstract

EduNova is a web-based eLearning platform designed to support students, teachers, and administrators in a modern digital classroom environment. The system enables role-based access control, secure login, content upload and distribution, quiz creation and evaluation, live class and chat features, and data-driven analytics.

This project report describes the system requirements, functional modules, implementation details, technical architecture, testing procedures, and future scope for expanding EduNova into a scalable educational solution.

---

## Table of Contents

1. Introduction
2. Project Overview
3. Problem Statement
4. Objectives
5. Scope of the Project
6. Literature Review
7. System Analysis
8. System Design
9. Database Design
10. Implementation
11. User Interface Design
12. Functional Requirements
13. Non-Functional Requirements
14. Security Features
15. Testing and Validation
16. Deployment Strategy
17. Results and Discussion
18. Conclusion
19. Future Enhancements
20. References
21. Appendices

---

## List of Figures

- Figure 1: EduNova System Architecture
- Figure 2: Role-Based Access Flow
- Figure 3: Database Schema and Relationships
- Figure 4: Upload and Permission Workflow
- Figure 5: Quiz Creation and Evaluation Flow
- Figure 6: Live Class and Chat Interaction Diagram

---

## List of Tables

- Table 1: Functional Requirements Matrix
- Table 2: Non-Functional Requirements Matrix
- Table 3: User Roles and Permissions
- Table 4: Content Types and Allowed File Formats
- Table 5: Database Tables and Fields
- Table 6: Test Case Summary

---

# 1. Introduction

The evolution of digital learning has accelerated demand for flexible, secure, and engaging educational platforms. EduNova aims to address the needs of students, teachers, and administrators by offering a unified environment for content delivery, assessment, communication, and performance analytics.

The platform is built with Python and Flask, using MySQL for storage and Flask-SocketIO for real-time chat and live classroom interactions. EduNova supports video, photo, and PDF content uploads, and it assigns resources to students based on permissions.

# 2. Project Overview

EduNova is a role-based eLearning system with three primary user roles:

- **Admin**: Manages users, content, system settings, and analytics.
- **Teacher**: Uploads course materials, creates quizzes, conducts live classes, and monitors student progress.
- **Student**: Views assigned content, takes quizzes, reviews results, and participates in chat/live sessions.

Key features include:

- Authentication and secure session management
- Teacher registration approval workflow
- Role-specific dashboards
- Video, photo, and PDF upload with permission controls
- Quiz creation, assignment, and evaluation
- Student progress tracking and score review
- Live class and chat using WebSocket communication
- Clustering analytics for student performance grouping
- Audit logging and session timeout security

# 3. Problem Statement

Traditional classroom systems lack centralized access to multimedia learning materials, fine-grained permission control, and real-time interaction across student and teacher roles. EduNova solves this problem by providing:

- A single platform for content sharing and academic evaluation
- Permission-based access to ensure only authorized students view relevant materials
- Live communication support for online classes and collaborative learning
- Analytics to help administrators and teachers understand student performance trends

# 4. Objectives

The main objectives of EduNova are:

- To create a secure multi-role eLearning platform
- To support upload and delivery of multimedia learning resources
- To enable quiz creation and automated evaluation
- To implement live classroom and chat functionality
- To provide performance analytics that facilitate decision making

# 5. Scope of the Project

EduNova covers the following areas:

- User registration and login for students, teachers, and admin
- Content upload and distribution
- Role-based dashboards and permissions
- Quiz management and result review
- Real-time communication via live class and chat
- Data analysis for performance clustering
- Security features such as session timeout and audit log

Areas excluded from the current version:

- Mobile application support
- Advanced learning management system (LMS) features such as course scheduling and grading rubrics
- External API integrations (e.g., Google Classroom, Zoom)
- Detailed recommendation engine beyond initial data structures

# 6. Literature Review

This chapter reviews existing eLearning platforms and digital education methods. It compares features such as content distribution, assessment, communication, and analytics.

### 6.1 E-Learning Platforms

- Learning Management Systems (LMS) such as Moodle, Canvas, and Blackboard
- Video-first platforms like Coursera, Udemy, and Khan Academy
- Real-time classrooms with chat and video like Zoom, Microsoft Teams, and Google Meet

### 6.2 Relevant Technologies

- Flask for lightweight web applications
- MySQL for relational data storage
- Flask-SocketIO for real-time communication
- Python libraries like pandas and scikit-learn for data analytics

### 6.3 Gap Analysis

Existing systems often require complex setup or lack tight integration of multimedia content, quizzes, and live interactions in one platform. EduNova addresses this gap by offering a unified classroom experience with permission control and analytics.

# 7. System Analysis

This chapter analyzes user requirements, system constraints, and the functional architecture of EduNova.

### 7.1 User Requirements

- Students should access only content assigned to them.
- Teachers should upload materials and create quizzes.
- Admin should monitor platform usage and approve teacher accounts.
- All users should communicate through chat and live class sessions.

### 7.2 Functional Requirements

Refer to Table 1 for a complete list of features and acceptance criteria.

### 7.3 Non-Functional Requirements

- Security: password hashing, session timeout, audit trails
- Reliability: stable file uploads, error handling, backup-ready database
- Performance: efficient query design for content and quiz retrieval
- Usability: responsive templates for student, teacher, and admin dashboards

### 7.4 Constraints

- Hosting environment requires MySQL and Python 3.11+.
- Large file uploads must be supported up to 4 GB.
- The platform should run on local or cloud servers with appropriate storage.

# 8. System Design

This chapter explains architecture, modules, and user interaction flows.

### 8.1 Overall Architecture

EduNova follows a three-tier web architecture:

- **Presentation Layer**: HTML templates rendered by Flask and client-side JavaScript for interactivity.
- **Application Layer**: Flask routes, business logic, authentication, file handling, and analytics.
- **Data Layer**: MySQL database storing users, content, tests, permissions, scores, comments, and audit logs.

### 8.2 Module Breakdown

- **Authentication Module**: Handles login, registration, password hashing, role validation, and session timeout.
- **Content Management Module**: Supports uploading videos, photos, and PDFs; applies permission controls; lists content for users.
- **Test Module**: Enables test creation, question storage, permission assignment, student access, and score evaluation.
- **Communication Module**: Manages live classes and chat rooms using SocketIO events.
- **Analytics Module**: Provides dashboards, student clustering, and performance distribution.
- **Administration Module**: Admin dashboard, user creation, profile updates, and system statistics.

### 8.3 Data Flow

- Users log in and are redirected to a dashboard according to role.
- Teachers upload content and assign it to specific students or classes.
- Students can view assigned content and attempt quizzes.
- Admin monitors platform usage and approves teacher accounts.
- Real-time events are sent between clients using SocketIO.

# 9. Database Design

EduNova uses a relational schema optimized for permissions and analytics.

### 9.1 Table Structure

- `users`: user account records with role, password hash, class name, approval status, and last active timestamp.
- `content`: uploaded learning resources and metadata.
- `content_permissions`: mapping of content IDs to student usernames.
- `tests`: quiz headers and due dates.
- `questions`: quiz questions, options, and correct answers.
- `quiz_permissions`: mapping of tests to students.
- `student_scores`: student quiz submissions, scores, answers, and timestamps.
- `comments`: feedback and comments attached to content.
- `bookmarks`: student bookmarks on learning items.
- `audit_log`: activity logging for security and audit purposes.

### 9.2 Relationships

- Users can be students, teachers, or admins.
- Content is uploaded by teachers/admins and assigned to students.
- Tests are created by teachers and assigned per student or class.
- Student scores belong to specific tests and students.

### 9.3 ER Diagram Description

The ER diagram shows:

- One-to-many relationship between `users` and `content` via `uploaded_by`.
- Many-to-many relationship between `content` and `students` through `content_permissions`.
- Many-to-many relationship between `tests` and `students` through `quiz_permissions`.
- One-to-many relationship between `tests` and `questions`.
- One-to-many relationship between `student_scores` and `tests`.

# 10. Implementation

This chapter provides implementation details and code architecture.

### 10.1 Technology Stack

- Python 3.x
- Flask
- Flask-SocketIO
- MySQL
- pandas
- scikit-learn
- Werkzeug

### 10.2 Application Configuration

EduNova configures secure session management, upload directories, and maximum allowed file size (4 GB). It also includes graceful error handling for oversized uploads.

### 10.3 Authentication and Authorization

- Passwords are hashed with `werkzeug.security.generate_password_hash`.
- Sessions store user role, ID, username, and last activity.
- Decorator `login_required(role)` enforces role-based access to different endpoints.
- The `check_session_timeout` hook logs out users after 30 minutes of inactivity.

### 10.4 File Upload Management

- Supports `video`, `photo`, and `pdf` uploads.
- Validates file extensions and saves files to dedicated folders.
- Generates unique filenames with timestamps to avoid collisions.
- Implements permission assignment through `content_permissions`.

### 10.5 Content and Permission Logic

- Teachers and admins can upload multimedia content and link it to selected students or an entire class.
- Students can only access content they are authorized to view.
- Direct file URL access for students is blocked; students must use the `/view_content/<id>` endpoint.

### 10.6 Quiz Engine

- Teachers create tests with multiple questions and options.
- Quizzes can be assigned to individual students or classes.
- Student answers are stored in JSON format in `student_scores`.
- Quiz submission calculates score percentage and prevents repeat submissions.

### 10.7 Communication Features

- Live classes and chat are powered by SocketIO.
- Users join rooms, exchange messages, and share connection offers for real-time interaction.
- Teacher live event notifications are broadcast via WebSocket.

### 10.8 Analytics Engine

- Admin dashboard calculates total students, teachers, content counts, and pending approvals.
- Performance distribution is generated from average quiz scores.
- Student clustering uses `scikit-learn` KMeans on quiz score data.

### 10.9 Error Handling and Logging

- Database connection failures return JSON error responses.
- File uploads report invalid formats or save failures.
- Audit events are logged for login, upload, teacher registration, and content actions.

# 11. User Interface Design

EduNova includes templates for each user role.

### 11.1 Login and Registration

- `login.html`: fields for username and password, plus links to student and teacher registration.
- `register.html`: student registration with class selection.
- `register_teacher.html`: teacher signup requiring admin approval.

### 11.2 Admin Dashboard

- `admin.html`: overview of system statistics, pending teacher approvals, user creation, and content management.
- Admin can update profile, create users, and view analytics.

### 11.3 Teacher Dashboard

- `teacher.html`: teacher role dashboard for uploading content, creating quizzes, and tracking student access.
- Provides content assignment controls and class-based distribution.

### 11.4 Student Dashboard

- `student.html`: student role dashboard for browsing assigned videos, photos, PDFs, bookmarks, and available quizzes.
- Students can open content, take tests, view scores, and review quiz answers.

### 11.5 Live Class and Chat Pages

- `live_class.html`: supports joining a live class and receiving real-time notifications.
- `chat.html`: general chat interface for role-based messaging among users.

### 11.6 Review Page

- `quiz_review.html`: displays quiz questions, student answers, correct answers, and score summary.

# 12. Functional Requirements

### 12.1 Authentication

- Users must sign in to enter the system.
- Teachers require admin approval before first login.
- Sessions expire after 30 minutes of inactivity.

### 12.2 Content Management

- Upload videos, photos, and PDFs.
- Assign content to students or classes.
- Delete content and revoke permissions.

### 12.3 Quiz Management

- Create quizzes with multiple questions.
- Assign quizzes using permissions.
- Store and evaluate responses automatically.
- Display review and score details.

### 12.4 Communication and Live Learning

- Allow real-time chat.
- Support live class notifications and room join/leave events.

### 12.5 Analytics

- Show total user and content statistics.
- Generate average score charts.
- Perform student clustering based on scores.

# 13. Non-Functional Requirements

### 13.1 Performance

- Handle large file uploads efficiently.
- Use caching strategies at the browser level for static files.

### 13.2 Security

- Use password hashing and secure session cookies.
- Restrict content access with permission checks.
- Protect against unauthorized direct file downloads.

### 13.3 Reliability

- Ensure database connections are validated and closed.
- Include error handling for all critical operations.

### 13.4 Usability

- Maintain a clear navigation structure per role.
- Present messages and error feedback clearly.

### 13.5 Maintainability

- Follow modular Flask route design.
- Keep database schema extensible with migrations.

# 14. Security Features

- Passwords are hashed with industry-standard hashing.
- Session expiration prevents unauthorized prolonged access.
- Admin approval prevents unverified teachers from entering the system.
- Content access is enforced by server-side permission checks.
- Audit logs record important actions such as login, uploads, and account creation.

# 15. Testing and Validation

### 15.1 Unit Testing Strategy

Although explicit tests are not part of the current codebase, the following test cases were used for validation:

- Login with correct and incorrect credentials.
- Teacher registration and approval workflow.
- Student access only to assigned content.
- File upload validation for videos, photos, and PDFs.
- Test creation, assignment, submission, and score calculation.
- Chat and live class event broadcasting.
- Session timeout and permission redirect behavior.

### 15.2 Functional Testing

- Content upload and permission assignment.
- Student dashboard listing of assigned materials.
- Admin metrics and teacher approval counts.
- Content deletion and safe file cleanup.

### 15.3 Integration Testing

- End-to-end flow from login to content viewing and quiz submission.
- Real-time chat events across connected browser clients.
- Data-driven clustering and chart generation.

# 16. Deployment Strategy

### 16.1 Environment Setup

- Install Python dependencies from `requirements.txt`.
- Create and configure MySQL database `elearning_db`.
- Set up upload directories under `elearning/uploads/video`, `elearning/uploads/photo`, and `elearning/uploads/pdf`.
- Ensure file permissions allow Flask to save user uploads.

### 16.2 Production Configuration

- Use a WSGI server such as Gunicorn or uWSGI to host the Flask app.
- Use a reverse proxy like Nginx for secure SSL/TLS termination.
- Configure environment variables for secret keys and database credentials.

### 16.3 Backup and Recovery

- Back up MySQL data regularly.
- Store uploaded files in persistent storage.
- Use database migrations to preserve schema changes.

# 17. Results and Discussion

EduNova demonstrates a working eLearning platform with a complete role-based workflow and multimedia support. Key results include:

- Students successfully access assigned content and complete quizzes.
- Teachers create quizzes and assign learning materials with class or student granularity.
- Admin dashboard displays accurate totals of users and content.
- Real-time chat and live class features enable interactive sessions.
- Student performance clustering provides early insights into learning groups.

# 18. Conclusion

This project delivers a functional eLearning platform that supports secure authentication, content management, quizzes, communication, and analytics. EduNova provides a foundation for digital classroom experiences by integrating multimedia learning resources with role-based permissions and real-time interaction.

The project demonstrates how small to medium educational institutions can leverage open-source tools such as Flask and MySQL to build a flexible learning system.

# 19. Future Enhancements

Potential future improvements include:

- Mobile app support for Android and iOS.
- Advanced recommendation engine for personalized learning.
- Video conferencing integration for richer live classes.
- Course and syllabus management with scheduling.
- Automated reporting and progress dashboards.
- Improved analytics with predictive student performance models.

# 20. References

- Flask Documentation, https://flask.palletsprojects.com/
- Flask-SocketIO Documentation, https://flask-socketio.readthedocs.io/
- MySQL Documentation, https://dev.mysql.com/doc/
- scikit-learn Documentation, https://scikit-learn.org/
- Werkzeug Security, https://werkzeug.palletsprojects.com/

# 21. Appendices

## Appendix A: Code Snippets

### A.1 User Authentication

```python
session.update(
    loggedin=True,
    id=user['id'],
    username=user['username'],
    role=user['role'],
    last_activity=datetime.utcnow().timestamp(),
    _db_last_active_touch=0,
)
```

### A.2 Permission Query for Student Content

```python
query = """
    SELECT c.id, c.title, c.filename, c.file_type, c.upload_date, c.uploaded_by,
           COALESCE(c.view_count, 0) AS view_count,
           IF(b.id IS NOT NULL, 1, 0) AS is_bookmarked
    FROM content c
    JOIN content_permissions cp ON c.id = cp.content_id
    LEFT JOIN bookmarks b ON b.content_id = c.id AND b.student_username = %s
    WHERE c.file_type = %s AND cp.student_username = %s
"""
```

## Appendix B: Database Schema Summary

- `users(id, username, password, role, class_name, is_approved, last_active)`
- `content(id, title, file_type, filename, uploaded_by, upload_date, view_count)`
- `content_permissions(id, content_id, student_username)`
- `tests(id, title, due_date, created_by, created_at)`
- `questions(id, test_id, question_text, options, correct_answer)`
- `student_scores(id, student_username, test_id, score, answers_json, submission_date)`
- `comments(id, content_id, user_username, comment_text, sentiment, created_at)`
- `quiz_permissions(id, test_id, student_username)`
- `audit_log(id, actor_username, action, details, created_at)`

## Appendix C: Setup Instructions

1. Install Python 3 and MySQL.
2. Create a virtual environment and install dependencies:
   ```bash
   pip install -r elearning/requirements.txt
   ```
3. Create the MySQL database `elearning_db`.
4. Run `init_db.py` or execute SQL scripts to create required tables.
5. Start the Flask app with `python elearning/app.py` or `python -m flask run`.

## Appendix D: Glossary

- LMS: Learning Management System
- SSL: Secure Sockets Layer
- API: Application Programming Interface
- GUI: Graphical User Interface
- KMeans: K-means clustering algorithm

---

*Note: This report is designed as a complete project report template. The final page count can be increased by adding diagrams, screenshots, detailed tables, expanded literature review, and extended appendices.*
