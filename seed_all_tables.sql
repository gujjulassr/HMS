-- ═══════════════════════════════════════════════════════════════════════
-- HMS — Full Seed Data for All 12 Tables
-- ═══════════════════════════════════════════════════════════════════════
-- Run this AFTER all migrations. Cleans existing data first.
-- Uses CURRENT_DATE so sessions are always "today".
-- Password for ALL users: password123
--
-- UUID PREFIX GUIDE:
--   a0 = user (patients)     b0 = user (doctors)
--   c0 = user (nurses)       d0 = user (admin)
--   e0 = patients table      f0 = doctors table
--   10 = relationships       20 = sessions
--   30 = appointments        40 = waitlist
--   50 = cancellation_log    60 = notification_log
--   70 = doctor_ratings      80 = booking_audit_log
-- ═══════════════════════════════════════════════════════════════════════

-- ── Clean existing data (reverse FK order) ──
DELETE FROM booking_audit_log;
DELETE FROM doctor_ratings;
DELETE FROM notification_log;
DELETE FROM cancellation_log;
DELETE FROM waitlist;
DELETE FROM appointments;
DELETE FROM sessions;
DELETE FROM scheduling_config;
DELETE FROM patient_relationships;
DELETE FROM doctors;
DELETE FROM patients;
DELETE FROM users;

-- ═══════════════════════════════════════════════════════════════
-- 1. USERS (15 users: 8 patients, 4 doctors, 2 nurses, 1 admin)
-- ═══════════════════════════════════════════════════════════════
-- Password hash = bcrypt("password123")

INSERT INTO users (id, email, phone, password_hash, full_name, role) VALUES
-- Patients
('a0000000-0000-0000-0000-000000000001', 'ravi.kumar@gmail.com',       '9876543210', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Ravi Kumar',         'patient'),
('a0000000-0000-0000-0000-000000000002', 'priya.sharma@gmail.com',     '9876543211', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Priya Sharma',       'patient'),
('a0000000-0000-0000-0000-000000000003', 'amit.patel@gmail.com',       '9876543212', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Amit Patel',         'patient'),
('a0000000-0000-0000-0000-000000000004', 'sunita.devi@gmail.com',      '9876543213', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Sunita Devi',        'patient'),
('a0000000-0000-0000-0000-000000000005', 'baby.ravi@gmail.com',        '9876543214', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Baby Ravi Kumar',    'patient'),
('a0000000-0000-0000-0000-000000000006', 'deepak.reddy@gmail.com',     '9876543215', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Deepak Reddy',       'patient'),
('a0000000-0000-0000-0000-000000000007', 'nagarjuna.g@gmail.com',      '9876543216', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Nagarjuna G',        'patient'),
('a0000000-0000-0000-0000-000000000008', 'fatima.begum@gmail.com',     '9876543217', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Fatima Begum',       'patient'),
-- Doctors
('b0000000-0000-0000-0000-000000000001', 'dr.ananya@hospital.com',     '9800000001', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Ananya Reddy',   'doctor'),
('b0000000-0000-0000-0000-000000000002', 'dr.vikram@hospital.com',     '9800000002', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Vikram Singh',   'doctor'),
('b0000000-0000-0000-0000-000000000003', 'dr.meera@hospital.com',      '9800000003', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Meera Nair',     'doctor'),
('b0000000-0000-0000-0000-000000000004', 'dr.rajesh@hospital.com',     '9800000004', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Dr. Rajesh Khanna',  'doctor'),
-- Nurses
('c0000000-0000-0000-0000-000000000001', 'nurse.lakshmi@hospital.com', '9800000010', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Lakshmi R',          'nurse'),
('c0000000-0000-0000-0000-000000000002', 'nurse.suresh@hospital.com',  '9800000011', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Suresh M',           'nurse'),
-- Admin
('d0000000-0000-0000-0000-000000000001', 'admin@hospital.com',         '9800000099', '$2b$12$0LgNsPLqex6E/0KPc0RgquVMoEOEcikMQn90cWDCxIZvlrkfQxWf2', 'Admin User',         'admin');


-- ═══════════════════════════════════════════════════════════════
-- 2. PATIENTS (8 patients — varied ages for priority testing)
-- ═══════════════════════════════════════════════════════════════
-- Priority tiers from age:
--   < 5 or >= 75 → CRITICAL
--   5-17 or 60-74 → HIGH
--   18-59 → NORMAL

INSERT INTO patients (id, user_id, abha_id, date_of_birth, gender, blood_group, emergency_contact_name, emergency_contact_phone, address, risk_score) VALUES
('e0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', '12345678901234', '1956-03-15', 'male',   'B+',  'Sunita Devi',     '9876543213', '42 MG Road, Hyderabad 500001',        0.00),
('e0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002', '12345678901235', '1996-07-22', 'female', 'O+',  'Amit Patel',      '9876543212', '15 Banjara Hills, Hyderabad 500034',   0.00),
('e0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000003', '12345678901236', '1991-11-08', 'male',   'A+',  'Priya Sharma',    '9876543211', '8 Jubilee Hills, Hyderabad 500033',    2.50),
('e0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000004', '12345678901237', '1944-01-20', 'female', 'AB-', 'Ravi Kumar',      '9876543210', '42 MG Road, Hyderabad 500001',        0.00),
('e0000000-0000-0000-0000-000000000005', 'a0000000-0000-0000-0000-000000000005', '12345678901238', '2025-06-10', 'male',   'B+',  'Ravi Kumar',      '9876543210', '42 MG Road, Hyderabad 500001',        0.00),
('e0000000-0000-0000-0000-000000000006', 'a0000000-0000-0000-0000-000000000006', '12345678901239', '1988-09-03', 'male',   'O-',  'Nagarjuna G',     '9876543216', '22 Kukatpally, Hyderabad 500072',     0.00),
('e0000000-0000-0000-0000-000000000007', 'a0000000-0000-0000-0000-000000000007', '12345678901240', '1993-04-18', 'male',   'A-',  'Deepak Reddy',    '9876543215', '10 Madhapur, Hyderabad 500081',       0.00),
('e0000000-0000-0000-0000-000000000008', 'a0000000-0000-0000-0000-000000000008', '12345678901241', '1950-12-05', 'female', 'B-',  'Deepak Reddy',    '9876543215', '5 Secunderabad, Hyderabad 500003',    0.00);


-- ═══════════════════════════════════════════════════════════════
-- 3. DOCTORS (4 doctors — different specializations)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO doctors (id, user_id, specialization, qualification, license_number, consultation_fee, max_patients_per_slot) VALUES
('f0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'General Medicine',  'MBBS, MD',         'AP-MED-2015-0042', 500.00,  2),
('f0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Cardiology',        'MBBS, DM Cardio',  'AP-MED-2012-0108', 800.00,  2),
('f0000000-0000-0000-0000-000000000003', 'b0000000-0000-0000-0000-000000000003', 'Pediatrics',        'MBBS, DCH',        'AP-MED-2018-0271', 600.00,  2),
('f0000000-0000-0000-0000-000000000004', 'b0000000-0000-0000-0000-000000000004', 'Orthopedics',       'MBBS, MS Ortho',   'AP-MED-2010-0315', 700.00,  2);


-- ═══════════════════════════════════════════════════════════════
-- 4. PATIENT RELATIONSHIPS (multi-beneficiary)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO patient_relationships (id, booker_patient_id, beneficiary_patient_id, relationship_type, is_approved, approved_at) VALUES
-- Self relationships (every patient, auto-approved)
('10000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000005', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000006', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000007', 'self',    true,  NOW()),
('10000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000008', 'self',    true,  NOW()),
-- Ravi → Sunita (spouse)
('10000000-0000-0000-0000-000000000009', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', 'spouse',  true,  NOW()),
-- Ravi → Baby Ravi (child/grandchild)
('10000000-0000-0000-0000-000000000010', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'child',   true,  NOW()),
-- Priya → Amit (friend, approved)
('10000000-0000-0000-0000-000000000011', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000003', 'friend',  true,  NOW()),
-- Deepak → Nagarjuna (sibling, approved)
('10000000-0000-0000-0000-000000000012', 'e0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000007', 'sibling', true,  NOW()),
-- Deepak → Fatima (parent, approved)
('10000000-0000-0000-0000-000000000013', 'e0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000008', 'parent',  true,  NOW()),
-- Amit → Priya (friend, PENDING — for testing approval flow)
('10000000-0000-0000-0000-000000000014', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 'friend',  false, NULL);


-- ═══════════════════════════════════════════════════════════════
-- 5. SCHEDULING CONFIG (system-wide settings)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO scheduling_config (config_key, config_value, description) VALUES
('max_bookings_per_day',    '5',    'Maximum bookings a single booker can make per day'),
('max_bookings_per_week',   '15',   'Maximum bookings a single booker can make per week'),
('cancel_cooldown_hours',   '2',    'Hours a booker must wait between cancellations'),
('risk_score_threshold',    '7.0',  'Risk score at or above which a booker is blocked'),
('risk_decay_per_day',      '0.1',  'Amount risk score decreases per day via nightly cron');


-- ═══════════════════════════════════════════════════════════════
-- 6. SESSIONS (10 sessions — 4 doctors, today + tomorrow)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO sessions (id, doctor_id, session_date, start_time, end_time, slot_duration_minutes, max_patients_per_slot, scheduling_type, total_slots, booked_count, status) VALUES
-- Dr. Ananya — General Medicine
('20000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE,     '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 6, 'active'),      -- today morning
('20000000-0000-0000-0000-000000000002', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE,     '14:00', '17:00', 15, 2, 'TIME_SLOT', 12, 0, 'active'),      -- today afternoon
('20000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000001', CURRENT_DATE + 1, '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 0, 'active'),      -- tomorrow morning
-- Dr. Vikram — Cardiology
('20000000-0000-0000-0000-000000000004', 'f0000000-0000-0000-0000-000000000002', CURRENT_DATE,     '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 4, 'active'),      -- today morning
('20000000-0000-0000-0000-000000000005', 'f0000000-0000-0000-0000-000000000002', CURRENT_DATE,     '14:00', '17:00', 15, 2, 'TIME_SLOT', 12, 0, 'active'),      -- today afternoon
('20000000-0000-0000-0000-000000000006', 'f0000000-0000-0000-0000-000000000002', CURRENT_DATE + 1, '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 0, 'active'),      -- tomorrow morning
-- Dr. Meera — Pediatrics
('20000000-0000-0000-0000-000000000007', 'f0000000-0000-0000-0000-000000000003', CURRENT_DATE,     '09:00', '13:00', 15, 2, 'PRIORITY_QUEUE', 16, 3, 'active'), -- today morning
('20000000-0000-0000-0000-000000000008', 'f0000000-0000-0000-0000-000000000003', CURRENT_DATE,     '14:00', '17:00', 15, 2, 'TIME_SLOT', 12, 0, 'cancelled'),   -- today afternoon (cancelled)
-- Dr. Rajesh — Orthopedics
('20000000-0000-0000-0000-000000000009', 'f0000000-0000-0000-0000-000000000004', CURRENT_DATE,     '10:00', '13:00', 15, 2, 'TIME_SLOT', 12, 2, 'active'),      -- today morning
('20000000-0000-0000-0000-000000000010', 'f0000000-0000-0000-0000-000000000004', CURRENT_DATE + 1, '09:00', '13:00', 15, 2, 'TIME_SLOT', 16, 0, 'active');      -- tomorrow morning


-- ═══════════════════════════════════════════════════════════════
-- 7. APPOINTMENTS (15 appointments — various statuses)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO appointments (id, session_id, patient_id, booked_by_patient_id, slot_number, slot_position, priority_tier, visual_priority, is_emergency, status, checked_in_at, checked_in_by, completed_at, notes) VALUES

-- ── Dr. Ananya's morning session — 6 appointments ──
-- Slot 1: Ravi (self, HIGH age 70, checked in)
('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'HIGH',     5, false, 'checked_in',  NOW() - INTERVAL '45 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 1: Priya (overbook, NORMAL age 30, booked)
('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 1, 2, 'NORMAL',   5, false, 'booked',      NULL, NULL, NULL, NULL),
-- Slot 2: Amit (self, NORMAL, nurse set visual_priority=8, checked in)
('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 2, 1, 'NORMAL',   8, false, 'checked_in',  NOW() - INTERVAL '30 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 3: Sunita (booked BY Ravi, CRITICAL age 82, checked in)
('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000001', 3, 1, 'CRITICAL', 5, false, 'checked_in',  NOW() - INTERVAL '20 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 4: Baby Ravi (booked BY Ravi, CRITICAL age 1, booked)
('30000000-0000-0000-0000-000000000005', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000001', 4, 1, 'CRITICAL', 5, false, 'booked',      NULL, NULL, NULL, NULL),
-- Slot 5: Fatima (booked BY Deepak, HIGH age 75, booked)
('30000000-0000-0000-0000-000000000006', '20000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000006', 5, 1, 'HIGH',     5, false, 'booked',      NULL, NULL, NULL, NULL),

-- ── Dr. Vikram's morning session — 4 appointments ──
-- Slot 1: Ravi (self, completed)
('30000000-0000-0000-0000-000000000007', '20000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'HIGH',     5, false, 'completed',   NOW() - INTERVAL '3 hours', 'c0000000-0000-0000-0000-000000000001', NOW() - INTERVAL '150 minutes', 'BP 140/90. Advised lifestyle changes. Follow up in 2 weeks.'),
-- Slot 2: Priya (self, cancelled)
('30000000-0000-0000-0000-000000000008', '20000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 2, 1, 'NORMAL',   5, false, 'cancelled',   NULL, NULL, NULL, NULL),
-- Slot 3: Nagarjuna (booked BY Deepak, NORMAL, checked in)
('30000000-0000-0000-0000-000000000009', '20000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000006', 3, 1, 'NORMAL',   5, false, 'checked_in',  NOW() - INTERVAL '15 minutes', 'c0000000-0000-0000-0000-000000000001', NULL, NULL),
-- Slot 4: Deepak (self, booked)
('30000000-0000-0000-0000-000000000010', '20000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000006', 4, 1, 'NORMAL',   5, false, 'booked',      NULL, NULL, NULL, NULL),

-- ── Dr. Meera's morning session — 3 appointments (pediatrics) ──
-- Slot 1: Baby Ravi (booked BY Ravi, CRITICAL infant)
('30000000-0000-0000-0000-000000000011', '20000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000001', 1, 1, 'CRITICAL', 5, false, 'booked',      NULL, NULL, NULL, NULL),
-- Slot 1: Amit (booked BY Priya as friend, overbook)
('30000000-0000-0000-0000-000000000012', '20000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000002', 1, 2, 'NORMAL',   5, false, 'booked',      NULL, NULL, NULL, NULL),
-- Emergency: Deepak (walk-in emergency, slot 0, auto checked-in)
('30000000-0000-0000-0000-000000000013', '20000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000006', 0, 1, 'CRITICAL', 10, true, 'checked_in', NOW() - INTERVAL '10 minutes', NULL, NULL, 'Severe abdominal pain — emergency walk-in'),

-- ── Dr. Rajesh's morning session — 2 appointments (orthopedics) ──
-- Slot 1: Fatima (booked BY Deepak, HIGH age 75)
('30000000-0000-0000-0000-000000000014', '20000000-0000-0000-0000-000000000009', 'e0000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000006', 1, 1, 'HIGH',     5, false, 'booked',      NULL, NULL, NULL, NULL),
-- Slot 2: Nagarjuna (self, no_show)
('30000000-0000-0000-0000-000000000015', '20000000-0000-0000-0000-000000000009', 'e0000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000007', 2, 1, 'NORMAL',   5, false, 'no_show',     NULL, NULL, NULL, NULL);


-- ═══════════════════════════════════════════════════════════════
-- 8. WAITLIST (2 entries)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO waitlist (id, session_id, patient_id, booked_by_patient_id, priority_tier, status) VALUES
-- Priya waiting for Dr. Vikram (after her cancellation)
('40000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'NORMAL',   'waiting'),
-- Fatima waiting for Dr. Meera (pediatrics full for slot 1)
('40000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000006', 'HIGH',     'waiting');


-- ═══════════════════════════════════════════════════════════════
-- 9. CANCELLATION LOG (2 entries)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO cancellation_log (id, appointment_id, cancelled_by_patient_id, reason, risk_delta, hours_before_appointment) VALUES
('50000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000002', 'Had an urgent meeting, will reschedule',         0.25, 4.00),
('50000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000015', 'e0000000-0000-0000-0000-000000000007', 'Patient did not show up — marked by nurse',      2.00, 0.50);


-- ═══════════════════════════════════════════════════════════════
-- 10. NOTIFICATION LOG (8 entries — various types and statuses)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO notification_log (id, user_id, appointment_id, type, channel, status, content, error_message, sent_at) VALUES
-- Booking confirmations (sent)
('60000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'booking_confirmation', 'email', 'sent',    'Your appointment with Dr. Ananya Reddy is confirmed for today at 09:00 AM. Slot 1.',         NULL, NOW() - INTERVAL '4 hours'),
('60000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 'booking_confirmation', 'email', 'sent',    'Your appointment with Dr. Ananya Reddy is confirmed for today at 09:00 AM. Slot 1 (shared).', NULL, NOW() - INTERVAL '3 hours'),
('60000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000006', '30000000-0000-0000-0000-000000000009', 'booking_confirmation', 'email', 'sent',    'Nagarjuna G appointment with Dr. Vikram Singh confirmed for today. Slot 3.',                   NULL, NOW() - INTERVAL '2 hours'),
-- Cancellation (sent)
('60000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000008', 'cancellation',         'email', 'sent',    'Your appointment with Dr. Vikram Singh has been cancelled. Risk score updated.',               NULL, NOW() - INTERVAL '1 hour'),
-- Reminder (pending — not yet sent)
('60000000-0000-0000-0000-000000000005', 'a0000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000004', 'reminder',             'email', 'pending', 'Reminder: Sunita Devi has an appointment with Dr. Ananya Reddy today at 09:30 AM.',            NULL, NULL),
-- No-show notification (sent)
('60000000-0000-0000-0000-000000000006', 'a0000000-0000-0000-0000-000000000007', '30000000-0000-0000-0000-000000000015', 'no_show',              'email', 'sent',    'You missed your appointment with Dr. Rajesh Khanna. Risk score has been updated.',             NULL, NOW() - INTERVAL '30 minutes'),
-- Emergency booking (sent)
('60000000-0000-0000-0000-000000000007', 'a0000000-0000-0000-0000-000000000006', '30000000-0000-0000-0000-000000000013', 'EMERGENCY_BOOKED',     'email', 'sent',    'Emergency appointment created for Deepak Reddy with Dr. Meera Nair (Pediatrics).',             NULL, NOW() - INTERVAL '10 minutes'),
-- Failed notification (for testing error handling)
('60000000-0000-0000-0000-000000000008', 'a0000000-0000-0000-0000-000000000008', '30000000-0000-0000-0000-000000000014', 'booking_confirmation', 'email', 'failed',  'Your appointment with Dr. Rajesh Khanna is confirmed for today.',                               'SMTP connection timeout after 30s', NULL);


-- ═══════════════════════════════════════════════════════════════
-- 11. DOCTOR RATINGS (4 entries — for completed/past appointments)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000002', 4, 'Dr. Vikram was very thorough with the checkup. Explained everything about my BP. Waiting time was reasonable.',                          0.82),
('70000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000001', 5, 'Dr. Ananya is the best! Very patient and caring. She took time to answer all my questions.',                                          0.95),
('70000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000002', 'f0000000-0000-0000-0000-000000000002', 2, 'Had to wait over an hour past my slot time. Doctor was good but the wait was unacceptable.',                                         -0.45),
('70000000-0000-0000-0000-000000000004', '30000000-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000006', 'f0000000-0000-0000-0000-000000000003', 5, 'Dr. Meera was fantastic with my son. Very gentle and explained everything to us parents. Highly recommended for kids!',              0.97);


-- ═══════════════════════════════════════════════════════════════
-- 12. BOOKING AUDIT LOG (10 entries — trail of all actions)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO booking_audit_log (id, action, appointment_id, performed_by_user_id, patient_id, metadata, ip_address) VALUES
-- Ravi booked for self with Dr. Ananya
('80000000-0000-0000-0000-000000000001', 'book',      '30000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', '{"slot_number": 1, "slot_position": 1, "doctor": "Dr. Ananya Reddy"}',                       '192.168.1.10'),
-- Ravi booked for Sunita with Dr. Ananya
('80000000-0000-0000-0000-000000000002', 'book',      '30000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000004', '{"slot_number": 3, "slot_position": 1, "booked_for": "Sunita Devi (spouse)"}',                '192.168.1.10'),
-- Ravi booked for Baby Ravi with Dr. Ananya
('80000000-0000-0000-0000-000000000003', 'book',      '30000000-0000-0000-0000-000000000005', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', '{"slot_number": 4, "slot_position": 1, "booked_for": "Baby Ravi Kumar (child)"}',             '192.168.1.10'),
-- Nurse checked in Ravi
('80000000-0000-0000-0000-000000000004', 'check_in',  '30000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', '{"visual_priority": 5}',                                                                     '192.168.1.50'),
-- Priya cancelled Dr. Vikram appointment
('80000000-0000-0000-0000-000000000005', 'cancel',    '30000000-0000-0000-0000-000000000008', 'a0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', '{"reason": "Had an urgent meeting", "risk_delta": 0.25, "hours_before": 4.0}',                '192.168.1.20'),
-- Dr. Vikram completed Ravi's consultation
('80000000-0000-0000-0000-000000000006', 'complete',  '30000000-0000-0000-0000-000000000007', 'b0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000001', '{"notes": "BP 140/90. Follow up in 2 weeks."}',                                              '192.168.1.100'),
-- Deepak booked Nagarjuna with Dr. Vikram
('80000000-0000-0000-0000-000000000007', 'book',      '30000000-0000-0000-0000-000000000009', 'a0000000-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000007', '{"slot_number": 3, "slot_position": 1, "booked_for": "Nagarjuna G (sibling)"}',               '192.168.1.30'),
-- Emergency booking for Deepak
('80000000-0000-0000-0000-000000000008', 'book',      '30000000-0000-0000-0000-000000000013', 'c0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000006', '{"is_emergency": true, "reason": "Severe abdominal pain"}',                                   '192.168.1.50'),
-- Nagarjuna marked no-show by nurse
('80000000-0000-0000-0000-000000000009', 'no_show',   '30000000-0000-0000-0000-000000000015', 'c0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000007', '{"risk_delta": 2.0}',                                                                        '192.168.1.50'),
-- Priya added to waitlist for Dr. Vikram
('80000000-0000-0000-0000-000000000010', 'WAITLISTED','30000000-0000-0000-0000-000000000008', 'a0000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', '{"session": "Dr. Vikram Cardiology", "priority": "NORMAL"}',                                  '192.168.1.20');


-- ═══════════════════════════════════════════════════════════════
-- VERIFICATION QUERIES (uncomment and run to check)
-- ═══════════════════════════════════════════════════════════════
-- SELECT 'users' AS tbl,              count(*) FROM users;               -- 15
-- SELECT 'patients' AS tbl,           count(*) FROM patients;            -- 8
-- SELECT 'doctors' AS tbl,            count(*) FROM doctors;             -- 4
-- SELECT 'patient_relationships',     count(*) FROM patient_relationships; -- 14
-- SELECT 'scheduling_config',         count(*) FROM scheduling_config;   -- 5
-- SELECT 'sessions' AS tbl,           count(*) FROM sessions;            -- 10
-- SELECT 'appointments' AS tbl,       count(*) FROM appointments;        -- 15
-- SELECT 'waitlist' AS tbl,           count(*) FROM waitlist;            -- 2
-- SELECT 'cancellation_log' AS tbl,   count(*) FROM cancellation_log;    -- 2
-- SELECT 'notification_log' AS tbl,   count(*) FROM notification_log;    -- 8
-- SELECT 'doctor_ratings' AS tbl,     count(*) FROM doctor_ratings;      -- 4
-- SELECT 'booking_audit_log' AS tbl,  count(*) FROM booking_audit_log;   -- 10
