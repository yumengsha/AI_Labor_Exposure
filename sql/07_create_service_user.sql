/* ============================================================================
   07_create_service_user.sql
   ----------------------------------------------------------------------------
   Purpose : One-time setup of a SERVICE user for the AUTOMATED refresh job,
             authenticated with an RSA key pair (no password, no browser, no
             MFA prompt).

   WHY THIS EXISTS
   ---------------
   Snowflake is phasing out password authentication for service/automated
   accounts (blocked for all non-human users by roughly Aug-Oct 2026). For a
   scheduled pipeline you must use a non-interactive method; key-pair auth on a
   TYPE=SERVICE user is the supported approach.

   BEFORE RUNNING THIS: generate a key pair on the machine that will run the
   job (keep the PRIVATE key secret; only the PUBLIC key goes to Snowflake):

       # unencrypted private key (simplest for automation):
       openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
       # matching public key:
       openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

   Then paste the PUBLIC key body (the lines BETWEEN the BEGIN/END markers,
   with newlines removed) into the ALTER USER statement below.

   Run this as a role that can create users and grant roles (e.g. ACCOUNTADMIN
   or SECURITYADMIN + SYSADMIN). Review each statement before running.
   ============================================================================ */

USE ROLE ACCOUNTADMIN;   -- or SECURITYADMIN for user/role management

/* ----------------------------------------------------------------------------
   1. A dedicated role for the automation, scoped to just this project's DB.
   ---------------------------------------------------------------------------- */
CREATE ROLE IF NOT EXISTS AI_LABOR_LOADER
    COMMENT = 'Role for the automated AI-labor refresh service user';

-- Warehouse usage (compute) + full rights on the project database.
GRANT USAGE ON WAREHOUSE AI_LABOR_WH TO ROLE AI_LABOR_LOADER;
GRANT USAGE ON DATABASE  AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT USAGE ON ALL SCHEMAS IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT USAGE ON FUTURE SCHEMAS IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;

-- Read+write on RAW (COPY INTO), and create/replace in STAGING/ANALYTICS/QUALITY.
GRANT ALL ON SCHEMA AI_LABOR_ANALYTICS.RAW       TO ROLE AI_LABOR_LOADER;
GRANT ALL ON SCHEMA AI_LABOR_ANALYTICS.STAGING   TO ROLE AI_LABOR_LOADER;
GRANT ALL ON SCHEMA AI_LABOR_ANALYTICS.ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON SCHEMA AI_LABOR_ANALYTICS.QUALITY   TO ROLE AI_LABOR_LOADER;

-- Rights on existing and future tables/views/stages/file formats in each schema.
GRANT ALL ON ALL TABLES       IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON FUTURE TABLES    IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON ALL VIEWS        IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON FUTURE VIEWS     IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON ALL STAGES       IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON FUTURE STAGES    IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON ALL FILE FORMATS IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;
GRANT ALL ON FUTURE FILE FORMATS IN DATABASE AI_LABOR_ANALYTICS TO ROLE AI_LABOR_LOADER;

/* ----------------------------------------------------------------------------
   2. The service user itself. TYPE = SERVICE means it can never log into the
      UI and is exempt from the human-MFA requirement, but it is ALSO barred
      from password auth - so it MUST use key-pair (which we set next).
   ---------------------------------------------------------------------------- */
CREATE USER IF NOT EXISTS SVC_AI_LABOR_LOADER
    TYPE = SERVICE
    DEFAULT_ROLE      = AI_LABOR_LOADER
    DEFAULT_WAREHOUSE = AI_LABOR_WH
    DEFAULT_NAMESPACE = AI_LABOR_ANALYTICS.RAW
    COMMENT = 'Service account for the automated AI-labor data refresh';

GRANT ROLE AI_LABOR_LOADER TO USER SVC_AI_LABOR_LOADER;

/* ----------------------------------------------------------------------------
   3. Attach the PUBLIC key. Replace the placeholder with your rsa_key.pub body
      (everything between -----BEGIN PUBLIC KEY----- and -----END PUBLIC KEY-----
      with line breaks removed). Do NOT paste the private key anywhere.
   ---------------------------------------------------------------------------- */
ALTER USER SVC_AI_LABOR_LOADER SET RSA_PUBLIC_KEY =
'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...REPLACE_WITH_YOUR_PUBLIC_KEY...IDAQAB';

/* Optional second key slot for zero-downtime rotation later:
   ALTER USER SVC_AI_LABOR_LOADER SET RSA_PUBLIC_KEY_2 = '...next key...';
   -- then remove the old one:  ALTER USER SVC_AI_LABOR_LOADER UNSET RSA_PUBLIC_KEY;
*/

/* ----------------------------------------------------------------------------
   4. Verify. Compare the fingerprint shown here with the one your private key
      produces:
        openssl rsa -pubin -in rsa_key.pub -outform DER \
          | openssl dgst -sha256 -binary | openssl enc -base64
      (prefix it with "SHA256:" to match Snowflake's display).
   ---------------------------------------------------------------------------- */
DESC USER SVC_AI_LABOR_LOADER;

/* ----------------------------------------------------------------------------
   5. Point your automation's .env at this user:
        SNOWFLAKE_USER=SVC_AI_LABOR_LOADER
        SNOWFLAKE_ROLE=AI_LABOR_LOADER
        SNOWFLAKE_AUTHENTICATOR=snowflake_jwt
        SNOWFLAKE_PRIVATE_KEY_PATH=/secure/path/rsa_key.p8
   ---------------------------------------------------------------------------- */
