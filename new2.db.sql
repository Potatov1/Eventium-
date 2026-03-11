BEGIN TRANSACTION;

-- Users table (no is_admin)
CREATE TABLE IF NOT EXISTS "users" (
    "id"    INTEGER,
    "username"  TEXT NOT NULL UNIQUE,
    "password_hash"  TEXT NOT NULL,
    PRIMARY KEY("id" AUTOINCREMENT)
);

-- Events table (removed image references)
CREATE TABLE IF NOT EXISTS "events" (
    "event_id"  TEXT,
    "host_id"   TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description"   TEXT,
    "fsq_id"    TEXT NOT NULL,
    "venue_name"    TEXT,
    "venue_address" TEXT NOT NULL,
    "venue_lat" REAL,
    "venue_lon" REAL,
    "venue_category"    TEXT,
    "type"  TEXT NOT NULL CHECK(("type" IN ('public', 'private'))),
    "invite_code"   TEXT,
    "date_time" TEXT NOT NULL,
    "capacity"  INTEGER,
    "created_at"    TEXT DEFAULT CURRENT_TIMESTAMP,
    "tags"  TEXT,
    PRIMARY KEY("event_id")
);

-- Event enrollment table
CREATE TABLE IF NOT EXISTS "event_enrollment" (
    "enrollment_id" TEXT,
    "event_id"  TEXT NOT NULL,
    "enrolled_at"   TEXT DEFAULT CURRENT_TIMESTAMP,
    "user_id"   TEXT NOT NULL,
    PRIMARY KEY("enrollment_id")
);

-- Reminders table
CREATE TABLE IF NOT EXISTS "reminders" (
    "id"    INTEGER,
    "notify_minutes_before" INTEGER NOT NULL,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    "user_id"   INTEGER NOT NULL,
    "event_id"  TEXT NOT NULL,
    PRIMARY KEY("id" AUTOINCREMENT),
    FOREIGN KEY("event_id") REFERENCES "events"("event_id"),
    FOREIGN KEY("user_id") REFERENCES "users"("id")
);

-- Sample events
INSERT INTO "events" VALUES 
('80bba69a-7042-40d6-a4ca-445cf6d14a3b','2','gg','pizza','3fd66200f964a520d8f11ee3','City Hall Park','17 Park Row (btwn Broadway & Centre St), New York, NY 10038',40.7123226224163,-74.0068332579282,'Park','public',NULL,'2025-08-15T15:04:00.000Z',NULL,'2025-08-15 15:04:46',NULL),
('5da6525e-0018-44f6-95b1-11f543e1704b','2','EXAMPLE','GUN','4c711cd79c6d6dcb1f74d47a','Main Park','Sector 47, Noida 201301, Uttar Pradesh',28.5498618741022,77.3719734810861,'Park','public',NULL,'2025-08-15T15:04:00.000Z',NULL,'2025-08-15 15:10:42',NULL),
('bf35befe-dc40-44f9-a8f3-4af7877ff8f9','3','park meet','meet','4c711cd79c6d6dcb1f74d47a','Main Park','Sector 47, Noida 201301, Uttar Pradesh',28.5498618741022,77.3719734810861,'Park','public',NULL,'2025-08-15T15:13:00.000Z',NULL,'2025-08-15 15:14:07',NULL),
('b2669130-d826-4b2c-bb31-03da3309de1d','2','janmashtmi celebration','lor krishna celeb','4fabd294e4b0508b79584496','Noida Sector 50 Park','',28.5710407062904,77.3678749260599,'Park','public',NULL,'2025-08-16T17:38:00.000Z',500,'2025-08-15 17:39:06',NULL),
('ee5121c5-f78e-47cc-a6f0-25c43f8c3e8f','4','freeom ay iscount','sale','4c9d817a2fb1a143f794e140','Market @ Sec 50','Noida',28.5703957975454,77.3619483052775,'Market','public',NULL,'2025-08-15T17:38:00.000Z',NULL,'2025-08-15 17:45:47',NULL),
('66b37f36-00e4-48ff-851a-714c6a9d537b','2','gog','gg','5c6f03f30802d4002c16884c','Joe''s Pizza','124 Fulton St (at Nassau St), New York, NY 10038',40.710178,-74.007769,'Pizzeria','public',NULL,'2025-08-28T14:37:00.000Z',12,'2025-08-28 14:37:16','');

-- Sample users
INSERT INTO "users" VALUES 
(1,'273771','$2b$12$99JLEuvR6MwYBguuRLE5oOlxNZYBqKWz50wyGttu079NSFBgDgtcG'),
(2,'user','$2b$12$HVPPtP68N1mSSNjTpqFdHuV/Pr3mhh.qgBB.2cUcPQjfG72uC08GW'),
(3,'theman','$2b$12$x1NPOv3kCHF5DGm8SavMwukFbB4LS1ueppwAVq0ukSOlaaHqcY3tq'),
(4,'raju','$2b$12$MQi8P5/BcOyi21XN9JWtae0ewbIjYxmbvLiBg.X1Mbe7LX6OTAebK'),
(5,'rgftiukgkyuy','$2b$12$qsahDNHiGI96U2W52nUVTuMhC2b22cC5KkecFtPPGINUCXHByPwde');

COMMIT;