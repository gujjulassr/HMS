-- Migration 020: Seed additional doctor ratings for RAG testing
-- Requires: some appointments to be in 'completed' status
-- We'll update a few appointments to completed, then add ratings
--
-- UUID PREFIX: 70000000 = doctor_ratings

-- First, complete a few more appointments so we can rate them
UPDATE appointments SET status = 'completed', completed_at = NOW() - INTERVAL '1 day',
    notes = 'Routine checkup. All vitals normal.'
WHERE id = '30000000-0000-0000-0000-000000000003'; -- Amit with Dr. Ananya

UPDATE appointments SET status = 'completed', completed_at = NOW() - INTERVAL '2 days',
    notes = 'Follow-up for chronic condition. Medication adjusted.'
WHERE id = '30000000-0000-0000-0000-000000000004'; -- Sunita with Dr. Ananya

-- Now add ratings (70000000 prefix, starting from 002)

-- Amit rates Dr. Ananya — positive but mentions wait time
INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000001', 3,
'Dr. Ananya is knowledgeable but the wait time was almost 45 minutes. The clinic was crowded and the queue system felt disorganized. Once I got in, the consultation was good though.',
-0.15);

-- Sunita rates Dr. Ananya — very positive, mentions caring nature
INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'f0000000-0000-0000-0000-000000000001', 5,
'Dr. Ananya was extremely patient with me being elderly. She explained my medications in simple terms and made sure I understood everything. Very caring doctor. The staff was also helpful in getting me a wheelchair.',
0.95);

-- Additional ratings for Dr. Vikram (already has one from Ravi)
-- We need another completed appointment for Vikram. Let's use Amit's booked one.
UPDATE appointments SET status = 'completed', completed_at = NOW() - INTERVAL '3 hours',
    notes = 'ECG normal. Stress test recommended.'
WHERE id = '30000000-0000-0000-0000-000000000008'; -- Amit with Dr. Vikram

INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000004', '30000000-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000002', 5,
'Dr. Vikram is the best cardiologist I have visited. He spent a good 20 minutes explaining my ECG results and what the stress test will involve. Very thorough and professional. No rushing at all.',
0.92);

-- For Dr. Meera, we need a completed appointment
UPDATE appointments SET status = 'completed', completed_at = NOW() - INTERVAL '5 hours',
    notes = 'Baby wellness checkup. Growth on track. Vaccination schedule updated.'
WHERE id = '30000000-0000-0000-0000-000000000009'; -- Baby Ravi with Dr. Meera

INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000005', '30000000-0000-0000-0000-000000000009', 'e0000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000003', 4,
'Dr. Meera was gentle with my grandson. She has a great bedside manner with children. Only concern is the wait time was about 30 minutes and the waiting area doesn''t have enough space for families with young children.',
0.55);

-- One more for Dr. Meera from another patient
UPDATE appointments SET status = 'completed', completed_at = NOW() - INTERVAL '4 hours',
    notes = 'General pediatric consultation. Referred for allergy testing.'
WHERE id = '30000000-0000-0000-0000-000000000010'; -- Amit with Dr. Meera (booked by Priya)

INSERT INTO doctor_ratings (id, appointment_id, patient_id, doctor_id, rating, review, sentiment_score) VALUES
('70000000-0000-0000-0000-000000000006', '30000000-0000-0000-0000-000000000010', 'e0000000-0000-0000-0000-000000000003', 'f0000000-0000-0000-0000-000000000003', 4,
'Good consultation with Dr. Meera. She listened carefully and didn''t rush through the appointment. Referred me for allergy testing which was helpful. The clinic itself could use better signage — I got lost finding the room.',
0.65);

-- VERIFICATION
-- SELECT count(*) FROM doctor_ratings;  -- Expected: 6 total (1 original + 5 new)
-- SELECT doctor_id, count(*), avg(rating) FROM doctor_ratings GROUP BY doctor_id;
