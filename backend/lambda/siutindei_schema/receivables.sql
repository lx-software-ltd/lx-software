-- Apply in the siutindei Aurora database.
-- The lxsoftware admin stack copies this file to
-- backend/lambda/siutindei_schema/receivables.sql and applies it through the
-- RDS Data API when SiutindeiClusterArn is set. Keep the two copies identical
-- (enforced by backend/lambda/siutindei_schema/test_sql_split.py).
-- Executive Board T4: listing receivables (§5.4) and read-only views (§5.7).
-- AdminApiFn reaches these only through the RDS Data API (parameterised
-- ExecuteStatement with typeHint UUID/DATE/DECIMAL). Writes are limited to
-- invoices, payments, listing_plans, and listing_subscriptions.status.
--
-- Validated against siutindei Alembic head 0029_add_api_keys
-- (backend/db/alembic/versions/0029_add_api_keys.py, repo commit 6ad5ce6b):
--   activities(id, org_id, category_id)        activity_locations(activity_id, location_id)
--   activity_pricing(activity_id)              activity_schedule(activity_id)
--   locations(id, org_id, area_id, lat, lng)   geographic_areas(id, name)
--   activity_categories(id, name)              organizations(id, name, media_urls text[],
--                                                            created_at, updated_at)
-- Re-check those columns when the product's Alembic head moves.
--
-- TODO (product repo): nothing writes listing_events_daily yet. The product
-- needs a daily aggregation job (searches, listing views, CTA taps, leads,
-- bookings per location) before v_funnel_daily returns rows. Track this in
-- the siutindei repo; the board's product_funnel tool is read-only.

BEGIN;

CREATE TABLE IF NOT EXISTS listing_plans (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    price_hkd       numeric(12, 2) NOT NULL CHECK (price_hkd >= 0),
    billing_period  text NOT NULL CHECK (billing_period IN ('monthly', 'annual')),
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS listing_subscriptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    store_id        uuid,
    plan_id         uuid REFERENCES listing_plans (id),
    starts_on       date NOT NULL,
    renews_on       date,
    status          text NOT NULL CHECK (status IN ('trial', 'active', 'past_due', 'cancelled')),
    payer_contact   text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id uuid REFERENCES listing_subscriptions (id),
    number          text NOT NULL UNIQUE,
    issued_on       date,
    due_on          date,
    amount_hkd      numeric(12, 2) NOT NULL CHECK (amount_hkd >= 0),
    status          text NOT NULL CHECK (status IN ('draft', 'sent', 'paid', 'overdue', 'void')),
    fps_reference   text UNIQUE,
    pdf_key         text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id      uuid REFERENCES invoices (id),
    received_on     date NOT NULL,
    amount_hkd      numeric(12, 2) NOT NULL,
    payer_name      text,
    bank_reference  text,
    source          text NOT NULL CHECK (source IN ('alert_email', 'statement', 'manual')),
    matched_by      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS invoices_status_due_idx ON invoices (status, due_on);
CREATE INDEX IF NOT EXISTS payments_invoice_idx ON payments (invoice_id);

-- §5.7 views, aligned to the live siutindei Alembic schema
-- (organizations, activities, activity_locations, locations,
-- geographic_areas, activity_categories, activity_pricing,
-- activity_schedule, organizations.media_urls). The product has no
-- stores table and no funnel events yet: locations stand in for venues,
-- and listing_events_daily is created here for the product to fill later.

CREATE TABLE IF NOT EXISTS listing_events_daily (
    day                 date NOT NULL,
    location_id         uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    searches            integer NOT NULL DEFAULT 0,
    listing_views       integer NOT NULL DEFAULT 0,
    cta_taps            integer NOT NULL DEFAULT 0,
    leads_relayed       integer NOT NULL DEFAULT 0,
    bookings_confirmed  integer NOT NULL DEFAULT 0,
    PRIMARY KEY (day, location_id)
);

-- Completeness is scored once per activity (photos, price, schedule, any
-- geocoded venue) and then averaged per district × category. Scoring inside
-- the grouped join would weight an activity once per venue row.
CREATE OR REPLACE VIEW v_catalog_health AS
WITH activity_completeness AS (
    SELECT
        a.id AS activity_id,
        (
            (CASE WHEN COALESCE(cardinality(o.media_urls), 0) > 0 THEN 1 ELSE 0 END)
            + (CASE WHEN EXISTS (
                SELECT 1 FROM activity_pricing p WHERE p.activity_id = a.id
            ) THEN 1 ELSE 0 END)
            + (CASE WHEN EXISTS (
                SELECT 1 FROM activity_schedule s WHERE s.activity_id = a.id
            ) THEN 1 ELSE 0 END)
            + (CASE WHEN EXISTS (
                SELECT 1
                FROM activity_locations al
                JOIN locations l ON l.id = al.location_id
                WHERE al.activity_id = a.id AND l.lat IS NOT NULL AND l.lng IS NOT NULL
            ) THEN 1 ELSE 0 END)
        ) / 4.0 AS completeness
    FROM activities a
    JOIN organizations o ON o.id = a.org_id
),
placed AS (
    SELECT
        a.id AS activity_id,
        a.org_id,
        a.category_id,
        l.id AS location_id,
        COALESCE(ga.name, 'unknown') AS district,
        ROW_NUMBER() OVER (PARTITION BY a.id, COALESCE(ga.name, 'unknown') ORDER BY l.id) AS venue_rank
    FROM activities a
    LEFT JOIN activity_locations al ON al.activity_id = a.id
    LEFT JOIN locations l ON l.id = al.location_id
    LEFT JOIN geographic_areas ga ON ga.id = l.area_id
)
SELECT
    p.district,
    COALESCE(c.name, 'unknown') AS category,
    COUNT(DISTINCT p.activity_id)::int AS activities,
    COUNT(DISTINCT p.org_id)::int AS providers,
    COUNT(DISTINCT p.location_id)::int AS stores,
    ROUND(
        SUM(ac.completeness) FILTER (WHERE p.venue_rank = 1)
        / COUNT(DISTINCT p.activity_id),
        2
    ) AS completeness
FROM placed p
JOIN activity_completeness ac ON ac.activity_id = p.activity_id
LEFT JOIN activity_categories c ON c.id = p.category_id
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_funnel_daily AS
SELECT
    d.day,
    COALESCE(ga.name, 'all') AS district,
    SUM(d.searches)::int AS searches,
    SUM(d.listing_views)::int AS listing_views,
    SUM(d.cta_taps)::int AS cta_taps,
    SUM(d.leads_relayed)::int AS leads_relayed,
    SUM(d.bookings_confirmed)::int AS bookings_confirmed
FROM listing_events_daily d
LEFT JOIN locations l ON l.id = d.location_id
LEFT JOIN geographic_areas ga ON ga.id = l.area_id
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_provider_pipeline AS
SELECT
    o.id AS organization_id,
    o.name AS organization_name,
    o.created_at::date AS signed_up_on,
    CASE
        WHEN EXISTS (SELECT 1 FROM activities a WHERE a.org_id = o.id) THEN 'listed'
        WHEN COALESCE(cardinality(o.media_urls), 0) > 0 THEN 'profile'
        ELSE 'signed_up'
    END AS onboarding_step,
    (CURRENT_DATE - o.updated_at::date) AS days_since_last_edit,
    ls.status AS subscription_status
FROM organizations o
LEFT JOIN listing_subscriptions ls
    ON ls.organization_id = o.id
    AND ls.status IN ('trial', 'active', 'past_due');

-- Least-privilege group role for the Data API user AdminApiFn connects as.
-- Idempotent: CREATE ROLE has no IF NOT EXISTS, so check pg_roles first.
-- After applying, attach it to the login the DB secret names:
--     GRANT board_api TO <secret username>;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'board_api') THEN
        CREATE ROLE board_api NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO board_api;
GRANT SELECT ON v_catalog_health, v_funnel_daily, v_provider_pipeline TO board_api;
GRANT SELECT ON listing_plans, listing_subscriptions, invoices, payments TO board_api;
GRANT INSERT, UPDATE ON invoices, payments, listing_plans TO board_api;
GRANT UPDATE (status) ON listing_subscriptions TO board_api;

COMMIT;
