"""
PostgreSQL connection layer for all raw-SQL modules (wastage, finance, accounts).

The app was written against Oracle (python-oracledb). This module gives the
rest of the code a psycopg 3 connection that keeps the few driver-level
behaviours the code relies on, so the SQL modules only had to change real
SQL dialect differences:

  * Bind style       ``:1, :2`` / ``:name``  ->  translated to psycopg's ``%s``
                     (string literals, ``::casts`` and ``%`` are handled).
  * Empty strings    bound ``''`` becomes NULL (Oracle treats '' as NULL).
  * Column names     ``cursor.description`` names come back UPPER-case, so
                     ``dict(zip(cols, row))`` keys stay e.g. ``ITEM_NAME``.
  * Numbers          NUMERIC comes back as ``int`` when whole, else ``float``
                     (same as oracledb's default), never ``Decimal``.
  * Statement-level  a failed statement only undoes itself (SAVEPOINT per
    rollback         execute), like Oracle. A PostgreSQL error would otherwise
                     abort the whole transaction, and several functions catch
                     an error and retry a fallback query on the same connection.
  * ``with conn:``   closes WITHOUT committing (rolls back anything not
                     committed), exactly like oracledb. Code commits explicitly.
  * Errors           everything raises ``DatabaseError``; ``str(e)`` starts with
                     the matching Oracle code (``ORA-00001`` unique, ``ORA-00904``
                     unknown column, ``ORA-02290`` check, ``ORA-01400`` not null,
                     ``ORA-12899`` too long...) and ``e.args[0].code`` holds the
                     number, so existing error handling keeps working.
  * Audit user       ``connect(username)`` sets ``app.client_identifier`` for
                     the session; audit triggers read it (was
                     DBMS_SESSION.SET_IDENTIFIER / CLIENT_IDENTIFIER).
"""
import os
import re
import datetime as _dt
from decimal import Decimal

import psycopg
from psycopg import sql as _pgsql  # noqa: F401  (re-export convenience)
from psycopg.adapt import Loader

try:
    import environ
    from pathlib import Path
    environ.Env.read_env(Path(__file__).resolve().parent.parent / '.env')
except Exception:  # pragma: no cover - env file is optional (Docker passes env)
    pass


# ------------------------------------------------------------------ errors
class _ErrInfo:
    def __init__(self, code, message, sqlstate=None, constraint=None):
        self.code = code
        self.message = message
        self.full_code = f'ORA-{code:05d}'
        self.sqlstate = sqlstate
        self.constraint = constraint

    def __str__(self):
        return self.message


class Error(Exception):
    pass


class DatabaseError(Error):
    """Raised for every database failure (mirrors oracledb.DatabaseError)."""

    def __init__(self, info, original=None):
        super().__init__(info)
        self.original = original

    def __str__(self):
        return str(self.args[0])


IntegrityError = DatabaseError

# SQLSTATE -> Oracle error number, for messages/handlers written against Oracle
_SQLSTATE_TO_ORA = {
    '23505': 1,      # unique_violation           -> ORA-00001
    '42703': 904,    # undefined_column           -> ORA-00904
    '42P01': 942,    # undefined_table            -> ORA-00942
    '23514': 2290,   # check_violation            -> ORA-02290
    '23502': 1400,   # not_null_violation         -> ORA-01400
    '23503': 2291,   # foreign_key_violation      -> ORA-02291/02292
    '22001': 12899,  # string_data_right_truncation -> ORA-12899
    '22007': 1861,   # invalid_datetime_format    -> ORA-01861
    '22008': 1840,   # datetime_field_overflow    -> ORA-01840
    '22003': 1438,   # numeric_value_out_of_range -> ORA-01438
    '22P02': 1722,   # invalid_text_representation -> ORA-01722
    '55P03': 54,     # lock_not_available (NOWAIT) -> ORA-00054
    '40P01': 60,     # deadlock_detected          -> ORA-00060
}


def _wrap_error(exc):
    sqlstate = getattr(exc, 'sqlstate', None)
    diag = getattr(exc, 'diag', None)
    pg_msg = (getattr(diag, 'message_primary', None) or str(exc)).strip()
    constraint = getattr(diag, 'constraint_name', None)
    m = re.match(r'ORA-(\d{5})', pg_msg)          # raised by our own triggers
    if m:
        code = int(m.group(1))
        msg = pg_msg
    else:
        code = _SQLSTATE_TO_ORA.get(sqlstate, 20000)
        if sqlstate == '23503' and 'still referenced' in pg_msg:
            code = 2292
        msg = f'ORA-{code:05d}: {pg_msg}'
        if constraint:
            msg += f' ({constraint})'
    return DatabaseError(_ErrInfo(code, msg, sqlstate, constraint), exc)


def _log_sql_error(sql, err):
    """Optional: SOORTY_SQL_ERROR_LOG=/path appends every failed statement
    (handy because some screens catch DB errors and fall back quietly)."""
    path = os.environ.get('SOORTY_SQL_ERROR_LOG')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(f'---\n{err}\n{(sql or "").strip()}\n')
    except OSError:
        pass


# ------------------------------------------------------------- type loaders
class _NumericLoader(Loader):
    """NUMERIC -> int when whole, else float (oracledb default behaviour)."""

    def load(self, data):
        if isinstance(data, memoryview):
            data = bytes(data)
        d = Decimal(data.decode())
        if d.is_nan():
            return None
        if d == d.to_integral_value():
            return int(d)
        return float(d)


# ---------------------------------------------------------- bind translator
_BIND_RE = re.compile(
    r"""('(?:[^']|'')*')          # 1: string literal
      | ("(?:[^"]|"")*")          # 2: quoted identifier
      | (--[^\n]*)                # 3: line comment
      | (/\*.*?\*/)               # 4: block comment
      | (::)                      # 5: postgres cast
      | (%)                       # 6: literal percent
      | (?<![\w:]):(\w+)          # 7: bind variable
    """, re.X | re.S)


def _translate(sql, params):
    """Oracle-style binds -> psycopg ``%s`` + ordered param list."""
    if params is None:
        params = []
    is_map = isinstance(params, dict)
    if not is_map:
        params = list(params)
    out_params = []
    positional_seen = []

    def repl(m):
        if m.group(1) or m.group(2) or m.group(3) or m.group(4):
            return m.group(0).replace('%', '%%')   # psycopg parses the whole text
        if m.group(5):
            return m.group(0)
        if m.group(6):
            return '%%'
        name = m.group(7)
        if is_map:
            if name in params:
                out_params.append(params[name])
            elif name.lower() in params:
                out_params.append(params[name.lower()])
            elif name.upper() in params:
                out_params.append(params[name.upper()])
            else:
                raise DatabaseError(_ErrInfo(1008, f'ORA-01008: not all variables bound (:{name})'))
            return '%s'
        # positional list: oracledb binds by position of first appearance of
        # each distinct name; repeated names reuse the same value.
        if name not in positional_seen:
            positional_seen.append(name)
        idx = positional_seen.index(name)
        if idx >= len(params):
            raise DatabaseError(_ErrInfo(1008, f'ORA-01008: not all variables bound (:{name})'))
        out_params.append(params[idx])
        return '%s'

    new_sql = _BIND_RE.sub(repl, sql)
    return new_sql, [_adapt(p) for p in out_params]


def _adapt(value):
    if isinstance(value, str) and value == '':
        return None                    # Oracle: '' IS NULL
    if isinstance(value, bool):
        return int(value)              # Oracle has no BOOLEAN; columns are NUMBER(1)
    if isinstance(value, _dt.datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)  # columns are local-time TIMESTAMP (Oracle DATE)
    return value


# ------------------------------------------------------------ cursor/conn
class _Description(tuple):
    pass


class Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._cur = psycopg.ClientCursor(conn._raw)
        self._last_sql = None

    # -- execution --------------------------------------------------------
    def execute(self, statement, parameters=None, **kwargs):
        if kwargs and parameters is None:
            parameters = kwargs
        sql, params = _translate(statement, parameters)
        self._last_sql = sql
        self._run(lambda: self._cur.execute(sql, params))
        return self

    def executemany(self, statement, seq_of_parameters):
        rows = list(seq_of_parameters)
        if not rows:
            return
        sql, _ = _translate(statement, rows[0])
        self._last_sql = sql
        batch = [_translate(statement, r)[1] for r in rows]
        self._run(lambda: self._cur.executemany(sql, batch))

    def _run(self, fn):
        raw = self._conn._raw
        use_sp = not raw.autocommit
        name = None
        try:
            if use_sp:
                self._conn._sp_counter += 1
                name = f'ora_stmt_{self._conn._sp_counter}'
                raw.execute(f'SAVEPOINT {name}')          # own cursor: keeps results on self._cur
            fn()
            if name:
                raw.execute(f'RELEASE SAVEPOINT {name}')
        except psycopg.Error as exc:
            if name:
                try:
                    raw.execute(f'ROLLBACK TO SAVEPOINT {name}')
                except psycopg.Error:
                    pass
            err = _wrap_error(exc)
            _log_sql_error(self._last_sql, err)
            raise err from exc

    def callproc(self, name, parameters=None):
        # The only Oracle procedure the app ever called.
        if name.upper() == 'DBMS_SESSION.SET_IDENTIFIER':
            self._conn.set_client_identifier((parameters or [None])[0])
            return parameters
        raise DatabaseError(_ErrInfo(6550, f'ORA-06550: unsupported procedure {name}'))

    # -- fetching ---------------------------------------------------------
    def fetchone(self):
        try:
            return self._cur.fetchone()
        except psycopg.ProgrammingError:
            return None

    def fetchall(self):
        try:
            return self._cur.fetchall()
        except psycopg.ProgrammingError:
            return []

    def fetchmany(self, size=None):
        try:
            return self._cur.fetchmany(size or self.arraysize)
        except psycopg.ProgrammingError:
            return []

    def __iter__(self):
        row = self.fetchone()
        while row is not None:
            yield row
            row = self.fetchone()

    @property
    def description(self):
        d = self._cur.description
        if d is None:
            return None
        return _Description(tuple([c.name.upper()] + list(c[1:])) for c in d)

    @property
    def rowcount(self):
        return self._cur.rowcount

    arraysize = 100

    def close(self):
        self._cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Connection:
    def __init__(self, raw):
        self._raw = raw
        self._sp_counter = 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        try:
            self._raw.commit()
        except psycopg.Error as exc:
            raise _wrap_error(exc) from exc

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if not self._raw.closed:
            try:
                self._raw.rollback()
            finally:
                self._raw.close()

    def set_client_identifier(self, identifier):
        with psycopg.ClientCursor(self._raw) as c:
            c.execute("SELECT set_config('app.client_identifier', %s, false)", [identifier or 'DIRECT_DB_EDIT'])
        self._raw.commit()

    @property
    def autocommit(self):
        return self._raw.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._raw.autocommit = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()          # oracledb semantics: no implicit commit
        return False


def _conninfo():
    # Django settings and raw modules share the same variables.
    return dict(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=os.environ.get('DB_PORT', '5432'),
        dbname=os.environ.get('DB_NAME', 'soorty'),
        user=os.environ.get('DB_USER', 'soorty'),
        password=os.environ.get('DB_PASSWORD', ''),
    )


def connect(username=None, **overrides):
    params = _conninfo()
    params.update(overrides)
    try:
        raw = psycopg.connect(**params, application_name='soorty-app',
                              options=f"-c TimeZone={os.environ.get('DB_TIMEZONE', 'Asia/Karachi')}")
    except psycopg.Error as exc:
        raise _wrap_error(exc) from exc
    raw.adapters.register_loader('numeric', _NumericLoader)
    conn = Connection(raw)
    conn.set_client_identifier(username if username else 'DIRECT_DB_EDIT')
    return conn


