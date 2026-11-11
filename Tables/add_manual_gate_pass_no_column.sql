-- Adds the manually-assigned Gate Pass number -- written by gate/
-- security staff after physical dispatch, once the Gate Pass is
-- Posted. Independent of GATE_PASS_ID (the system's own document
-- number) -- this is the separate, physical gate-register number.
-- Safe to run more than once.

SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_gatepass_header ADD MANUAL_GATE_PASS_NO VARCHAR2(50)';
  DBMS_OUTPUT.PUT_LINE('OK    MANUAL_GATE_PASS_NO added to wst_djn_gatepass_header');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -1430 THEN
      DBMS_OUTPUT.PUT_LINE('SKIP  MANUAL_GATE_PASS_NO already exists');
    ELSE
      DBMS_OUTPUT.PUT_LINE('FAIL  MANUAL_GATE_PASS_NO -- ' || SQLERRM);
    END IF;
END;
/
