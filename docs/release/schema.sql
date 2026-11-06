--
-- PostgreSQL database dump
--

\restrict BfgXYbu849BAvcuGYf0aGYmZF0NrqgL9EpUOYFRNlz7h9Nqf3NhfuRpZEl5lbZR

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: account_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.account_role AS ENUM (
    'AR',
    'UNBILLED_AR',
    'DEFERRED_REVENUE',
    'REVENUE'
);


--
-- Name: batch_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.batch_status AS ENUM (
    'DRAFT',
    'APPROVED',
    'POSTED'
);


--
-- Name: contract_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.contract_event_type AS ENUM (
    'NEW',
    'RENEWAL',
    'CANCELLATION',
    'UPGRADE'
);


--
-- Name: contract_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.contract_status AS ENUM (
    'ACTIVE',
    'CANCELLED',
    'EXPIRED'
);


--
-- Name: gl_account_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.gl_account_type AS ENUM (
    'ASSET',
    'LIABILITY',
    'REVENUE'
);


--
-- Name: job_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_status AS ENUM (
    'QUEUED',
    'RUNNING',
    'DONE',
    'FAILED'
);


--
-- Name: job_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_type AS ENUM (
    'INGEST',
    'RECOGNITION',
    'JOURNALS',
    'EXPORT'
);


--
-- Name: journal_entry_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.journal_entry_type AS ENUM (
    'INVOICE',
    'CREDIT_NOTE',
    'REVENUE',
    'REVENUE_CATCH_UP',
    'REVERSAL',
    'ADJUSTMENT'
);


--
-- Name: obligation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.obligation_status AS ENUM (
    'ACTIVE',
    'SUPERSEDED',
    'SATISFIED'
);


--
-- Name: period_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.period_status AS ENUM (
    'FUTURE',
    'OPEN',
    'CLOSING',
    'CLOSED'
);


--
-- Name: recognition_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.recognition_method AS ENUM (
    'RATABLE_DAILY',
    'RATABLE_MONTHLY',
    'POINT_IN_TIME'
);


--
-- Name: schedule_line_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.schedule_line_status AS ENUM (
    'PENDING',
    'POSTED',
    'SUPERSEDED'
);


--
-- Name: schedule_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.schedule_status AS ENUM (
    'ACTIVE',
    'SUPERSEDED'
);


--
-- Name: ssp_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ssp_source AS ENUM (
    'FIXED',
    'LIST_PRICE',
    'PCT_OF_LIST'
);


--
-- Name: upload_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.upload_status AS ENUM (
    'RECEIVED',
    'VALIDATING',
    'ACCEPTED',
    'PARTIAL',
    'REJECTED'
);


--
-- Name: upload_template; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.upload_template AS ENUM (
    'customers',
    'products',
    'contracts',
    'contract_lines',
    'invoices',
    'credit_notes',
    'deliveries'
);


--
-- Name: revrec_append_only(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revrec_append_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: rows cannot be updated or deleted', TG_TABLE_NAME
        USING ERRCODE = 'RV005';
END;
$$;


--
-- Name: revrec_guard_journal_batch(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revrec_guard_journal_batch() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_debit numeric(18, 2);
    v_credit numeric(18, 2);
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.status = 'POSTED' THEN
        RAISE EXCEPTION 'journal batch % is POSTED and read-only', OLD.id
            USING ERRCODE = 'RV001';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' OR NEW.period_id IS DISTINCT FROM OLD.period_id THEN
        IF EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'CLOSED') THEN
            RAISE EXCEPTION 'accounting period % is CLOSED; no journal batch can be added',
                NEW.period_id
                USING ERRCODE = 'RV003';
        END IF;
    END IF;

    IF NEW.status = 'POSTED' THEN
        SELECT coalesce(sum(l.debit), 0), coalesce(sum(l.credit), 0)
          INTO v_debit, v_credit
          FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
         WHERE e.batch_id = NEW.id;
        IF v_debit <> v_credit THEN
            RAISE EXCEPTION 'journal batch % cannot be POSTED: debits % <> credits %',
                NEW.id, v_debit, v_credit
                USING ERRCODE = 'RV002';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: revrec_guard_journal_entry(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revrec_guard_journal_entry() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (SELECT 1 FROM journal_batches WHERE id = OLD.batch_id AND status = 'POSTED') THEN
            RAISE EXCEPTION 'journal entry % is in a POSTED batch and cannot be changed', OLD.id
                USING ERRCODE = 'RV001',
                      HINT = 'Book a REVERSAL or ADJUSTMENT entry in the current open period.';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (SELECT 1 FROM journal_batches WHERE id = NEW.batch_id AND status = 'POSTED') THEN
            RAISE EXCEPTION 'journal batch % is POSTED; entries cannot be added to it', NEW.batch_id
                USING ERRCODE = 'RV001';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: revrec_guard_journal_line(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revrec_guard_journal_line() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (
            SELECT 1 FROM journal_entries e JOIN journal_batches b ON b.id = e.batch_id
            WHERE e.id = OLD.entry_id AND b.status = 'POSTED'
        ) THEN
            RAISE EXCEPTION 'journal line % is in a POSTED batch and cannot be changed', OLD.id
                USING ERRCODE = 'RV001',
                      HINT = 'Book a REVERSAL or ADJUSTMENT entry in the current open period.';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (
            SELECT 1 FROM journal_entries e JOIN journal_batches b ON b.id = e.batch_id
            WHERE e.id = NEW.entry_id AND b.status = 'POSTED'
        ) THEN
            RAISE EXCEPTION 'journal entry % is in a POSTED batch; lines cannot be added to it',
                NEW.entry_id
                USING ERRCODE = 'RV001';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: revrec_guard_schedule_line(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.revrec_guard_schedule_line() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.status = 'POSTED' THEN
        RAISE EXCEPTION 'schedule line % is POSTED and cannot be changed', OLD.id
            USING ERRCODE = 'RV004';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounting_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounting_periods (
    id bigint NOT NULL,
    period_key character varying(6) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status public.period_status DEFAULT 'FUTURE'::public.period_status NOT NULL,
    closed_by bigint,
    closed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: accounting_periods_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounting_periods_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounting_periods_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounting_periods_id_seq OWNED BY public.accounting_periods.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL,
    user_id bigint,
    action character varying(64) NOT NULL,
    entity_type character varying(64) NOT NULL,
    entity_id character varying(64),
    before jsonb,
    after jsonb,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;


--
-- Name: contract_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contract_lines (
    id bigint NOT NULL,
    contract_version_id bigint NOT NULL,
    line_no integer NOT NULL,
    product_id bigint NOT NULL,
    quantity numeric(12,4) NOT NULL,
    unit_price numeric(18,2) NOT NULL,
    discount numeric(18,2) DEFAULT 0 NOT NULL,
    net_price numeric(18,2) NOT NULL,
    service_start date NOT NULL,
    service_end date NOT NULL,
    completion_date date,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contract_lines_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contract_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contract_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.contract_lines_id_seq OWNED BY public.contract_lines.id;


--
-- Name: contract_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contract_versions (
    id bigint NOT NULL,
    contract_id bigint NOT NULL,
    version_no integer NOT NULL,
    event_type public.contract_event_type NOT NULL,
    effective_date date NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    transaction_price numeric(18,2) NOT NULL,
    booked_period character varying(6) NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contract_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contract_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contract_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.contract_versions_id_seq OWNED BY public.contract_versions.id;


--
-- Name: contracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contracts (
    id bigint NOT NULL,
    contract_code character varying(64) NOT NULL,
    customer_id bigint NOT NULL,
    status public.contract_status DEFAULT 'ACTIVE'::public.contract_status NOT NULL,
    current_version_no integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contracts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contracts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contracts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.contracts_id_seq OWNED BY public.contracts.id;


--
-- Name: credit_notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credit_notes (
    id bigint NOT NULL,
    credit_note_number character varying(64) NOT NULL,
    invoice_id bigint NOT NULL,
    credit_date date NOT NULL,
    amount numeric(18,2) NOT NULL,
    reason text NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: credit_notes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credit_notes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_notes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credit_notes_id_seq OWNED BY public.credit_notes.id;


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    id bigint NOT NULL,
    customer_code character varying(64) NOT NULL,
    name character varying(255) NOT NULL,
    country character varying(2) NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: customers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.customers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.customers_id_seq OWNED BY public.customers.id;


--
-- Name: deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deliveries (
    id bigint NOT NULL,
    delivery_code character varying(64) NOT NULL,
    contract_line_id bigint NOT NULL,
    delivery_date date NOT NULL,
    units_fraction numeric(9,6) NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: deliveries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.deliveries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: deliveries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.deliveries_id_seq OWNED BY public.deliveries.id;


--
-- Name: gl_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gl_accounts (
    id bigint NOT NULL,
    account_code character varying(32) NOT NULL,
    name character varying(255) NOT NULL,
    type public.gl_account_type NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: gl_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.gl_accounts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gl_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.gl_accounts_id_seq OWNED BY public.gl_accounts.id;


--
-- Name: gl_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gl_mappings (
    id bigint NOT NULL,
    account_role public.account_role NOT NULL,
    product_id bigint,
    product_category character varying(64),
    account_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_gl_mappings_product_or_category CHECK (((product_id IS NULL) OR (product_category IS NULL)))
);


--
-- Name: gl_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.gl_mappings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gl_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.gl_mappings_id_seq OWNED BY public.gl_mappings.id;


--
-- Name: invoice_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoice_lines (
    id bigint NOT NULL,
    invoice_id bigint NOT NULL,
    contract_line_id bigint,
    line_no integer NOT NULL,
    amount numeric(18,2) NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: invoice_lines_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.invoice_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: invoice_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.invoice_lines_id_seq OWNED BY public.invoice_lines.id;


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    id bigint NOT NULL,
    invoice_number character varying(64) NOT NULL,
    contract_id bigint NOT NULL,
    invoice_date date NOT NULL,
    total_amount numeric(18,2) NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: invoices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.invoices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: invoices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.invoices_id_seq OWNED BY public.invoices.id;


--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_runs (
    id bigint NOT NULL,
    job_type public.job_type NOT NULL,
    status public.job_status DEFAULT 'QUEUED'::public.job_status NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    result jsonb,
    error text,
    created_by bigint,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: job_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.job_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.job_runs_id_seq OWNED BY public.job_runs.id;


--
-- Name: journal_batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_batches (
    id bigint NOT NULL,
    period_id bigint NOT NULL,
    batch_no integer NOT NULL,
    status public.batch_status DEFAULT 'DRAFT'::public.batch_status NOT NULL,
    generated_by bigint NOT NULL,
    approved_by bigint,
    approved_at timestamp with time zone,
    posted_by bigint,
    posted_at timestamp with time zone,
    total_debit numeric(18,2) DEFAULT 0 NOT NULL,
    total_credit numeric(18,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: journal_batches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_batches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_batches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_batches_id_seq OWNED BY public.journal_batches.id;


--
-- Name: journal_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_entries (
    id bigint NOT NULL,
    batch_id bigint NOT NULL,
    entry_type public.journal_entry_type NOT NULL,
    entry_date date NOT NULL,
    contract_id bigint NOT NULL,
    contract_version_id bigint NOT NULL,
    source_type character varying(32) NOT NULL,
    source_id bigint,
    source_upload_id bigint,
    source_row integer,
    reverses_entry_id bigint,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: journal_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_entries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_entries_id_seq OWNED BY public.journal_entries.id;


--
-- Name: journal_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_lines (
    id bigint NOT NULL,
    entry_id bigint NOT NULL,
    account_id bigint NOT NULL,
    debit numeric(18,2) DEFAULT 0 NOT NULL,
    credit numeric(18,2) DEFAULT 0 NOT NULL,
    product_id bigint,
    performance_obligation_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_journal_lines_one_sided CHECK (((debit >= (0)::numeric) AND (credit >= (0)::numeric) AND ((debit = (0)::numeric) OR (credit = (0)::numeric))))
);


--
-- Name: journal_lines_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_lines_id_seq OWNED BY public.journal_lines.id;


--
-- Name: performance_obligations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.performance_obligations (
    id bigint NOT NULL,
    contract_version_id bigint NOT NULL,
    contract_line_id bigint NOT NULL,
    product_id bigint NOT NULL,
    method public.recognition_method NOT NULL,
    ssp_amount numeric(18,2) NOT NULL,
    allocated_amount numeric(18,2) NOT NULL,
    service_start date NOT NULL,
    service_end date NOT NULL,
    completion_date date,
    carried_from_po_id bigint,
    status public.obligation_status DEFAULT 'ACTIVE'::public.obligation_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: performance_obligations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.performance_obligations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: performance_obligations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.performance_obligations_id_seq OWNED BY public.performance_obligations.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.products (
    id bigint NOT NULL,
    product_code character varying(128) NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(64),
    list_price numeric(18,2) NOT NULL,
    recognition_method public.recognition_method NOT NULL,
    is_separate_obligation boolean NOT NULL,
    revenue_account_id bigint NOT NULL,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- Name: revenue_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revenue_schedules (
    id bigint NOT NULL,
    performance_obligation_id bigint NOT NULL,
    contract_version_id bigint NOT NULL,
    status public.schedule_status DEFAULT 'ACTIVE'::public.schedule_status NOT NULL,
    generated_by_job_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: revenue_schedules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.revenue_schedules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: revenue_schedules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.revenue_schedules_id_seq OWNED BY public.revenue_schedules.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id bigint NOT NULL,
    name character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: schedule_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schedule_lines (
    id bigint NOT NULL,
    schedule_id bigint NOT NULL,
    service_period character varying(6) NOT NULL,
    amount numeric(18,2) NOT NULL,
    status public.schedule_line_status DEFAULT 'PENDING'::public.schedule_line_status NOT NULL,
    posting_period character varying(6),
    is_catch_up boolean DEFAULT false NOT NULL,
    journal_line_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schedule_lines_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.schedule_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: schedule_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.schedule_lines_id_seq OWNED BY public.schedule_lines.id;


--
-- Name: ssp_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ssp_rules (
    id bigint NOT NULL,
    product_id bigint NOT NULL,
    ssp_source public.ssp_source NOT NULL,
    ssp_value numeric(18,2),
    ssp_pct numeric(7,4),
    valid_from date NOT NULL,
    valid_to date,
    source_row integer,
    source_payload jsonb,
    source_upload_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_ssp_rules_fixed_needs_value CHECK (((ssp_source <> 'FIXED'::public.ssp_source) OR (ssp_value IS NOT NULL))),
    CONSTRAINT ck_ssp_rules_pct_needs_pct CHECK (((ssp_source <> 'PCT_OF_LIST'::public.ssp_source) OR (ssp_pct IS NOT NULL))),
    CONSTRAINT ck_ssp_rules_valid_range CHECK (((valid_to IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: ssp_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ssp_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ssp_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ssp_rules_id_seq OWNED BY public.ssp_rules.id;


--
-- Name: upload_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.upload_files (
    id bigint NOT NULL,
    template public.upload_template NOT NULL,
    original_filename character varying(255) NOT NULL,
    sha256 character varying(64) NOT NULL,
    stored_path character varying(1024) NOT NULL,
    uploaded_by bigint NOT NULL,
    period_key character varying(6) NOT NULL,
    status public.upload_status DEFAULT 'RECEIVED'::public.upload_status NOT NULL,
    total_rows integer DEFAULT 0 NOT NULL,
    accepted_rows integer DEFAULT 0 NOT NULL,
    rejected_rows integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: upload_files_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.upload_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: upload_files_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.upload_files_id_seq OWNED BY public.upload_files.id;


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    role_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_roles_id_seq OWNED BY public.user_roles.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    email character varying(320) NOT NULL,
    full_name character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: validation_errors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.validation_errors (
    id bigint NOT NULL,
    upload_file_id bigint NOT NULL,
    row_number integer NOT NULL,
    column_name character varying(64),
    error_code character varying(4) NOT NULL,
    message text NOT NULL,
    raw_value text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: validation_errors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.validation_errors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: validation_errors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.validation_errors_id_seq OWNED BY public.validation_errors.id;


--
-- Name: accounting_periods id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_periods ALTER COLUMN id SET DEFAULT nextval('public.accounting_periods_id_seq'::regclass);


--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);


--
-- Name: contract_lines id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines ALTER COLUMN id SET DEFAULT nextval('public.contract_lines_id_seq'::regclass);


--
-- Name: contract_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_versions ALTER COLUMN id SET DEFAULT nextval('public.contract_versions_id_seq'::regclass);


--
-- Name: contracts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts ALTER COLUMN id SET DEFAULT nextval('public.contracts_id_seq'::regclass);


--
-- Name: credit_notes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_notes ALTER COLUMN id SET DEFAULT nextval('public.credit_notes_id_seq'::regclass);


--
-- Name: customers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers ALTER COLUMN id SET DEFAULT nextval('public.customers_id_seq'::regclass);


--
-- Name: deliveries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deliveries ALTER COLUMN id SET DEFAULT nextval('public.deliveries_id_seq'::regclass);


--
-- Name: gl_accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_accounts ALTER COLUMN id SET DEFAULT nextval('public.gl_accounts_id_seq'::regclass);


--
-- Name: gl_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_mappings ALTER COLUMN id SET DEFAULT nextval('public.gl_mappings_id_seq'::regclass);


--
-- Name: invoice_lines id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines ALTER COLUMN id SET DEFAULT nextval('public.invoice_lines_id_seq'::regclass);


--
-- Name: invoices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices ALTER COLUMN id SET DEFAULT nextval('public.invoices_id_seq'::regclass);


--
-- Name: job_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs ALTER COLUMN id SET DEFAULT nextval('public.job_runs_id_seq'::regclass);


--
-- Name: journal_batches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches ALTER COLUMN id SET DEFAULT nextval('public.journal_batches_id_seq'::regclass);


--
-- Name: journal_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries ALTER COLUMN id SET DEFAULT nextval('public.journal_entries_id_seq'::regclass);


--
-- Name: journal_lines id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines ALTER COLUMN id SET DEFAULT nextval('public.journal_lines_id_seq'::regclass);


--
-- Name: performance_obligations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations ALTER COLUMN id SET DEFAULT nextval('public.performance_obligations_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- Name: revenue_schedules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_schedules ALTER COLUMN id SET DEFAULT nextval('public.revenue_schedules_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: schedule_lines id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_lines ALTER COLUMN id SET DEFAULT nextval('public.schedule_lines_id_seq'::regclass);


--
-- Name: ssp_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ssp_rules ALTER COLUMN id SET DEFAULT nextval('public.ssp_rules_id_seq'::regclass);


--
-- Name: upload_files id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_files ALTER COLUMN id SET DEFAULT nextval('public.upload_files_id_seq'::regclass);


--
-- Name: user_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles ALTER COLUMN id SET DEFAULT nextval('public.user_roles_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: validation_errors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_errors ALTER COLUMN id SET DEFAULT nextval('public.validation_errors_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: accounting_periods pk_accounting_periods; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_periods
    ADD CONSTRAINT pk_accounting_periods PRIMARY KEY (id);


--
-- Name: audit_log pk_audit_log; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT pk_audit_log PRIMARY KEY (id);


--
-- Name: contract_lines pk_contract_lines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines
    ADD CONSTRAINT pk_contract_lines PRIMARY KEY (id);


--
-- Name: contract_versions pk_contract_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_versions
    ADD CONSTRAINT pk_contract_versions PRIMARY KEY (id);


--
-- Name: contracts pk_contracts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT pk_contracts PRIMARY KEY (id);


--
-- Name: credit_notes pk_credit_notes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_notes
    ADD CONSTRAINT pk_credit_notes PRIMARY KEY (id);


--
-- Name: customers pk_customers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT pk_customers PRIMARY KEY (id);


--
-- Name: deliveries pk_deliveries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deliveries
    ADD CONSTRAINT pk_deliveries PRIMARY KEY (id);


--
-- Name: gl_accounts pk_gl_accounts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_accounts
    ADD CONSTRAINT pk_gl_accounts PRIMARY KEY (id);


--
-- Name: gl_mappings pk_gl_mappings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_mappings
    ADD CONSTRAINT pk_gl_mappings PRIMARY KEY (id);


--
-- Name: invoice_lines pk_invoice_lines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT pk_invoice_lines PRIMARY KEY (id);


--
-- Name: invoices pk_invoices; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT pk_invoices PRIMARY KEY (id);


--
-- Name: job_runs pk_job_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT pk_job_runs PRIMARY KEY (id);


--
-- Name: journal_batches pk_journal_batches; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT pk_journal_batches PRIMARY KEY (id);


--
-- Name: journal_entries pk_journal_entries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT pk_journal_entries PRIMARY KEY (id);


--
-- Name: journal_lines pk_journal_lines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines
    ADD CONSTRAINT pk_journal_lines PRIMARY KEY (id);


--
-- Name: performance_obligations pk_performance_obligations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations
    ADD CONSTRAINT pk_performance_obligations PRIMARY KEY (id);


--
-- Name: products pk_products; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT pk_products PRIMARY KEY (id);


--
-- Name: revenue_schedules pk_revenue_schedules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_schedules
    ADD CONSTRAINT pk_revenue_schedules PRIMARY KEY (id);


--
-- Name: roles pk_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT pk_roles PRIMARY KEY (id);


--
-- Name: schedule_lines pk_schedule_lines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_lines
    ADD CONSTRAINT pk_schedule_lines PRIMARY KEY (id);


--
-- Name: ssp_rules pk_ssp_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ssp_rules
    ADD CONSTRAINT pk_ssp_rules PRIMARY KEY (id);


--
-- Name: upload_files pk_upload_files; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_files
    ADD CONSTRAINT pk_upload_files PRIMARY KEY (id);


--
-- Name: user_roles pk_user_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT pk_user_roles PRIMARY KEY (id);


--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);


--
-- Name: validation_errors pk_validation_errors; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_errors
    ADD CONSTRAINT pk_validation_errors PRIMARY KEY (id);


--
-- Name: accounting_periods uq_accounting_periods_period_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_periods
    ADD CONSTRAINT uq_accounting_periods_period_key UNIQUE (period_key);


--
-- Name: contract_lines uq_contract_lines_contract_version_id_line_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines
    ADD CONSTRAINT uq_contract_lines_contract_version_id_line_no UNIQUE (contract_version_id, line_no);


--
-- Name: contract_versions uq_contract_versions_contract_id_version_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_versions
    ADD CONSTRAINT uq_contract_versions_contract_id_version_no UNIQUE (contract_id, version_no);


--
-- Name: contracts uq_contracts_contract_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT uq_contracts_contract_code UNIQUE (contract_code);


--
-- Name: credit_notes uq_credit_notes_credit_note_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_notes
    ADD CONSTRAINT uq_credit_notes_credit_note_number UNIQUE (credit_note_number);


--
-- Name: customers uq_customers_customer_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT uq_customers_customer_code UNIQUE (customer_code);


--
-- Name: deliveries uq_deliveries_delivery_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deliveries
    ADD CONSTRAINT uq_deliveries_delivery_code UNIQUE (delivery_code);


--
-- Name: gl_accounts uq_gl_accounts_account_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_accounts
    ADD CONSTRAINT uq_gl_accounts_account_code UNIQUE (account_code);


--
-- Name: gl_mappings uq_gl_mappings_account_role_product_id_product_category; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_mappings
    ADD CONSTRAINT uq_gl_mappings_account_role_product_id_product_category UNIQUE NULLS NOT DISTINCT (account_role, product_id, product_category);


--
-- Name: invoice_lines uq_invoice_lines_invoice_id_line_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT uq_invoice_lines_invoice_id_line_no UNIQUE (invoice_id, line_no);


--
-- Name: invoices uq_invoices_invoice_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT uq_invoices_invoice_number UNIQUE (invoice_number);


--
-- Name: journal_batches uq_journal_batches_period_id_batch_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT uq_journal_batches_period_id_batch_no UNIQUE (period_id, batch_no);


--
-- Name: products uq_products_product_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT uq_products_product_code UNIQUE (product_code);


--
-- Name: roles uq_roles_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_name UNIQUE (name);


--
-- Name: user_roles uq_user_roles_user_id_role_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT uq_user_roles_user_id_role_id UNIQUE (user_id, role_id);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: ix_accounting_periods_closed_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounting_periods_closed_by ON public.accounting_periods USING btree (closed_by);


--
-- Name: ix_audit_log_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_log_entity ON public.audit_log USING btree (entity_type, entity_id);


--
-- Name: ix_audit_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_log_user_id ON public.audit_log USING btree (user_id);


--
-- Name: ix_contract_lines_contract_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contract_lines_contract_version_id ON public.contract_lines USING btree (contract_version_id);


--
-- Name: ix_contract_lines_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contract_lines_product_id ON public.contract_lines USING btree (product_id);


--
-- Name: ix_contract_lines_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contract_lines_source_upload_id ON public.contract_lines USING btree (source_upload_id);


--
-- Name: ix_contract_versions_contract_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contract_versions_contract_id ON public.contract_versions USING btree (contract_id);


--
-- Name: ix_contract_versions_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contract_versions_source_upload_id ON public.contract_versions USING btree (source_upload_id);


--
-- Name: ix_contracts_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contracts_customer_id ON public.contracts USING btree (customer_id);


--
-- Name: ix_credit_notes_invoice_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_notes_invoice_id ON public.credit_notes USING btree (invoice_id);


--
-- Name: ix_credit_notes_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_notes_source_upload_id ON public.credit_notes USING btree (source_upload_id);


--
-- Name: ix_customers_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_customers_source_upload_id ON public.customers USING btree (source_upload_id);


--
-- Name: ix_deliveries_contract_line_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deliveries_contract_line_id ON public.deliveries USING btree (contract_line_id);


--
-- Name: ix_deliveries_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deliveries_source_upload_id ON public.deliveries USING btree (source_upload_id);


--
-- Name: ix_gl_mappings_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gl_mappings_account_id ON public.gl_mappings USING btree (account_id);


--
-- Name: ix_gl_mappings_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gl_mappings_product_id ON public.gl_mappings USING btree (product_id);


--
-- Name: ix_invoice_lines_contract_line_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_contract_line_id ON public.invoice_lines USING btree (contract_line_id);


--
-- Name: ix_invoice_lines_invoice_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_invoice_id ON public.invoice_lines USING btree (invoice_id);


--
-- Name: ix_invoice_lines_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_source_upload_id ON public.invoice_lines USING btree (source_upload_id);


--
-- Name: ix_invoices_contract_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoices_contract_id ON public.invoices USING btree (contract_id);


--
-- Name: ix_invoices_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoices_source_upload_id ON public.invoices USING btree (source_upload_id);


--
-- Name: ix_job_runs_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_runs_created_by ON public.job_runs USING btree (created_by);


--
-- Name: ix_job_runs_status_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_runs_status_created_at ON public.job_runs USING btree (status, created_at);


--
-- Name: ix_journal_batches_approved_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_batches_approved_by ON public.journal_batches USING btree (approved_by);


--
-- Name: ix_journal_batches_generated_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_batches_generated_by ON public.journal_batches USING btree (generated_by);


--
-- Name: ix_journal_batches_period_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_batches_period_id ON public.journal_batches USING btree (period_id);


--
-- Name: ix_journal_batches_posted_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_batches_posted_by ON public.journal_batches USING btree (posted_by);


--
-- Name: ix_journal_entries_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_batch_id ON public.journal_entries USING btree (batch_id);


--
-- Name: ix_journal_entries_contract_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_contract_id ON public.journal_entries USING btree (contract_id);


--
-- Name: ix_journal_entries_contract_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_contract_version_id ON public.journal_entries USING btree (contract_version_id);


--
-- Name: ix_journal_entries_reverses_entry_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_reverses_entry_id ON public.journal_entries USING btree (reverses_entry_id);


--
-- Name: ix_journal_entries_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_source_upload_id ON public.journal_entries USING btree (source_upload_id);


--
-- Name: ix_journal_lines_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_lines_account_id ON public.journal_lines USING btree (account_id);


--
-- Name: ix_journal_lines_entry_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_lines_entry_id ON public.journal_lines USING btree (entry_id);


--
-- Name: ix_journal_lines_performance_obligation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_lines_performance_obligation_id ON public.journal_lines USING btree (performance_obligation_id);


--
-- Name: ix_journal_lines_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_lines_product_id ON public.journal_lines USING btree (product_id);


--
-- Name: ix_performance_obligations_carried_from_po_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_performance_obligations_carried_from_po_id ON public.performance_obligations USING btree (carried_from_po_id);


--
-- Name: ix_performance_obligations_contract_line_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_performance_obligations_contract_line_id ON public.performance_obligations USING btree (contract_line_id);


--
-- Name: ix_performance_obligations_contract_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_performance_obligations_contract_version_id ON public.performance_obligations USING btree (contract_version_id);


--
-- Name: ix_performance_obligations_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_performance_obligations_product_id ON public.performance_obligations USING btree (product_id);


--
-- Name: ix_products_revenue_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_products_revenue_account_id ON public.products USING btree (revenue_account_id);


--
-- Name: ix_products_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_products_source_upload_id ON public.products USING btree (source_upload_id);


--
-- Name: ix_revenue_schedules_contract_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revenue_schedules_contract_version_id ON public.revenue_schedules USING btree (contract_version_id);


--
-- Name: ix_revenue_schedules_generated_by_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revenue_schedules_generated_by_job_id ON public.revenue_schedules USING btree (generated_by_job_id);


--
-- Name: ix_revenue_schedules_performance_obligation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revenue_schedules_performance_obligation_id ON public.revenue_schedules USING btree (performance_obligation_id);


--
-- Name: ix_schedule_lines_journal_line_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedule_lines_journal_line_id ON public.schedule_lines USING btree (journal_line_id);


--
-- Name: ix_schedule_lines_posting_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedule_lines_posting_period ON public.schedule_lines USING btree (posting_period);


--
-- Name: ix_schedule_lines_schedule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedule_lines_schedule_id ON public.schedule_lines USING btree (schedule_id);


--
-- Name: ix_schedule_lines_status_service_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedule_lines_status_service_period ON public.schedule_lines USING btree (status, service_period);


--
-- Name: ix_ssp_rules_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ssp_rules_product_id ON public.ssp_rules USING btree (product_id);


--
-- Name: ix_ssp_rules_source_upload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ssp_rules_source_upload_id ON public.ssp_rules USING btree (source_upload_id);


--
-- Name: ix_upload_files_uploaded_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_upload_files_uploaded_by ON public.upload_files USING btree (uploaded_by);


--
-- Name: ix_user_roles_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_roles_role_id ON public.user_roles USING btree (role_id);


--
-- Name: ix_user_roles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_roles_user_id ON public.user_roles USING btree (user_id);


--
-- Name: ix_validation_errors_upload_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_validation_errors_upload_file_id ON public.validation_errors USING btree (upload_file_id);


--
-- Name: uq_accounting_periods_one_open; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_accounting_periods_one_open ON public.accounting_periods USING btree (status) WHERE (status = 'OPEN'::public.period_status);


--
-- Name: uq_journal_entries_one_per_document; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_journal_entries_one_per_document ON public.journal_entries USING btree (entry_type, source_id) WHERE (entry_type = ANY (ARRAY['INVOICE'::public.journal_entry_type, 'CREDIT_NOTE'::public.journal_entry_type]));


--
-- Name: uq_journal_entries_one_reversal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_journal_entries_one_reversal ON public.journal_entries USING btree (reverses_entry_id) WHERE (reverses_entry_id IS NOT NULL);


--
-- Name: audit_log trg_audit_log_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_log_append_only BEFORE DELETE OR UPDATE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.revrec_append_only();


--
-- Name: contract_versions trg_contract_versions_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_contract_versions_append_only BEFORE DELETE OR UPDATE ON public.contract_versions FOR EACH ROW EXECUTE FUNCTION public.revrec_append_only();


--
-- Name: journal_batches trg_journal_batches_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_journal_batches_guard BEFORE INSERT OR DELETE OR UPDATE ON public.journal_batches FOR EACH ROW EXECUTE FUNCTION public.revrec_guard_journal_batch();


--
-- Name: journal_entries trg_journal_entries_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_journal_entries_guard BEFORE INSERT OR DELETE OR UPDATE ON public.journal_entries FOR EACH ROW EXECUTE FUNCTION public.revrec_guard_journal_entry();


--
-- Name: journal_lines trg_journal_lines_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_journal_lines_guard BEFORE INSERT OR DELETE OR UPDATE ON public.journal_lines FOR EACH ROW EXECUTE FUNCTION public.revrec_guard_journal_line();


--
-- Name: schedule_lines trg_schedule_lines_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_schedule_lines_guard BEFORE DELETE OR UPDATE ON public.schedule_lines FOR EACH ROW EXECUTE FUNCTION public.revrec_guard_schedule_line();


--
-- Name: accounting_periods fk_accounting_periods_closed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_periods
    ADD CONSTRAINT fk_accounting_periods_closed_by_users FOREIGN KEY (closed_by) REFERENCES public.users(id);


--
-- Name: audit_log fk_audit_log_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT fk_audit_log_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: contract_lines fk_contract_lines_contract_version_id_contract_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines
    ADD CONSTRAINT fk_contract_lines_contract_version_id_contract_versions FOREIGN KEY (contract_version_id) REFERENCES public.contract_versions(id);


--
-- Name: contract_lines fk_contract_lines_product_id_products; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines
    ADD CONSTRAINT fk_contract_lines_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: contract_lines fk_contract_lines_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_lines
    ADD CONSTRAINT fk_contract_lines_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: contract_versions fk_contract_versions_contract_id_contracts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_versions
    ADD CONSTRAINT fk_contract_versions_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: contract_versions fk_contract_versions_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_versions
    ADD CONSTRAINT fk_contract_versions_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: contracts fk_contracts_customer_id_customers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT fk_contracts_customer_id_customers FOREIGN KEY (customer_id) REFERENCES public.customers(id);


--
-- Name: credit_notes fk_credit_notes_invoice_id_invoices; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_notes
    ADD CONSTRAINT fk_credit_notes_invoice_id_invoices FOREIGN KEY (invoice_id) REFERENCES public.invoices(id);


--
-- Name: credit_notes fk_credit_notes_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_notes
    ADD CONSTRAINT fk_credit_notes_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: customers fk_customers_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT fk_customers_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: deliveries fk_deliveries_contract_line_id_contract_lines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deliveries
    ADD CONSTRAINT fk_deliveries_contract_line_id_contract_lines FOREIGN KEY (contract_line_id) REFERENCES public.contract_lines(id);


--
-- Name: deliveries fk_deliveries_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deliveries
    ADD CONSTRAINT fk_deliveries_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: gl_mappings fk_gl_mappings_account_id_gl_accounts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_mappings
    ADD CONSTRAINT fk_gl_mappings_account_id_gl_accounts FOREIGN KEY (account_id) REFERENCES public.gl_accounts(id);


--
-- Name: gl_mappings fk_gl_mappings_product_id_products; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gl_mappings
    ADD CONSTRAINT fk_gl_mappings_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: invoice_lines fk_invoice_lines_contract_line_id_contract_lines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT fk_invoice_lines_contract_line_id_contract_lines FOREIGN KEY (contract_line_id) REFERENCES public.contract_lines(id);


--
-- Name: invoice_lines fk_invoice_lines_invoice_id_invoices; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT fk_invoice_lines_invoice_id_invoices FOREIGN KEY (invoice_id) REFERENCES public.invoices(id);


--
-- Name: invoice_lines fk_invoice_lines_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT fk_invoice_lines_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: invoices fk_invoices_contract_id_contracts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoices_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: invoices fk_invoices_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoices_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: job_runs fk_job_runs_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT fk_job_runs_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: journal_batches fk_journal_batches_approved_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT fk_journal_batches_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: journal_batches fk_journal_batches_generated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT fk_journal_batches_generated_by_users FOREIGN KEY (generated_by) REFERENCES public.users(id);


--
-- Name: journal_batches fk_journal_batches_period_id_accounting_periods; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT fk_journal_batches_period_id_accounting_periods FOREIGN KEY (period_id) REFERENCES public.accounting_periods(id);


--
-- Name: journal_batches fk_journal_batches_posted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_batches
    ADD CONSTRAINT fk_journal_batches_posted_by_users FOREIGN KEY (posted_by) REFERENCES public.users(id);


--
-- Name: journal_entries fk_journal_entries_batch_id_journal_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT fk_journal_entries_batch_id_journal_batches FOREIGN KEY (batch_id) REFERENCES public.journal_batches(id);


--
-- Name: journal_entries fk_journal_entries_contract_id_contracts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT fk_journal_entries_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: journal_entries fk_journal_entries_contract_version_id_contract_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT fk_journal_entries_contract_version_id_contract_versions FOREIGN KEY (contract_version_id) REFERENCES public.contract_versions(id);


--
-- Name: journal_entries fk_journal_entries_reverses_entry_id_journal_entries; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT fk_journal_entries_reverses_entry_id_journal_entries FOREIGN KEY (reverses_entry_id) REFERENCES public.journal_entries(id);


--
-- Name: journal_entries fk_journal_entries_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT fk_journal_entries_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: journal_lines fk_journal_lines_account_id_gl_accounts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines
    ADD CONSTRAINT fk_journal_lines_account_id_gl_accounts FOREIGN KEY (account_id) REFERENCES public.gl_accounts(id);


--
-- Name: journal_lines fk_journal_lines_entry_id_journal_entries; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines
    ADD CONSTRAINT fk_journal_lines_entry_id_journal_entries FOREIGN KEY (entry_id) REFERENCES public.journal_entries(id);


--
-- Name: journal_lines fk_journal_lines_performance_obligation_id_performance__9e74; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines
    ADD CONSTRAINT fk_journal_lines_performance_obligation_id_performance__9e74 FOREIGN KEY (performance_obligation_id) REFERENCES public.performance_obligations(id);


--
-- Name: journal_lines fk_journal_lines_product_id_products; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_lines
    ADD CONSTRAINT fk_journal_lines_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: performance_obligations fk_performance_obligations_carried_from_po_id_performan_1c0b; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations
    ADD CONSTRAINT fk_performance_obligations_carried_from_po_id_performan_1c0b FOREIGN KEY (carried_from_po_id) REFERENCES public.performance_obligations(id);


--
-- Name: performance_obligations fk_performance_obligations_contract_line_id_contract_lines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations
    ADD CONSTRAINT fk_performance_obligations_contract_line_id_contract_lines FOREIGN KEY (contract_line_id) REFERENCES public.contract_lines(id);


--
-- Name: performance_obligations fk_performance_obligations_contract_version_id_contract_8e7a; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations
    ADD CONSTRAINT fk_performance_obligations_contract_version_id_contract_8e7a FOREIGN KEY (contract_version_id) REFERENCES public.contract_versions(id);


--
-- Name: performance_obligations fk_performance_obligations_product_id_products; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_obligations
    ADD CONSTRAINT fk_performance_obligations_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: products fk_products_revenue_account_id_gl_accounts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT fk_products_revenue_account_id_gl_accounts FOREIGN KEY (revenue_account_id) REFERENCES public.gl_accounts(id);


--
-- Name: products fk_products_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT fk_products_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: revenue_schedules fk_revenue_schedules_contract_version_id_contract_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_schedules
    ADD CONSTRAINT fk_revenue_schedules_contract_version_id_contract_versions FOREIGN KEY (contract_version_id) REFERENCES public.contract_versions(id);


--
-- Name: revenue_schedules fk_revenue_schedules_generated_by_job_id_job_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_schedules
    ADD CONSTRAINT fk_revenue_schedules_generated_by_job_id_job_runs FOREIGN KEY (generated_by_job_id) REFERENCES public.job_runs(id);


--
-- Name: revenue_schedules fk_revenue_schedules_performance_obligation_id_performa_2faf; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_schedules
    ADD CONSTRAINT fk_revenue_schedules_performance_obligation_id_performa_2faf FOREIGN KEY (performance_obligation_id) REFERENCES public.performance_obligations(id);


--
-- Name: schedule_lines fk_schedule_lines_journal_line_id_journal_lines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_lines
    ADD CONSTRAINT fk_schedule_lines_journal_line_id_journal_lines FOREIGN KEY (journal_line_id) REFERENCES public.journal_lines(id);


--
-- Name: schedule_lines fk_schedule_lines_schedule_id_revenue_schedules; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_lines
    ADD CONSTRAINT fk_schedule_lines_schedule_id_revenue_schedules FOREIGN KEY (schedule_id) REFERENCES public.revenue_schedules(id);


--
-- Name: ssp_rules fk_ssp_rules_product_id_products; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ssp_rules
    ADD CONSTRAINT fk_ssp_rules_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: ssp_rules fk_ssp_rules_source_upload_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ssp_rules
    ADD CONSTRAINT fk_ssp_rules_source_upload_id_upload_files FOREIGN KEY (source_upload_id) REFERENCES public.upload_files(id);


--
-- Name: upload_files fk_upload_files_uploaded_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_files
    ADD CONSTRAINT fk_upload_files_uploaded_by_users FOREIGN KEY (uploaded_by) REFERENCES public.users(id);


--
-- Name: user_roles fk_user_roles_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: user_roles fk_user_roles_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: validation_errors fk_validation_errors_upload_file_id_upload_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_errors
    ADD CONSTRAINT fk_validation_errors_upload_file_id_upload_files FOREIGN KEY (upload_file_id) REFERENCES public.upload_files(id);


--
-- PostgreSQL database dump complete
--

\unrestrict BfgXYbu849BAvcuGYf0aGYmZF0NrqgL9EpUOYFRNlz7h9Nqf3NhfuRpZEl5lbZR

