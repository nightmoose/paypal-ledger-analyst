import pytest
from ledger import sqlguard
from ledger.sqlguard import UnsafeSQL

OK = ["SELECT 1", "select * from invoices where status = 'SENT';", "WITH x AS (SELECT 1 a) SELECT a FROM x",
      "-- comment\nSELECT count(*) FROM orders", "SELECT 'drop table orders' AS s"]
BAD = ["DELETE FROM orders", "DROP TABLE invoices", "INSERT INTO orders VALUES (1)", "UPDATE invoices SET status='PAID'",
       "SELECT 1; DROP TABLE orders", "ATTACH 'x.db' AS x", "COPY orders TO 'out.csv'", "PRAGMA database_list",
       "SELECT * FROM read_csv('/etc/passwd')", "INSTALL httpfs", "CREATE TABLE t AS SELECT 1", "SET threads=1",
       "SELECT * FROM glob('/*')", "", "   ;  ", "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
       "SELECT getenv('HOME')", "EXPORT DATABASE '/tmp/x'"]


@pytest.mark.parametrize("q", OK)
def test_allows_select(q):
    assert sqlguard.check(q)


@pytest.mark.parametrize("q", BAD)
def test_blocks_writes(q):
    with pytest.raises(UnsafeSQL):
        sqlguard.check(q)


def test_db_connection_is_read_only():
    from ledger import db
    with pytest.raises(Exception):
        db.con().execute("CREATE TABLE z(a INT)")
