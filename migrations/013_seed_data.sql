-- Migration 013: Seed realistic dummy data
-- Run AFTER all 12 table migrations
-- Uses fixed UUIDs so foreign keys work and you can reference them in testing
--
-- UUID PREFIX GUIDE (all valid hex):
--   a0000000 = user (patients)     b0000000 = user (doctors)
--   c0000000 = user (nurse)        d0000000 = user (admin)
--   e0000000 = patients table      f0000000 = doctors table
--   10000000 = relationships       20000000 = sessions
--   30000000 = appointments        40000000 = waitlist
--   50000000 = cancellation_log    60000000 = notification_log
--   70000000 = doctor_ratings      80000000 = booking_audit_log
--
-- Password hash is bcrypt of "password123" for all users
-- $2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2

-- ═══════════════════════════════════════════════════════════════
-- USERS (10 users: 5 patients, 3 doctors, 1 nurse, 1 admin)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO users (id, email, phone, password_hash, full_name, role) VALUES
-- Patients
('a0000000-0000-0000-0000-000000000001', 'ravi.kumar@gmail.com',     '9876543210', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Ravi Kumar',       'patient'),
('a0000000-0000-0000-0000-000000000002', 'priya.sharma@gmail.com',   '9876543211', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Priya Sharma',     'patient'),
('a0000000-0000-0000-0000-000000000003', 'amit.patel@gmail.com',     '9876543212', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Amit Patel',       'patient'),
('a0000000-0000-0000-0000-000000000004', 'sunita.devi@gmail.com',    '9876543213', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Sunita Devi',      'patient'),
('a0000000-0000-0000-0000-000000000005', 'baby.ravi@gmail.com',      '9876543214', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Baby Ravi Kumar',  'patient'),
-- Doctors
('b0000000-0000-0000-0000-000000000001', 'dr.ananya@hospital.com',   '9800000001', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Ananya Reddy', 'doctor'),
('b0000000-0000-0000-0000-000000000002', 'dr.vikram@hospital.com',   '9800000002', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Vikram Singh', 'doctor'),
('b0000000-0000-0000-0000-000000000003', 'dr.meera@hospital.com',    '9800000003', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Meera Nair',   'doctor'),
-- Nurse
('c0000000-0000-0000-0000-000000000001', 'nurse.lakshmi@hospital.com','9800000010', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Lakshmi R',        'nurse'),
-- Admin
('d0000000-0000-0000-0000-000000000001', 'admin@hospital.com',       '9800000099', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Admin User',       'admin');


-- ═══════════════════════════════════════════════════════════════
-- PATIENTS (5 patients — varied ages for priority testing)
-- ═══════════════════════════════════════════════════════════════
-- Ravi Kumar:     age 70 → priority HIGH (senior)
-- Priya Sharma:   age 30 → priority NORMAL
-- Amit Patel:     age 35 → priority NORMAL
-- Sunita Devi:    age 82 → priority CRITICAL (elderly)
-- Baby Ravi:      age 1  → priority CRITICAL (infant) — Ravi's grandchild

INSERT INTO patients (id, user_id, abha_id, date_of_birth, gender, blood_group, emergency_contact_name, emergency_contact_phone, address, risk_score) VALUES
('e0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', '12345678901234', '1956-03-15', 'male',   'B+',  'Sunita Devi',   '9876543213', '42 MG Road, Hyderabad 500001',      0.00),
('e0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002', '12345678901235', '1996-07-22', 'female', 'O+',  'Amit Patel',    '9876543212', '15 Banjara Hills, Hyderabad 500034', 0.00),
('e0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000003', '12345678901236', '1991-11-08', 'male',   'A+',  'Priya Sharma',  '9876543211', '8 Jubilee Hills, Hyderabad 500033',  2.50),
('e0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000004', '12345678901237', '1944-01-20', 'female', 'AB-', 'Ravi Kumar',    '9876543210', '42 MG Road, Hyderabad 500001',      0.00),
('e0000000-0000-0000-0000-000000000005', 'a0000000-0000-0000-0000-000000000005', '12345678901238', '2025-06-10', 'male',   'B+',  'Ravi Kumar',    '9876543210', '42 MG Road, Hyderabad 500001',      0.00);


-- ═══════════════════════════════════════════════════════════════
-- DOCTORS (3 doctors — different specializations)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO doctors (id, user_id, specialization, qualification, license_number, consultation_fee, max_patients_per_slot) VALUES
('f0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'General Medicine',  'MBBS, MD',       'AP-MED-2015-0042', 500.00, 2),
('f0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Cardiology',        'MBBS, DM Cardio','AP-MED-2012-0108', 800.00, 2),
('f0000000-0000-0000-0000-000000000003', 'b0000000-0000-0000-0000-000000000003', 'Pediatrics',        'MBBS, DCH',      'AP-MED-2018-0271', 600.00, 2);


-- ═══════════════════════════════════════════════════════════════
-- PATIENT RELATIONSHIPS (multi-beneficiary)
-- ═══════════════════════════════════════════════════════════════
-- Every patient has a self-relationship (auto-approved)
-- Ravi books for Sunita (spouse) and Baby Ravi (grandchild)
-- Priya books for Amit (friend)

INSERT INTO patient_relationships (id, booker_patient_id, beneficiary_patient_id, relationship_type, is_approved, approved_at) VALUES
-- Self relationships (auto-approved)
('10000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'self',   true,  NOW()),
('10000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'self',   true,  NOW()),
('10000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'self',   true,  NOW()),
('10000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'self',   true,  NOW()),
('10000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000005', 'self',   true,  NOW()),
-- Ravi → Sunita (spouse, approved)
('10000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', 'spouse', true,  NOW()),
-- Ravi → Baby Ravi (grandchild = child type, approved)
('10000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'child',  true,  NOW()),
-- Priya → Amit (friend, approved)
('10000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000003', 'friend', true,  NOW()),
-- Amit → Priya (friend, PENDING — not yet approved, for testing)
('10000000-0000-0000-0000-000000000009', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 'friend', false, NULL);


-- ═══════════════════════════════════════════════════════════════
-- SESSIONS (6 sessions across 3 doctors, today + tomorrow)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO sessions (id, doctor_id, session_date, start_time, end_time, slot_duration_minutes, max_patients_per_slot, scheduling_type, total_slots, booked_count, status) VALUES
-- Dr. Ananya — General Medicine — today morning (16 slots, 5 booked)
('20000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE, '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 5, 'active'),
-- Dr. Ananya — General Medicine — today afternoon (12 slots, 0 booked, inactive until doctor activates)
('20000000-0000-0000-0000-000000000007', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE, '14:00', '17:00', 15, 2, 'TIME_SLOT', 12, 0, 'inactive'),
-- Dr. Ananya — General Medicine — tomorrow morning (16 slots, 0 booked)
('20000000-0000-0000-0000-000000000002', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE + 1, '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 0, 'active'),
-- Dr. Vikram — Cardiology — today morning (12 slots, 3 booked)
('20000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000002', CURRENT_DATE, '10:00', '13:00', 15, 2, 'TIME_SLOT', 12, 3, 'active'),
-- Dr. Vikram — Cardiology — today evening (8 slots, 0 booked)
('20000000-0000-0000-0000-000000000004', 'f0000000-0000-0000-0000-000000000002', CURRENT_DATE, '16:00', '18:00', 15, 2, 'FCFS', 8, 0, 'active'),
-- Dr. Meera — Pediatrics — today morning (16 slots, 2 booked)
('20000000-0000-0000-0000-000000000005', 'f0000000-0000-0000-0000-000000000003', CURRENT_DATE, '09:00', '13:00', 15, 2, 'PRIORITY_QUEUE', 16, 2, 'active'),
-- Dr. Meera — Pediatrics — cancelled session (for testing edge cases)
('20000000-0000-0000-0000-000000000006', 'f0000000-0000-0000-0000-000000000003', CURRENT_DATE, '14:00', '17:00', 15, 2, 'TIME_SLOT', 12, 0, 'cancelled');


-- ═══════════════════════════════════════════════════════════════
-- APPOINTMENTS (10 appointments — various statuses for testing)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO appointments (id, session_id, patient_id, booked_by_patient_id, slot_number, slot_position, priority_tier, visual_priority, is_emergency, status, checked_in_at, checked_in_by, completed_at, notes) VALUES
-- Dr. Ananya's session today — 5 appointments
-- Slot 1: Ravi (self-booked, checked in, HIGH priority from age 70)
('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'HIGH', 5, false, 'checked_in', NOW() - INTERVAL '30 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 1: Priya (overbook on same slot, booked, NORMAL age 30)
('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 1, 2, 'NORMAL', 5, false, 'booked', NULL, NULL, NULL, NULL),
-- Slot 2: Amit (self-booked, checked in, NORMAL, nurse set visual_priority=8)
('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 2, 1, 'NORMAL', 8, false, 'checked_in', NOW() - INTERVAL '20 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 3: Sunita (booked BY Ravi for her, CRITICAL from age 82)
('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000001', 3, 1, 'CRITICAL', 5, false, 'checked_in', NOW() - INTERVAL '15 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 4: Baby Ravi (booked BY Ravi, CRITICAL from age 1)
('30000000-0000-0000-0000-000000000005', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000001', 4, 1, 'CRITICAL', 5, false, 'booked', NULL, NULL, NULL, NULL),

-- Dr. Vikram's session today — 3 appointments
-- Slot 1: Ravi (self-booked, completed already)
('30000000-0000-0000-0000-000000000006', '20000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'HIGH', 5, false, 'completed', NOW() - INTERVAL '2 hours', 'c0000000-0000-0000-0000-000000000001', NOW() - INTERVAL '90 minutes', 'BP 140/90. Advised lifestyle changes. Follow up in 2 weeks.'),
-- Slot 2: Priya (self-booked, cancelled — for testing cancellation)
('30000000-0000-0000-0000-000000000007', '20000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 2, 1, 'NORMAL', 5, false, 'cancelled', NULL, NULL, NULL, NULL),
-- Slot 3: Amit (self-booked, booked status)
('30000000-0000-0000-0000-000000000008', '20000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 3, 1, 'NORMAL', 5, false, 'booked', NULL, NULL, NULL, NULL),

-- Dr. Meera's session today — 2 appointments (pediatrics)
-- Slot 1: Baby Ravi (booked BY Ravi, CRITICAL infant)
('30000000-0000-0000-0000-000000000009', '20000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'CRITICAL', 5, false, 'booked', NULL, NULL, NULL, NULL),
-- Slot 1: Amit (booked BY Priya as friend, overbook)
('30000000-0000-0000-0000-000000000010', '20000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 1, 2, 'NORMAL', 5, false, 'booked', NULL, NULL, NULL, NULL);


-- ═══════════════════════════════════════════════════════════════
-- WAITLIST (1 entry — Priya waiting for Dr. Vikram's slot)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO waitlist (id, session_id, patient_id, booked_by_patient_id, priority_tier, status) VALUES
('40000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'NORMAL', 'waiting');


-- ═══════════════════════════════════════════════════════════════
-- CANCELLATION LOG (1 entry — Priya cancelled Dr. Vikram appointment)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO cancellation_log (id, appointment_id, cancelled_by_patient_id, reason, risk_delta, hours_before_appointment) VALUES
('50000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000002', 'Had an urgent meeting, will reschedule', 0.25, 4.00);


-- ═══════════════════════════════════════════════════════════════
-- NOTIFICATION LOG (4 entries — booking confirmations + cancellation)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO notification_log (id, user_id, appointment_id, type, channel, status, content, sent_at) VALUES
('60000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'booking_confirmation', 'email', 'sent', 'Your appointment with Dr. Ananya Reddy is confirmed for today at 09:00 AM. Slot 1.', NOW() - INTERVAL '3 hours'),
('60000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 'booking_confirmation', 'email', 'sent', 'Your appointment with Dr. Ananya Reddy is confirmed for today at 09:00 AM. Slot 1 (shared).', NOW() - INTERVAL '2 hours'),
('60000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000007', 'cancellation', 'email', 'sent', 'Your appointment with Dr. Vikram Singh has been cancelled. Risk score updated.', NOW() - INTERVAL '1 hour'),
('60000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000004', 'reminder', 'email', 'pending', 'Reminder: Sunita Devi has an appointment with Dr. Ananya Reddy today at 09:30 AM.', NULL);


-- ═══════════════════════════════════════════════════════════════
-- DOCTOR RATINGS (1 entry — for Ravi's completed appointment with Dr. Vikram)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000002', 4, 'Dr. Vikram was very thorough with the checkup. Explained everything about my BP. Waiting time was reasonable.', 0.82);


-- ═══════════════════════════════════════════════════════════════
-- BOOKING AUDIT LOG (6 entries — trail of actions)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO booking_audit_log (id, action, appointment_id, performed_by_user_id, patient_id, metadata, ip_address) VALUES
-- Ravi booked for himself with Dr. Ananya
('80000000-0000-0000-0000-000000000001', 'book',     '30000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', '{"slot_number": 1, "slot_position": 1, "doctor": "Dr. Ananya Reddy"}', '192.168.1.10'),
-- Ravi booked for Sunita (beneficiary) with Dr. Ananya
('80000000-0000-0000-0000-000000000002', 'book',     '30000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', '{"slot_number": 3, "slot_position": 1, "doctor": "Dr. Ananya Reddy", "booked_for": "Sunita Devi (spouse)"}', '192.168.1.10'),
-- Ravi booked for Baby Ravi (beneficiary) with Dr. Ananya
('80000000-0000-0000-0000-000000000003', 'book',     '30000000-0000-0000-0000-000000000005', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', '{"slot_number": 4, "slot_position": 1, "doctor": "Dr. Ananya Reddy", "booked_for": "Baby Ravi Kumar (child)"}', '192.168.1.10'),
-- Nurse checked in Ravi
('80000000-0000-0000-0000-000000000004', 'check_in', '30000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', '{"visual_priority": 5}', '192.168.1.50'),
-- Priya cancelled her Dr. Vikram appointment
('80000000-0000-0000-0000-000000000005', 'cancel',   '30000000-0000-0000-0000-000000000007', 'a0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', '{"reason": "Had an urgent meeting", "risk_delta": 0.25, "hours_before": 4.0}', '192.168.1.20'),
-- Dr. Vikram completed Ravi's consultation
('80000000-0000-0000-0000-000000000006', 'complete', '30000000-0000-0000-0000-000000000006', 'b0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000001', '{"notes": "BP 140/90. Follow up in 2 weeks."}', '192.168.1.100');


-- ═══════════════════════════════════════════════════════════════
-- VERIFICATION QUERIES (run these to confirm data is correct)
-- ═══════════════════════════════════════════════════════════════
-- SELECT count(*) FROM users;              -- Expected: 10
-- SELECT count(*) FROM patients;           -- Expected: 5
-- SELECT count(*) FROM doctors;            -- Expected: 3
-- SELECT count(*) FROM patient_relationships; -- Expected: 9
-- SELECT count(*) FROM sessions;           -- Expected: 6
-- SELECT count(*) FROM appointments;       -- Expected: 10
-- SELECT count(*) FROM waitlist;           -- Expected: 1
-- SELECT count(*) FROM cancellation_log;   -- Expected: 1
-- SELECT count(*) FROM notification_log;   -- Expected: 4
-- SELECT count(*) FROM doctor_ratings;     -- Expected: 1
-- SELECT count(*) FROM booking_audit_log;  -- Expected: 6
--
-- Queue test (Dr. Ananya's session — who goes first?):
-- SELECT e.id, u.full_name, a.priority_tier, a.visual_priority, a.checked_in_at
-- FROM appointments a
-- JOIN patients e ON a.patient_id = e.id
-- JOIN users u ON e.user_id = u.id
-- WHERE a.session_id = '20000000-0000-0000-0000-000000000001'
--   AND a.status = 'checked_in'
-- ORDER BY
--     CASE a.priority_tier WHEN 'CRITICAL' THEN 3 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 1 END DESC,
--     a.visual_priority DESC,
--     a.created_at ASC;
-- Expected order: 1. Sunita (CRITICAL), 2. Ravi (HIGH), 3. Amit (NORMAL, visual=8)
