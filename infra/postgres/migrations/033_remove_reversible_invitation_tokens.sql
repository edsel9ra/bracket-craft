BEGIN;

ALTER TABLE public.organization_invitations DROP COLUMN token_encrypted;

COMMIT;
