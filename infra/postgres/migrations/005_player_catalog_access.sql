BEGIN;

-- Keep identity documents private while allowing the API to manage safe player fields.
GRANT SELECT (
    id,
    first_name,
    last_name,
    document_type,
    national_id_hmac,
    issuing_country,
    birth_date,
    photo_url,
    created_at
)
    ON public.players TO bracket_app;
GRANT INSERT (
    first_name,
    last_name,
    document_type,
    national_id_encrypted,
    national_id_hmac,
    issuing_country,
    birth_date,
    photo_url
)
    ON public.players TO bracket_app;

COMMIT;
