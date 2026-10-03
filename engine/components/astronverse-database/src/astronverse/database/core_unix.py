import sqlite3

from astronverse.database import DatabaseType
from astronverse.database.core import IDatabaseCore


class DatabaseCore(IDatabaseCore):
    @staticmethod
    def connect(db_info_dict: dict, db_type: DatabaseType = DatabaseType.MySQL):
        if db_type == DatabaseType.MySQL:
            import pymysql

            db_conn = pymysql.connect(
                host=db_info_dict["host"],
                port=int(db_info_dict.get("port") or db_info_dict.get("PORT") or 3306),
                user=db_info_dict["user"],
                password=db_info_dict["password"],
                database=db_info_dict["database"],
                charset=db_info_dict.get("charset", "utf8").replace("-", ""),
            )
        elif db_type == DatabaseType.SQLServer:
            try:
                import pyodbc
            except ImportError as e:
                raise Exception("SQL Server 需要 pyodbc 与 unixODBC 驱动") from e
            server = "{},{}".format(db_info_dict.get("host", ""), int(db_info_dict.get("port", 1433)))
            last_error = None
            db_conn = None
            for driver in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "FreeTDS"):
                conn_str = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={server};"
                    f"DATABASE={db_info_dict.get('database', '')};"
                    f"UID={db_info_dict.get('user', '')};"
                    f"PWD={db_info_dict.get('password', '')};"
                    "TrustServerCertificate=yes;"
                )
                try:
                    db_conn = pyodbc.connect(conn_str)
                    break
                except Exception as e:
                    last_error = e
            if db_conn is None:
                raise Exception(f"SQL Server 连接失败（需要 unixODBC 驱动）: {last_error}")
        elif db_type == DatabaseType.Oracle:
            import cx_Oracle

            if db_info_dict.get("service_type", "") == "service":
                service = db_info_dict.get("service", "")
            else:
                service = db_info_dict.get("sid", "")
            db_conn = cx_Oracle.connect(
                user=db_info_dict.get("user", ""),
                password=db_info_dict.get("password", ""),
                dsn=f"{db_info_dict.get('host', '')}:{int(db_info_dict.get('port', 1521))}/{service}",
            )
        elif db_type == DatabaseType.PostgreSQL:
            import psycopg2

            db_conn = psycopg2.connect(
                database=db_info_dict.get("database", ""),
                user=db_info_dict.get("user", ""),
                password=db_info_dict.get("password", ""),
                host=db_info_dict.get("host", ""),
                port=int(db_info_dict.get("port", 5432)),
            )
        elif db_type == DatabaseType.SQLite:
            db_conn = sqlite3.connect(f"{db_info_dict.get('sqlite_path', '')}")
        elif db_type == DatabaseType.Access:
            raise Exception("Access 数据库仅支持 Windows（需要 Microsoft Access ODBC 驱动）")
        elif db_type == DatabaseType.DB2:
            raise Exception("DB2 暂不支持")
        else:
            raise Exception("找不到该数据库类型!")
        return db_conn

    @staticmethod
    def disconnect(db_conn: object):
        db_conn.close()

    @staticmethod
    def execute(db_conn: object, sql_str: str) -> bool:
        cursor = db_conn.cursor()
        try:
            cursor.execute(sql_str)
            db_conn.commit()
        except Exception:
            db_conn.rollback()
            return False
        return True

    @staticmethod
    def query(db_conn: object, sql_str: str) -> str:
        import datetime
        import json
        from decimal import Decimal

        cursor = db_conn.cursor()
        res_list = []

        cursor.execute(sql_str)
        key_info = cursor.description
        key_tup = [key[0] for key in key_info]

        result_arr = cursor.fetchall()

        for results in result_arr:
            new_result = []
            for result in results:
                if isinstance(result, datetime.datetime):
                    new_result.append(result.strftime("%Y-%m-%d %H:%M:%S"))
                elif isinstance(result, datetime.date):
                    new_result.append(result.strftime("%Y-%m-%d"))
                elif isinstance(result, Decimal):
                    new_result.append(str(result))
                else:
                    new_result.append(result)
            row_data = dict(zip(key_tup, new_result, strict=False))
            res_list.append(row_data)
        try:
            res_list = json.dumps(res_list, ensure_ascii=False)
        except Exception:
            pass
        return res_list
