#!/bin/bash
# ═══════════════════════════════════════════════════════════
# DPMS v2 — Apply pending migrations (non-destructive)
# Usage: bash patch_db.sh
# ═══════════════════════════════════════════════════════════

DB_NAME="dpms_v2"
DB_USER="postgres"

echo "🏥 DPMS v2 — Patch Database (non-destructive)"
echo "═══════════════════════════════════════════════"
echo ""
echo "Applying migrations 014-016..."

# 014: Add inactive status to sessions
echo ""
echo "→ 014: Adding 'inactive' session status..."
psql -U $DB_USER -d $DB_NAME -f migrations/014_add_inactive_status_and_afternoon_session.sql 2>&1

# 014: Seed scheduling config
echo ""
echo "→ 014: Seeding scheduling config..."
psql -U $DB_USER -d $DB_NAME -f migrations/014_seed_scheduling_config.sql 2>&1

# 015: Refresh sessions to today
echo ""
echo "→ 015: Refreshing sessions to today..."
psql -U $DB_USER -d $DB_NAME -f migrations/015_refresh_sessions_to_today.sql 2>&1

# 016: Widen audit actions + add duration_minutes
echo ""
echo "→ 016: Widening audit constraints + adding duration column..."
psql -U $DB_USER -d $DB_NAME -f migrations/016_widen_audit_actions_and_add_duration.sql 2>&1

# 017: Widen notification_log constraints + ensure audit is widened
echo ""
echo "→ 017: Widening notification_log & audit constraints..."
psql -U $DB_USER -d $DB_NAME -f migrations/017_widen_notification_and_audit_constraints.sql 2>&1

echo ""
echo "✅ Patch complete! Restart FastAPI server to pick up changes."
