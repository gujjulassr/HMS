#!/bin/bash
# ═══════════════════════════════════════════════════════════
# DPMS v2 — Run all migrations + seed data
# Usage: bash run_migrations.sh
# ═══════════════════════════════════════════════════════════

DB_NAME="dpms_v2"
DB_USER="postgres"

echo "🏥 DPMS v2 — Database Migration Script"
echo "═══════════════════════════════════════"

# Step 1: Kill active connections and drop database
echo ""
echo "⚠️  This will DROP and recreate the database. Press Ctrl+C to cancel."
echo "    Continuing in 3 seconds..."
sleep 3

echo ""
echo "→ Killing active connections to $DB_NAME..."
psql -U $DB_USER -d postgres -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();
" -q 2>/dev/null

echo "→ Dropping database $DB_NAME (if exists)..."
dropdb -U $DB_USER --if-exists $DB_NAME

echo "→ Creating fresh database $DB_NAME..."
createdb -U $DB_USER $DB_NAME

# Step 2: Run all 12 table migrations in order
echo ""
echo "→ Running table migrations (001-012)..."

for i in $(seq -w 1 12); do
    FILE=$(ls migrations/0${i}_*.sql 2>/dev/null)
    if [ -f "$FILE" ]; then
        psql -U $DB_USER -d $DB_NAME -f "$FILE" -q 2>&1 | grep -i error
        if [ $? -ne 0 ]; then
            echo "   ✓ $FILE"
        fi
    else
        echo "   ✗ Migration $i not found!"
    fi
done

# Step 3: Run seed data
echo ""
echo "→ Seeding test data..."
psql -U $DB_USER -d $DB_NAME -f migrations/013_seed_data.sql -q 2>&1 | grep -i error
if [ $? -ne 0 ]; then
    echo "   ✓ Seed data loaded"
fi

# Step 4: Run post-seed migrations (014-016)
echo ""
echo "→ Running post-seed migrations (014-016)..."

# 014: Add inactive status to sessions + seed scheduling config
psql -U $DB_USER -d $DB_NAME -f migrations/014_add_inactive_status_and_afternoon_session.sql -q 2>&1 | grep -i error
if [ $? -ne 0 ]; then
    echo "   ✓ 014_add_inactive_status_and_afternoon_session.sql"
fi

psql -U $DB_USER -d $DB_NAME -f migrations/014_seed_scheduling_config.sql -q 2>&1 | grep -i error
if [ $? -ne 0 ]; then
    echo "   ✓ 014_seed_scheduling_config.sql"
fi

# 015: Refresh sessions to today
psql -U $DB_USER -d $DB_NAME -f migrations/015_refresh_sessions_to_today.sql -q 2>&1 | grep -i error
if [ $? -ne 0 ]; then
    echo "   ✓ 015_refresh_sessions_to_today.sql"
fi

# 016: Widen audit actions + add duration_minutes
psql -U $DB_USER -d $DB_NAME -f migrations/016_widen_audit_actions_and_add_duration.sql -q 2>&1 | grep -i error
if [ $? -ne 0 ]; then
    echo "   ✓ 016_widen_audit_actions_and_add_duration.sql"
fi

# Step 5: Verify
echo ""
echo "→ Verifying tables..."
echo ""
psql -U $DB_USER -d $DB_NAME -c "\dt"

echo ""
echo "→ Row counts:"
psql -U $DB_USER -d $DB_NAME -c "
SELECT 'users' AS table_name, count(*) FROM users
UNION ALL SELECT 'patients', count(*) FROM patients
UNION ALL SELECT 'doctors', count(*) FROM doctors
UNION ALL SELECT 'patient_relationships', count(*) FROM patient_relationships
UNION ALL SELECT 'sessions', count(*) FROM sessions
UNION ALL SELECT 'scheduling_config', count(*) FROM scheduling_config
UNION ALL SELECT 'appointments', count(*) FROM appointments
UNION ALL SELECT 'waitlist', count(*) FROM waitlist
UNION ALL SELECT 'cancellation_log', count(*) FROM cancellation_log
UNION ALL SELECT 'notification_log', count(*) FROM notification_log
UNION ALL SELECT 'doctor_ratings', count(*) FROM doctor_ratings
UNION ALL SELECT 'booking_audit_log', count(*) FROM booking_audit_log
ORDER BY table_name;
"

echo ""
echo "✅ Done! All migrations applied and data seeded."
echo ""
echo "Test credentials:"
echo "  Email:    ravi.kumar@gmail.com"
echo "  Password: password123"
echo "  (All 10 seed users have the same password)"
echo ""
echo "UUID prefix guide:"
echo "  a0=users(patients) b0=users(doctors) c0=nurse d0=admin"
echo "  e0=patients f0=doctors 10=relationships 20=sessions"
echo "  30=appointments 40=waitlist 50=cancellation 60=notification"
echo "  70=ratings 80=audit"
