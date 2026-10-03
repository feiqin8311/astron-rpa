import sqlite3

import pytest
from astronverse.database import DatabaseType
from astronverse.database.core_unix import DatabaseCore


def test_sqlite_connect_execute_query(tmp_path):
    db_path = str(tmp_path / "t.sqlite")
    conn = DatabaseCore.connect({"sqlite_path": db_path}, DatabaseType.SQLite)
    assert DatabaseCore.execute(conn, "CREATE TABLE t (id INTEGER, name TEXT)")
    assert DatabaseCore.execute(conn, "INSERT INTO t VALUES (1, 'mac')")
    rows = DatabaseCore.query(conn, "SELECT id, name FROM t")
    assert '"name": "mac"' in rows
    DatabaseCore.disconnect(conn)
    sqlite3.connect(db_path).close()


def test_access_is_windows_only():
    with pytest.raises(Exception, match="Access"):
        DatabaseCore.connect({"access_path": "x.mdb"}, DatabaseType.Access)
